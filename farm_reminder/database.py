import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

from .paths import DB_PATH


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
"""


def _now_iso():
    return datetime.now().isoformat(timespec="minutes")


def _row_to_dict(row):
    return dict(row) if row is not None else None


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
            self._seed_field_slots(connection)
            self._recalculate_wallet_balances(connection)
            connection.commit()

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
                    s.expected_net_income, s.note, s.updated_at
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
                       note, updated_at
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
                       expected_income, expected_net_income, note
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
                }
                connection.execute(
                    """
                    INSERT INTO slot_states (
                        slot_id, phase, crop_id, strategy_id, strategy_name, planned_start_at,
                        planted_at, harvest_at, watering_times_json, expected_cost,
                        expected_income, expected_net_income, note, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        _now_iso(),
                    ),
                )
            connection.commit()
        return len(slot_ids)

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

    def confirm_planted(self, slot_ids, started_at):
        if not slot_ids:
            return {"processed_count": 0}
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
                return {"processed_count": 0}

            grouped_cost = defaultdict(lambda: {"count": 0, "cost": 0.0})
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
                grouped_cost[row["crop_id"]]["count"] += 1
                grouped_cost[row["crop_id"]]["cost"] += float(row["expected_cost"] or 0)

            for crop_id, item in grouped_cost.items():
                self._insert_ledger(
                    connection,
                    "seed_purchase",
                    -item["cost"],
                    start_text,
                    f"种植 {crop_id} × {item['count']}",
                    ref_type="slot_states",
                )
            connection.commit()
        return {"processed_count": len(process_rows)}

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

    def harvest_slots(self, slot_ids, occurred_at):
        if not slot_ids:
            return {"processed_count": 0}
        occur_dt = self._parse_iso(occurred_at) or datetime.now()
        occur_text = occur_dt.isoformat(timespec="minutes")

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT slot_id, crop_id, expected_income
                FROM slot_states
                WHERE slot_id IN ({','.join('?' for _ in slot_ids)})
                  AND crop_id IS NOT NULL
                """,
                tuple(slot_ids),
            ).fetchall()
            process_rows = [dict(row) for row in rows]
            if not process_rows:
                return {"processed_count": 0}

            grouped_income = defaultdict(lambda: {"count": 0, "income": 0.0})
            for row in process_rows:
                connection.execute(
                    """
                    INSERT INTO activity_logs (event_type, occurred_at, slot_id, crop_id, related_name, amount, note)
                    VALUES ('harvest', ?, ?, ?, '', ?, '登记收获')
                    """,
                    (occur_text, row["slot_id"], row["crop_id"], float(row["expected_income"] or 0)),
                )
                grouped_income[row["crop_id"]]["count"] += 1
                grouped_income[row["crop_id"]]["income"] += float(row["expected_income"] or 0)

            for crop_id, item in grouped_income.items():
                self._insert_ledger(
                    connection,
                    "harvest_income",
                    item["income"],
                    occur_text,
                    f"收获 {crop_id} × {item['count']}",
                    ref_type="slot_states",
                )

            connection.execute(
                f"DELETE FROM slot_states WHERE slot_id IN ({','.join('?' for _ in slot_ids)})",
                tuple(slot_ids),
            )
            connection.commit()
        return {"processed_count": len(process_rows)}

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
