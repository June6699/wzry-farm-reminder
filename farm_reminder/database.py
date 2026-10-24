import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

from .paths import DB_PATH
from .planner import is_weekend_bonus_time


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS field_slots (
    slot_id TEXT PRIMARY KEY,
    field_no INTEGER NOT NULL,
    row_no INTEGER NOT NULL,
    col_no INTEGER NOT NULL,
    sort_order INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS slot_states (
    slot_id TEXT PRIMARY KEY,
    phase TEXT NOT NULL DEFAULT 'idle',
    crop_id TEXT,
    strategy_id TEXT,
    strategy_name TEXT,
    planned_start_at TEXT,
    planted_at TEXT,
    harvest_at TEXT,
    watering_times_json TEXT DEFAULT '[]',
    expected_cost REAL DEFAULT 0,
    expected_income REAL DEFAULT 0,
    expected_net_income REAL DEFAULT 0,
    note TEXT,
    mutation_entries_json TEXT DEFAULT '[]',
    mutation_multiplier REAL DEFAULT 1,
    blessing_count INTEGER DEFAULT 0,
    hero_flag INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wallet_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    amount_signed REAL NOT NULL,
    balance_after REAL NOT NULL,
    occurred_at TEXT NOT NULL,
    ref_type TEXT,
    ref_id TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    slot_id TEXT,
    crop_id TEXT,
    related_name TEXT,
    amount REAL DEFAULT 0,
    note TEXT
);

CREATE TABLE IF NOT EXISTS raid_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    counterparty_name TEXT,
    slot_id TEXT,
    crop_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price_snapshot REAL NOT NULL,
    amount REAL NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS theft_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    cycle_id TEXT,
    slot_id TEXT,
    thief_name TEXT,
    crop_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price_snapshot REAL NOT NULL,
    loss_amount REAL NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS seed_inventory (
    crop_id TEXT PRIMARY KEY,
    quantity INTEGER NOT NULL DEFAULT 0,
    source TEXT DEFAULT '',
    note TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fruit_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crop_id TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    mutation_entries_json TEXT DEFAULT '[]',
    mutation_multiplier REAL DEFAULT 1,
    hero_flag INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'in_stock',
    harvested_at TEXT NOT NULL,
    slot_id TEXT,
    sold_at TEXT,
    sell_total REAL,
    note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS blessing_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    counterparty_name TEXT,
    slot_id TEXT,
    crop_id TEXT,
    note TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cultivation_progress (
    crop_id TEXT PRIMARY KEY,
    points INTEGER NOT NULL DEFAULT 0
);
"""

SLOT_STATE_EXTRA_COLUMNS = {
    "mutation_entries_json": "TEXT DEFAULT '[]'",
    "mutation_multiplier": "REAL DEFAULT 1",
    "blessing_count": "INTEGER DEFAULT 0",
    "hero_flag": "INTEGER DEFAULT 0",
}


def _now_iso():
    return datetime.now().isoformat(timespec="minutes")


def daily_reset_boundary(now=None, reset_time="05:00"):
    """以每日 05:00 为界，返回当前「祝福/偷菜日」的起始时刻。"""
    now = now or datetime.now()
    hour, minute = (int(part) for part in reset_time.split(":"))
    boundary = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < boundary:
        boundary -= timedelta(days=1)
    return boundary


class Database:
    def __init__(self, path=DB_PATH):
        self.path = path

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self):
        with self._connect() as connection:
            connection.executescript(SCHEMA_SQL)
            self._migrate_slot_states(connection)
            self._seed_field_slots(connection)
            self._recalculate_wallet_balances(connection)
            connection.commit()

    @staticmethod
    def _migrate_slot_states(connection):
        existing_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(slot_states)").fetchall()
        }
        for column_name, column_type in SLOT_STATE_EXTRA_COLUMNS.items():
            if column_name not in existing_columns:
                connection.execute(
                    f"ALTER TABLE slot_states ADD COLUMN {column_name} {column_type}"
                )

    def _seed_field_slots(self, connection):
        existing = connection.execute("SELECT COUNT(*) AS count_value FROM field_slots").fetchone()["count_value"]
        if existing:
            return

        sort_order = 0
        for field_no in range(1, 5):
            for row_no in range(1, 4):
                for col_no in range(1, 5):
                    sort_order += 1
                    slot_id = f"F{field_no}-R{row_no}-C{col_no}"
                    connection.execute(
                        """
                        INSERT INTO field_slots (slot_id, field_no, row_no, col_no, sort_order)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (slot_id, field_no, row_no, col_no, sort_order),
                    )

    def _current_balance(self, connection):
        row = connection.execute(
            "SELECT COALESCE(SUM(amount_signed), 0) AS balance_value FROM wallet_ledger"
        ).fetchone()
        return float(row["balance_value"])

    def _recalculate_wallet_balances(self, connection):
        rows = connection.execute(
            "SELECT id, amount_signed FROM wallet_ledger ORDER BY id ASC"
        ).fetchall()
        running = 0.0
        for row in rows:
            running += float(row["amount_signed"] or 0)
            connection.execute(
                "UPDATE wallet_ledger SET balance_after = ? WHERE id = ?",
                (round(running, 2), row["id"]),
            )

    def _insert_ledger(self, connection, ledger_type, amount_signed, occurred_at, note, ref_type=None, ref_id=None):
        balance_after = round(self._current_balance(connection) + float(amount_signed), 2)
        cursor = connection.execute(
            """
            INSERT INTO wallet_ledger (type, amount_signed, balance_after, occurred_at, ref_type, ref_id, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ledger_type,
                round(float(amount_signed), 2),
                balance_after,
                occurred_at,
                ref_type,
                ref_id,
                note,
            ),
        )
        return cursor.lastrowid, balance_after

    def get_wallet_summary(self):
        today_prefix = datetime.now().strftime("%Y-%m-%d")
        with self._connect() as connection:
            balance = self._current_balance(connection)
            income = connection.execute(
                """
                SELECT COALESCE(SUM(amount_signed), 0) AS total
                FROM wallet_ledger
                WHERE amount_signed > 0
                """
            ).fetchone()["total"]
            expense = connection.execute(
                """
                SELECT COALESCE(ABS(SUM(amount_signed)), 0) AS total
                FROM wallet_ledger
                WHERE amount_signed < 0
                """
            ).fetchone()["total"]
            today_income = connection.execute(
                """
                SELECT COALESCE(SUM(amount_signed), 0) AS total
                FROM wallet_ledger
                WHERE amount_signed > 0 AND occurred_at LIKE ?
                """,
                (f"{today_prefix}%",),
            ).fetchone()["total"]
            today_expense = connection.execute(
                """
                SELECT COALESCE(ABS(SUM(amount_signed)), 0) AS total
                FROM wallet_ledger
                WHERE amount_signed < 0 AND occurred_at LIKE ?
                """,
                (f"{today_prefix}%",),
            ).fetchone()["total"]
            planned_rows = connection.execute(
                """
                SELECT
                    COALESCE(SUM(expected_cost), 0) AS cost_total,
                    COALESCE(SUM(expected_income), 0) AS income_total,
                    COALESCE(SUM(expected_net_income), 0) AS net_total
                FROM slot_states
                """
            ).fetchone()
        return {
            "balance": round(balance, 2),
            "total_income": round(income, 2),
            "total_expense": round(expense, 2),
            "today_income": round(today_income, 2),
            "today_expense": round(today_expense, 2),
            "today_net": round(today_income - today_expense, 2),
            "planned_cost": round(planned_rows["cost_total"], 2),
            "planned_income": round(planned_rows["income_total"], 2),
            "planned_net": round(planned_rows["net_total"], 2),
        }

    def get_wallet_ledger(self, limit=40):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, type, amount_signed, balance_after, occurred_at, ref_type, ref_id, note
                FROM wallet_ledger
                ORDER BY occurred_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_raids(self, limit=12):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, direction, occurred_at, counterparty_name, slot_id, crop_id,
                       quantity, unit_price_snapshot, amount, note
                FROM raid_logs
                ORDER BY occurred_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_fields(self, unlocked_slot_count):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    f.slot_id, f.field_no, f.row_no, f.col_no, f.sort_order,
                    s.phase, s.crop_id, s.strategy_id, s.strategy_name,
                    s.planned_start_at, s.planted_at, s.harvest_at,
                    s.watering_times_json, s.expected_cost, s.expected_income,
                    s.expected_net_income, s.note, s.updated_at,
                    s.mutation_entries_json, s.mutation_multiplier,
                    s.blessing_count, s.hero_flag
                FROM field_slots AS f
                LEFT JOIN slot_states AS s ON s.slot_id = f.slot_id
                ORDER BY f.sort_order
                """
            ).fetchall()

        now = datetime.now()
        grouped = defaultdict(list)
        for row in rows:
            slot_data = dict(row)
            unlocked = slot_data["sort_order"] <= unlocked_slot_count
            harvest_at = self._parse_iso(slot_data.get("harvest_at"))
            planned_start_at = self._parse_iso(slot_data.get("planned_start_at"))
            planted_at = self._parse_iso(slot_data.get("planted_at"))

            remaining_minutes = None
            remaining_label = ""
            status_label = "未启用"
            if unlocked:
                status_label = "空闲"
                if slot_data.get("crop_id"):
                    phase = slot_data.get("phase") or "planned"
                    if phase == "planned":
                        status_label = "已规划"
                        if planned_start_at:
                            delta = planned_start_at - now
                            remaining_minutes = max(0, int(delta.total_seconds() // 60))
                            if delta.total_seconds() > 0:
                                remaining_label = self._format_countdown(delta, prefix="计划开始")
                            else:
                                remaining_label = "计划时间已过，待手动开始"
                    elif phase == "planted":
                        if harvest_at:
                            delta = harvest_at - now
                            remaining_minutes = int(delta.total_seconds() // 60)
                            if delta.total_seconds() <= 0:
                                status_label = "可收获"
                                remaining_label = "已到收获时间"
                            else:
                                status_label = "生长中"
                                remaining_label = self._format_countdown(delta, prefix="剩余")
                        elif planted_at:
                            status_label = "生长中"
                    elif phase == "ready":
                        status_label = "可收获"
                        remaining_label = "已到收获时间"

            slot_data.update(
                {
                    "is_unlocked": unlocked,
                    "remaining_minutes": remaining_minutes,
                    "remaining_label": remaining_label,
                    "status_label": status_label,
                    "watering_times": json.loads(slot_data.get("watering_times_json") or "[]"),
                    "mutation_entries": json.loads(slot_data.get("mutation_entries_json") or "[]"),
                    "mutation_multiplier": float(slot_data.get("mutation_multiplier") or 1),
                    "blessing_count": int(slot_data.get("blessing_count") or 0),
                    "hero_flag": bool(slot_data.get("hero_flag")),
                }
            )
            grouped[row["field_no"]].append(slot_data)

        fields = []
        for field_no in range(1, 5):
            slots = grouped[field_no]
            unlocked_count = sum(1 for slot in slots if slot["is_unlocked"])
            fields.append(
                {
                    "field_no": field_no,
                    "slots": slots,
                    "unlocked_slot_count": unlocked_count,
                    "planned_slot_count": sum(1 for slot in slots if slot.get("phase") == "planned"),
                    "active_slot_count": sum(1 for slot in slots if slot.get("phase") == "planted"),
                }
            )
        return fields

    def get_slot_state_rows(self):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT slot_id, phase, crop_id, strategy_id, strategy_name, planned_start_at, planted_at,
                       harvest_at, watering_times_json, expected_cost, expected_income, expected_net_income,
                       note, updated_at, mutation_entries_json, mutation_multiplier,
                       blessing_count, hero_flag
                FROM slot_states
                ORDER BY slot_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_farm_summary(self):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_slots,
                    SUM(CASE WHEN phase = 'planned' THEN 1 ELSE 0 END) AS planned_slots,
                    SUM(CASE WHEN phase = 'planted' THEN 1 ELSE 0 END) AS active_slots,
                    SUM(CASE WHEN phase = 'ready' THEN 1 ELSE 0 END) AS ready_slots,
                    COALESCE(SUM(expected_cost), 0) AS expected_cost,
                    COALESCE(SUM(expected_income), 0) AS expected_income,
                    COALESCE(SUM(expected_net_income), 0) AS expected_net_income
                FROM slot_states
                """
            ).fetchone()
        return {
            "assigned_slots": row["total_slots"] or 0,
            "planned_slots": row["planned_slots"] or 0,
            "active_slots": row["active_slots"] or 0,
            "ready_slots": row["ready_slots"] or 0,
            "expected_cost": round(row["expected_cost"] or 0, 2),
            "expected_income": round(row["expected_income"] or 0, 2),
            "expected_net_income": round(row["expected_net_income"] or 0, 2),
        }

    def resolve_slot_ids(self, unlocked_slot_count, scope):
        mode = (scope or {}).get("mode") or "all"
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT slot_id, field_no, sort_order
                FROM field_slots
                ORDER BY sort_order
                """
            ).fetchall()

        unlocked_rows = [row for row in rows if row["sort_order"] <= unlocked_slot_count]
        if mode == "slot":
            slot_id = (scope or {}).get("slot_id")
            return [slot_id] if slot_id else []
        if mode == "field":
            field_no = int((scope or {}).get("field_no") or 0)
            return [row["slot_id"] for row in unlocked_rows if row["field_no"] == field_no]
        return [row["slot_id"] for row in unlocked_rows]

    def apply_plan(self, assignments):
        with self._connect() as connection:
            for assignment in assignments:
                connection.execute(
                    """
                    INSERT INTO slot_states (
                        slot_id, phase, crop_id, strategy_id, strategy_name, planned_start_at,
                        planted_at, harvest_at, watering_times_json, expected_cost,
                        expected_income, expected_net_income, note, updated_at
                    )
                    VALUES (?, 'planned', ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(slot_id) DO UPDATE SET
                        phase = excluded.phase,
                        crop_id = excluded.crop_id,
                        strategy_id = excluded.strategy_id,
                        strategy_name = excluded.strategy_name,
                        planned_start_at = excluded.planned_start_at,
                        planted_at = excluded.planted_at,
                        harvest_at = excluded.harvest_at,
                        watering_times_json = excluded.watering_times_json,
                        expected_cost = excluded.expected_cost,
                        expected_income = excluded.expected_income,
                        expected_net_income = excluded.expected_net_income,
                        note = excluded.note,
                        updated_at = excluded.updated_at
                    """,
                    (
                        assignment["slot_id"],
                        assignment["crop_id"],
                        assignment["strategy_id"],
                        assignment["strategy_name"],
                        assignment["planned_start_at"],
                        assignment["harvest_at"],
                        json.dumps(assignment.get("watering_times", []), ensure_ascii=False),
                        assignment["expected_cost"],
                        assignment["expected_income"],
                        assignment["expected_net_income"],
                        assignment.get("note", ""),
                        _now_iso(),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO activity_logs (event_type, occurred_at, slot_id, crop_id, related_name, amount, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "plan",
                        assignment["planned_start_at"],
                        assignment["slot_id"],
                        assignment["crop_id"],
                        assignment["strategy_name"],
                        assignment["expected_net_income"],
                        "应用规划方案",
                    ),
                )
            connection.commit()

    def update_slot_states(self, slot_ids, patch):
        if not slot_ids:
            return 0

        with self._connect() as connection:
            existing_rows = connection.execute(
                f"""
                SELECT slot_id, phase, crop_id, strategy_id, strategy_name, planned_start_at,
                       planted_at, harvest_at, watering_times_json, expected_cost,
                       expected_income, expected_net_income, note,
                       mutation_entries_json, mutation_multiplier, blessing_count, hero_flag
                FROM slot_states
                WHERE slot_id IN ({",".join("?" for _ in slot_ids)})
                """,
                tuple(slot_ids),
            ).fetchall()
            existing_map = {row["slot_id"]: dict(row) for row in existing_rows}

            for slot_id in slot_ids:
                row = existing_map.get(slot_id, {})
                merged = {
                    "phase": patch.get("phase", row.get("phase", "planned")),
                    "crop_id": patch.get("crop_id", row.get("crop_id")),
                    "strategy_id": patch.get("strategy_id", row.get("strategy_id", "manual")),
                    "strategy_name": patch.get("strategy_name", row.get("strategy_name", "手动编辑")),
                    "planned_start_at": patch.get("planned_start_at", row.get("planned_start_at")),
                    "planted_at": patch.get("planted_at", row.get("planted_at")),
                    "harvest_at": patch.get("harvest_at", row.get("harvest_at")),
                    "watering_times_json": json.dumps(patch.get("watering_times", json.loads(row.get("watering_times_json") or "[]")), ensure_ascii=False),
                    "expected_cost": patch.get("expected_cost", row.get("expected_cost", 0)),
                    "expected_income": patch.get("expected_income", row.get("expected_income", 0)),
                    "expected_net_income": patch.get("expected_net_income", row.get("expected_net_income", 0)),
                    "note": patch.get("note", row.get("note", "")),
                    "mutation_entries_json": json.dumps(patch.get("mutation_entries", json.loads(row.get("mutation_entries_json") or "[]")), ensure_ascii=False),
                    "mutation_multiplier": patch.get("mutation_multiplier", row.get("mutation_multiplier", 1)),
                    "blessing_count": patch.get("blessing_count", row.get("blessing_count", 0)),
                    "hero_flag": patch.get("hero_flag", row.get("hero_flag", 0)),
                }
                connection.execute(
                    """
                    INSERT INTO slot_states (
                        slot_id, phase, crop_id, strategy_id, strategy_name, planned_start_at,
                        planted_at, harvest_at, watering_times_json, expected_cost,
                        expected_income, expected_net_income, note,
                        mutation_entries_json, mutation_multiplier, blessing_count, hero_flag, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(slot_id) DO UPDATE SET
                        phase = excluded.phase,
                        crop_id = excluded.crop_id,
                        strategy_id = excluded.strategy_id,
                        strategy_name = excluded.strategy_name,
                        planned_start_at = excluded.planned_start_at,
                        planted_at = excluded.planted_at,
                        harvest_at = excluded.harvest_at,
                        watering_times_json = excluded.watering_times_json,
                        expected_cost = excluded.expected_cost,
                        expected_income = excluded.expected_income,
                        expected_net_income = excluded.expected_net_income,
                        note = excluded.note,
                        mutation_entries_json = excluded.mutation_entries_json,
                        mutation_multiplier = excluded.mutation_multiplier,
                        blessing_count = excluded.blessing_count,
                        hero_flag = excluded.hero_flag,
                        updated_at = excluded.updated_at
                    """,
                    (
                        slot_id,
                        merged["phase"],
                        merged["crop_id"],
                        merged["strategy_id"],
                        merged["strategy_name"],
                        merged["planned_start_at"],
                        merged["planted_at"],
                        merged["harvest_at"],
                        merged["watering_times_json"],
                        merged["expected_cost"],
                        merged["expected_income"],
                        merged["expected_net_income"],
                        merged["note"],
                        merged["mutation_entries_json"],
                        merged["mutation_multiplier"],
                        merged["blessing_count"],
                        int(bool(merged["hero_flag"])),
                        _now_iso(),
                    ),
                )
            connection.commit()
        return len(slot_ids)

    def set_slot_mutation(self, slot_id, entries, multiplier, hero_flag, expected_income, expected_net_income):
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE slot_states
                SET mutation_entries_json = ?,
                    mutation_multiplier = ?,
                    hero_flag = ?,
                    expected_income = ?,
                    expected_net_income = ?,
                    updated_at = ?
                WHERE slot_id = ? AND crop_id IS NOT NULL
                """,
                (
                    json.dumps(entries, ensure_ascii=False),
                    round(float(multiplier), 4),
                    int(bool(hero_flag)),
                    round(float(expected_income), 2),
                    round(float(expected_net_income), 2),
                    _now_iso(),
                    slot_id,
                ),
            )
            connection.commit()
            return bool(updated.rowcount)

    def clear_slot_states(self, slot_ids):
        if not slot_ids:
            return 0
        with self._connect() as connection:
            connection.execute(
                f"DELETE FROM slot_states WHERE slot_id IN ({','.join('?' for _ in slot_ids)})",
                tuple(slot_ids),
            )
            connection.commit()
        return len(slot_ids)

    def confirm_planted(self, slot_ids, started_at, crop_map=None, reset_time="05:00"):
        """开始种植：优先消耗种子背包，缺口按种子原价自动购买入账。"""
        if not slot_ids:
            return {"processed_count": 0, "seed_notes": []}
        crop_map = crop_map or {}
        start_dt = self._parse_iso(started_at) or datetime.now()
        start_text = start_dt.isoformat(timespec="minutes")

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT slot_id, crop_id, phase, planned_start_at, harvest_at, expected_cost
                FROM slot_states
                WHERE slot_id IN ({','.join('?' for _ in slot_ids)})
                """,
                tuple(slot_ids),
            ).fetchall()
            process_rows = [dict(row) for row in rows if row["crop_id"] and row["phase"] != "planted"]
            if not process_rows:
                return {"processed_count": 0, "seed_notes": []}

            grouped = defaultdict(lambda: {"count": 0, "cost": 0.0})
            for row in process_rows:
                base_start = self._parse_iso(row["planned_start_at"]) or start_dt
                harvest_at = self._parse_iso(row["harvest_at"]) or start_dt
                duration = harvest_at - base_start
                if duration.total_seconds() <= 0:
                    duration = timedelta(minutes=1)
                new_harvest_at = (start_dt + duration).isoformat(timespec="minutes")

                connection.execute(
                    """
                    UPDATE slot_states
                    SET phase = 'planted',
                        planned_start_at = ?,
                        planted_at = ?,
                        harvest_at = ?,
                        updated_at = ?
                    WHERE slot_id = ?
                    """,
                    (start_text, start_text, new_harvest_at, _now_iso(), row["slot_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO activity_logs (event_type, occurred_at, slot_id, crop_id, related_name, amount, note)
                    VALUES ('plant', ?, ?, ?, '', ?, '手动开始种植')
                    """,
                    (start_text, row["slot_id"], row["crop_id"], -float(row["expected_cost"] or 0)),
                )
                grouped[row["crop_id"]]["count"] += 1
                grouped[row["crop_id"]]["cost"] += float(row["expected_cost"] or 0)

            seed_notes = []
            for crop_id, item in grouped.items():
                crop_info = crop_map.get(crop_id, {})
                crop_name = crop_info.get("name") or crop_id
                needed = item["count"]
                from_bag = 0
                if crop_info:
                    bag_row = connection.execute(
                        "SELECT quantity FROM seed_inventory WHERE crop_id = ?",
                        (crop_id,),
                    ).fetchone()
                    if bag_row and int(bag_row["quantity"] or 0) > 0:
                        from_bag = min(needed, int(bag_row["quantity"]))
                        remaining_qty = int(bag_row["quantity"]) - from_bag
                        if remaining_qty > 0:
                            connection.execute(
                                """
                                UPDATE seed_inventory SET quantity = ?, updated_at = ?
                                WHERE crop_id = ?
                                """,
                                (remaining_qty, _now_iso(), crop_id),
                            )
                        else:
                            connection.execute(
                                "DELETE FROM seed_inventory WHERE crop_id = ?",
                                (crop_id,),
                            )

                purchased = needed - from_bag
                purchased_cost = purchased * float(crop_info.get("seed_cost") or 0)
                if purchased > 0:
                    self._insert_ledger(
                        connection,
                        "seed_purchase",
                        -purchased_cost,
                        start_text,
                        f"种植 {crop_name} × {needed}（背包 {from_bag} + 购买 {purchased}）",
                        ref_type="slot_states",
                    )
                seed_notes.append(
                    f"{crop_name}×{needed}（背包 {from_bag} + 购买 {purchased}）"
                )
            connection.commit()
        return {"processed_count": len(process_rows), "seed_notes": seed_notes}

    def water_slots(self, slot_ids, occurred_at, reduce_minutes):
        if not slot_ids:
            return {"processed_count": 0}

        occur_dt = self._parse_iso(occurred_at) or datetime.now()
        occur_text = occur_dt.isoformat(timespec="minutes")
        reduce_value = max(0, int(reduce_minutes or 0))

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT slot_id, crop_id, phase, harvest_at, watering_times_json
                FROM slot_states
                WHERE slot_id IN ({','.join('?' for _ in slot_ids)})
                """,
                tuple(slot_ids),
            ).fetchall()
            process_rows = [dict(row) for row in rows if row["crop_id"] and row["phase"] == "planted"]
            if not process_rows:
                return {"processed_count": 0}

            for row in process_rows:
                current_harvest = self._parse_iso(row["harvest_at"]) or occur_dt
                watered_history = json.loads(row.get("watering_times_json") or "[]")
                watered_history.append(
                    {
                        "occurred_at": occur_text,
                        "reduce_minutes": reduce_value,
                    }
                )
                new_harvest = current_harvest - timedelta(minutes=reduce_value)
                new_phase = "ready" if new_harvest <= occur_dt else "planted"
                connection.execute(
                    """
                    UPDATE slot_states
                    SET phase = ?,
                        harvest_at = ?,
                        watering_times_json = ?,
                        updated_at = ?
                    WHERE slot_id = ?
                    """,
                    (
                        new_phase,
                        new_harvest.isoformat(timespec="minutes"),
                        json.dumps(watered_history, ensure_ascii=False),
                        _now_iso(),
                        row["slot_id"],
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO activity_logs (event_type, occurred_at, slot_id, crop_id, related_name, amount, note)
                    VALUES ('water', ?, ?, ?, '', 0, ?)
                    """,
                    (
                        occur_text,
                        row["slot_id"],
                        row["crop_id"],
                        f"浇水减少 {reduce_value} 分钟",
                    ),
                )
            connection.commit()
        return {"processed_count": len(process_rows), "reduce_minutes": reduce_value}

    def harvest_slots(self, slot_ids, occurred_at, cultivation_points=10):
        """收获不再直接入账：产出果实批次进背包，培育值累计，卖出时才结算。"""
        if not slot_ids:
            return {"processed_count": 0, "fruit_batches": []}
        occur_dt = self._parse_iso(occurred_at) or datetime.now()
        occur_text = occur_dt.isoformat(timespec="minutes")

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT slot_id, crop_id, expected_income, harvest_at,
                       mutation_entries_json, mutation_multiplier, hero_flag
                FROM slot_states
                WHERE slot_id IN ({','.join('?' for _ in slot_ids)})
                  AND crop_id IS NOT NULL
                """,
                tuple(slot_ids),
            ).fetchall()
            process_rows = [dict(row) for row in rows]
            if not process_rows:
                return {"processed_count": 0, "fruit_batches": []}

            fruit_batches = []
            cultivation_delta = defaultdict(int)
            for row in process_rows:
                entries = json.loads(row.get("mutation_entries_json") or "[]")
                multiplier = float(row.get("mutation_multiplier") or 1)
                ripen_dt = self._parse_iso(row.get("harvest_at")) or occur_dt
                quantity = 2 if is_weekend_bonus_time(ripen_dt) else 1

                connection.execute(
                    """
                    INSERT INTO fruit_inventory (
                        crop_id, quantity, mutation_entries_json, mutation_multiplier, hero_flag,
                        status, harvested_at, slot_id, note
                    )
                    VALUES (?, ?, ?, ?, ?, 'in_stock', ?, ?, '')
                    """,
                    (
                        row["crop_id"],
                        quantity,
                        json.dumps(entries, ensure_ascii=False),
                        round(multiplier, 4),
                        int(bool(row.get("hero_flag"))),
                        occur_text,
                        row["slot_id"],
                    ),
                )
                fruit_note = f"收获入背包 ×{quantity}" + (f" · 词条×{multiplier}" if multiplier > 1 else "")
                connection.execute(
                    """
                    INSERT INTO activity_logs (event_type, occurred_at, slot_id, crop_id, related_name, amount, note)
                    VALUES ('harvest', ?, ?, ?, '', ?, ?)
                    """,
                    (occur_text, row["slot_id"], row["crop_id"], float(row["expected_income"] or 0), fruit_note),
                )
                fruit_batches.append(
                    {
                        "crop_id": row["crop_id"],
                        "quantity": quantity,
                        "mutation_entries": entries,
                        "mutation_multiplier": multiplier,
                    }
                )
                cultivation_delta[row["crop_id"]] += 1

            for crop_id, plot_count in cultivation_delta.items():
                connection.execute(
                    """
                    INSERT INTO cultivation_progress (crop_id, points)
                    VALUES (?, ?)
                    ON CONFLICT(crop_id) DO UPDATE SET
                        points = points + excluded.points
                    """,
                    (crop_id, plot_count * int(cultivation_points)),
                )

            connection.execute(
                f"DELETE FROM slot_states WHERE slot_id IN ({','.join('?' for _ in slot_ids)})",
                tuple(slot_ids),
            )
            connection.commit()
        return {"processed_count": len(process_rows), "fruit_batches": fruit_batches}

    # ---------------- 种子背包 ----------------

    def get_seed_inventory(self):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT crop_id, quantity, source, note, updated_at
                FROM seed_inventory
                WHERE quantity > 0
                ORDER BY updated_at DESC, crop_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def adjust_seed_inventory(self, crop_id, delta, source="", note=""):
        delta = int(delta or 0)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT quantity FROM seed_inventory WHERE crop_id = ?",
                (crop_id,),
            ).fetchone()
            current = int(row["quantity"]) if row else 0
            new_quantity = current + delta
            if new_quantity > 0:
                connection.execute(
                    """
                    INSERT INTO seed_inventory (crop_id, quantity, source, note, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(crop_id) DO UPDATE SET
                        quantity = excluded.quantity,
                        source = CASE WHEN excluded.source != '' THEN excluded.source ELSE seed_inventory.source END,
                        note = CASE WHEN excluded.note != '' THEN excluded.note ELSE seed_inventory.note END,
                        updated_at = excluded.updated_at
                    """,
                    (crop_id, new_quantity, source or "", note or "", _now_iso()),
                )
            elif row:
                connection.execute(
                    "DELETE FROM seed_inventory WHERE crop_id = ?",
                    (crop_id,),
                )
            connection.commit()
            final_quantity = max(0, new_quantity)
        return {"crop_id": crop_id, "quantity": final_quantity, "delta": delta}

    # ---------------- 果实背包 ----------------

    def get_fruit_inventory(self, status=None, limit=200):
        query = """
            SELECT id, crop_id, quantity, mutation_entries_json, mutation_multiplier, hero_flag,
                   status, harvested_at, slot_id, sold_at, sell_total, note
            FROM fruit_inventory
        """
        params = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY harvested_at DESC, id DESC LIMIT ?"
        params = params + (limit,)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["mutation_entries"] = json.loads(item.get("mutation_entries_json") or "[]")
            result.append(item)
        return result

    def sell_fruits(self, fruit_ids, unit_price_map, occurred_at=None):
        """按批次卖出果实并入账 fruit_sell。unit_price_map: {crop_id: 单株售价}"""
        if not fruit_ids:
            return {"sold_count": 0, "total_income": 0, "details": []}
        occur_dt = self._parse_iso(occurred_at) or datetime.now()
        occur_text = occur_dt.isoformat(timespec="minutes")

        with self._connect() as connection:
            placeholders = ",".join("?" for _ in fruit_ids)
            rows = connection.execute(
                f"""
                SELECT id, crop_id, quantity, mutation_entries_json, mutation_multiplier
                FROM fruit_inventory
                WHERE id IN ({placeholders}) AND status = 'in_stock'
                """,
                tuple(fruit_ids),
            ).fetchall()

            total_income = 0.0
            details = []
            grouped_income = defaultdict(lambda: {"count": 0, "income": 0.0})
            for row in rows:
                unit_price = float(unit_price_map.get(row["crop_id"], 0))
                multiplier = float(row["mutation_multiplier"] or 1)
                batch_total = round(int(row["quantity"]) * unit_price * multiplier, 2)
                entries = json.loads(row["mutation_entries_json"] or "[]")

                connection.execute(
                    """
                    UPDATE fruit_inventory
                    SET status = 'sold', sold_at = ?, sell_total = ?
                    WHERE id = ?
                    """,
                    (occur_text, batch_total, row["id"]),
                )
                grouped_income[row["crop_id"]]["count"] += int(row["quantity"])
                grouped_income[row["crop_id"]]["income"] += batch_total
                total_income += batch_total
                details.append(
                    {
                        "fruit_id": row["id"],
                        "crop_id": row["crop_id"],
                        "quantity": int(row["quantity"]),
                        "mutation_entries": entries,
                        "mutation_multiplier": multiplier,
                        "sell_total": batch_total,
                    }
                )

            for crop_id, item in grouped_income.items():
                self._insert_ledger(
                    connection,
                    "fruit_sell",
                    item["income"],
                    occur_text,
                    f"小摊卖出 {crop_id} × {item['count']}",
                    ref_type="fruit_inventory",
                )
            connection.commit()
        return {
            "sold_count": len(details),
            "total_income": round(total_income, 2),
            "details": details,
        }

    def get_collection(self):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT crop_id,
                       mutation_entries_json AS mutation_entries_json,
                       COUNT(*) AS batch_count,
                       SUM(quantity) AS total_quantity,
                       MAX(harvested_at) AS last_harvested_at
                FROM fruit_inventory
                GROUP BY crop_id, mutation_entries_json
                ORDER BY crop_id, mutation_entries_json
                """
            ).fetchall()
        return [
            {
                "crop_id": row["crop_id"],
                "mutation_entries": json.loads(row["mutation_entries_json"] or "[]"),
                "batch_count": int(row["batch_count"] or 0),
                "total_quantity": int(row["total_quantity"] or 0),
                "last_harvested_at": row["last_harvested_at"],
            }
            for row in rows
        ]

    # ---------------- 培育 ----------------

    def get_cultivation_rows(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT crop_id, points FROM cultivation_progress ORDER BY points DESC, crop_id"
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------------- 祝福 ----------------

    def add_blessing(self, direction, occurred_at, counterparty_name="", slot_id="", crop_id="", note="", per_crop_max=3):
        occur_dt = self._parse_iso(occurred_at) or datetime.now()
        occur_text = occur_dt.isoformat(timespec="minutes")
        slot_id = (slot_id or "").strip()
        crop_id = (crop_id or "").strip()

        with self._connect() as connection:
            if slot_id:
                row = connection.execute(
                    "SELECT blessing_count FROM slot_states WHERE slot_id = ?",
                    (slot_id,),
                ).fetchone()
                if row and int(row["blessing_count"] or 0) >= int(per_crop_max):
                    return {"ok": False, "message": f"该格子作物已达单株祝福上限 {per_crop_max} 次。"}
                if row:
                    connection.execute(
                        "UPDATE slot_states SET blessing_count = blessing_count + 1, updated_at = ? WHERE slot_id = ?",
                        (_now_iso(), slot_id),
                    )

            connection.execute(
                """
                INSERT INTO blessing_logs (direction, occurred_at, counterparty_name, slot_id, crop_id, note)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (direction, occur_text, counterparty_name, slot_id, crop_id, note),
            )
            related = counterparty_name or ("" if direction == "given" else "未知好友")
            connection.execute(
                """
                INSERT INTO activity_logs (event_type, occurred_at, slot_id, crop_id, related_name, amount, note)
                VALUES ('bless', ?, ?, ?, ?, 0, ?)
                """,
                (
                    occur_text,
                    slot_id,
                    crop_id,
                    related,
                    note or ("我祝福了别人" if direction == "given" else "别人祝福了我"),
                ),
            )
            connection.commit()
        return {"ok": True}

    def get_blessing_summary(self, reset_time="05:00"):
        boundary = daily_reset_boundary(reset_time=reset_time).isoformat(timespec="minutes")
        with self._connect() as connection:
            given = connection.execute(
                "SELECT COUNT(*) AS total FROM blessing_logs WHERE direction = 'given' AND occurred_at >= ?",
                (boundary,),
            ).fetchone()["total"]
            received = connection.execute(
                "SELECT COUNT(*) AS total FROM blessing_logs WHERE direction = 'received' AND occurred_at >= ?",
                (boundary,),
            ).fetchone()["total"]
            per_crop = connection.execute(
                """
                SELECT slot_id, COUNT(*) AS total
                FROM blessing_logs
                WHERE slot_id != '' AND occurred_at >= ?
                GROUP BY slot_id
                """,
                (boundary,),
            ).fetchall()
        return {
            "boundary": boundary,
            "given_today": int(given),
            "received_today": int(received),
            "per_crop": {row["slot_id"]: int(row["total"]) for row in per_crop},
        }

    def get_recent_blessings(self, limit=10):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, direction, occurred_at, counterparty_name, slot_id, crop_id, note
                FROM blessing_logs
                ORDER BY occurred_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------------- 偷菜配额 ----------------

    def get_theft_quota_today(self, reset_time="05:00"):
        boundary = daily_reset_boundary(reset_time=reset_time).isoformat(timespec="minutes")
        with self._connect() as connection:
            outbound = connection.execute(
                "SELECT COUNT(*) AS total FROM raid_logs WHERE direction = 'outbound' AND occurred_at >= ?",
                (boundary,),
            ).fetchone()["total"]
        return {"boundary": boundary, "outbound_today": int(outbound)}

    def record_raid(self, payload):
        direction = payload["direction"]
        occurred_at = payload.get("occurred_at") or _now_iso()
        counterparty_name = (payload.get("counterparty_name") or "").strip()
        slot_id = (payload.get("slot_id") or "").strip()
        crop_id = payload["crop_id"]
        quantity = int(payload["quantity"])
        unit_price_snapshot = float(payload["unit_price_snapshot"])
        amount = round(quantity * unit_price_snapshot, 2)
        note = (payload.get("note") or "").strip()

        ledger_type = "steal_income" if direction == "outbound" else "theft_loss"
        signed_amount = amount if direction == "outbound" else -amount
        related_name = counterparty_name or ("未记录受害者" if direction == "outbound" else "未知访客")
        event_type = "raid" if direction == "outbound" else "theft"

        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO raid_logs (
                    direction, occurred_at, counterparty_name, slot_id,
                    crop_id, quantity, unit_price_snapshot, amount, note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    direction,
                    occurred_at,
                    counterparty_name,
                    slot_id,
                    crop_id,
                    quantity,
                    unit_price_snapshot,
                    amount,
                    note,
                ),
            )
            raid_id = cursor.lastrowid
            self._insert_ledger(
                connection,
                ledger_type,
                signed_amount,
                occurred_at,
                note or (
                    f"偷了别人的 {crop_id} × {quantity}" if direction == "outbound"
                    else f"{related_name} 偷走了 {crop_id} × {quantity}"
                ),
                ref_type="raid_logs",
                ref_id=str(raid_id),
            )
            connection.execute(
                """
                INSERT INTO activity_logs (event_type, occurred_at, slot_id, crop_id, related_name, amount, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event_type, occurred_at, slot_id, crop_id, related_name, signed_amount, note),
            )
            connection.commit()

        return {
            "direction": direction,
            "occurred_at": occurred_at,
            "counterparty_name": related_name,
            "slot_id": slot_id,
            "crop_id": crop_id,
            "quantity": quantity,
            "unit_price_snapshot": unit_price_snapshot,
            "amount": amount,
            "note": note,
        }

    def get_event_points(self):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    occurred_at,
                    event_type,
                    slot_id,
                    crop_id,
                    related_name,
                    amount,
                    note
                FROM activity_logs

                UNION ALL

                SELECT
                    occurred_at,
                    'theft' AS event_type,
                    slot_id,
                    crop_id,
                    thief_name AS related_name,
                    -loss_amount AS amount,
                    note
                FROM theft_logs

                ORDER BY occurred_at ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _parse_iso(value):
        if not value:
            return None
        text = str(value).replace(" ", "T")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    @staticmethod
    def _format_countdown(delta, prefix="剩余"):
        total_minutes = int(delta.total_seconds() // 60)
        if total_minutes <= 0:
            return "已到时间"
        hours, minutes = divmod(total_minutes, 60)
        if hours:
            return f"{prefix} {hours}小时{minutes}分钟"
        return f"{prefix} {minutes}分钟"
