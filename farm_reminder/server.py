import json
import mimetypes
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from .planner import build_planner_payload
from .paths import WEB_DIR


def _json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _parse_iso(value):
    if not value:
        return None
    text = str(value).replace(" ", "T")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _format_money(value):
    return round(float(value or 0), 2)


def _parse_hhmm(value, fallback):
    try:
        hour_text, minute_text = str(value).split(":")
        return int(hour_text), int(minute_text)
    except (TypeError, ValueError):
        hour_text, minute_text = str(fallback).split(":")
        return int(hour_text), int(minute_text)


def build_clock_events(mechanics, now=None):
    """生成未来三天内的关键节点：每日重置 / 昼夜 / 偷菜窗口 / 周末双倍。"""
    now = now or datetime.now()
    day_night = mechanics.get("day_night", {})
    steal = mechanics.get("steal_rules", {})
    reset_time = mechanics.get("daily_reset_time", "05:00")
    day_start = day_night.get("day_start", "06:00")
    night_start = day_night.get("night_start", "18:00")
    steal_start = steal.get("window_start", "08:00")
    weekend = mechanics.get("weekend_bonus_start", {})
    weekend_weekday = int(weekend.get("weekday", 4))
    weekend_time = weekend.get("time", "18:00")

    raw_events = []
    for day_offset in range(0, 4):
        base = (now + timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)

        def add(time_text, label, kind):
            hour, minute = _parse_hhmm(time_text, "00:00")
            at = base + timedelta(days=1) if hour >= 24 else base.replace(hour=hour, minute=minute)
            raw_events.append({"at": at, "label": label, "kind": kind})

        add(reset_time, "每日重置（祝福 / 偷菜计数 / 培育次数）", "reset")
        add(day_start, "进入白天", "day-night")
        add(steal_start, "偷菜窗口开启", "steal")
        add(night_start, "进入夜晚", "day-night")
        add("24:00", "偷菜窗口关闭", "steal")
        if base.weekday() == weekend_weekday:
            add(weekend_time, "周末双倍开启", "weekend")
        if base.weekday() == 6:
            add("24:00", "周末双倍结束", "weekend")

    raw_events.sort(key=lambda item: item["at"])
    merged = []
    for event in raw_events:
        if merged and merged[-1]["at"] == event["at"]:
            merged[-1]["label"] += " · " + event["label"]
            merged[-1]["kind"] = event["kind"] if merged[-1]["kind"] == event["kind"] else "mixed"
            continue
        merged.append(event)

    upcoming = [event for event in merged if event["at"] > now][:14]
    for event in upcoming:
        event["at"] = event["at"].isoformat(timespec="minutes")
    return upcoming


def build_handler(services):
    def _current_config():
        return services["config"].load()

    def _current_rules():
        services["rules"].reload()
        return services["rules"]

    def _enrich_fields(fields, rules):
        for field in fields:
            for slot in field["slots"]:
                crop = rules.get_crop(slot.get("crop_id")) if slot.get("crop_id") else None
                slot["crop_name"] = crop["name"] if crop else ""
                slot["crop_growth_label"] = crop["growth_label"] if crop else ""
        return fields

    def _cultivation_map(rules):
        return {
            row["crop_id"]: rules.get_cultivation_level(row["points"])
            for row in services["database"].get_cultivation_rows()
        }

    def _fruit_unit_price(crop, config, cultivation_level):
        multiplier = float(cultivation_level.get("multiplier", 1.0))
        return crop["base_sell_price"] * multiplier * (1 + config["player"]["stall_bonus_pct"] / 100)

    def _enrich_bag_payload(rules, config):
        database = services["database"]
        cultivation_map = _cultivation_map(rules)

        seed_inventory = []
        for row in database.get_seed_inventory():
            crop = rules.get_crop(row["crop_id"])
            seed_inventory.append(
                {
                    **row,
                    "crop_name": crop["name"] if crop else row["crop_id"],
                    "seed_cost": crop["seed_cost"] if crop else 0,
                }
            )

        fruit_unit_prices = {}
        fruits_in_stock = []
        fruits_sold = []
        for row in database.get_fruit_inventory():
            crop = rules.get_crop(row["crop_id"])
            level_info = cultivation_map.get(row["crop_id"], {"multiplier": 1.0, "level": 1})
            unit_price = _fruit_unit_price(crop, config, level_info) if crop else 0
            entry = {
                **row,
                "crop_name": crop["name"] if crop else row["crop_id"],
                "unit_price": _format_money(unit_price),
                "estimated_total": _format_money(unit_price * int(row["quantity"]) * float(row["mutation_multiplier"] or 1)),
            }
            if row["crop_id"] not in fruit_unit_prices:
                fruit_unit_prices[row["crop_id"]] = _format_money(unit_price)
            if row["status"] == "in_stock":
                fruits_in_stock.append(entry)
            else:
                fruits_sold.append(entry)

        cultivation_rows = []
        for row in database.get_cultivation_rows():
            crop = rules.get_crop(row["crop_id"])
            level_info = cultivation_map.get(row["crop_id"], {"multiplier": 1.0, "level": 1, "required_points": 0})
            levels = rules.mechanics.get("cultivation_levels", [])
            current_level = int(level_info.get("level", 1))
            next_level = next(
                (item for item in levels if int(item["level"]) == current_level + 1),
                None,
            )
            cultivation_rows.append(
                {
                    "crop_id": row["crop_id"],
                    "crop_name": crop["name"] if crop else row["crop_id"],
                    "points": int(row["points"]),
                    "level": current_level,
                    "multiplier": level_info.get("multiplier", 1.0),
                    "next_level_points": next_level["required_points"] if next_level else None,
                    "is_max": next_level is None,
                }
            )

        collection = []
        for row in database.get_collection():
            crop = rules.get_crop(row["crop_id"])
            collection.append(
                {
                    **row,
                    "crop_name": crop["name"] if crop else row["crop_id"],
                    "crop_unlock_level": crop["unlock_level"] if crop else 0,
                }
            )

        return {
            "seed_inventory": seed_inventory,
            "fruit_unit_prices": fruit_unit_prices,
            "fruits_in_stock": fruits_in_stock,
            "fruits_sold": fruits_sold[:40],
            "cultivation": cultivation_rows,
            "collection": collection,
        }

    def _dashboard_payload():
        config = _current_config()
        rules = _current_rules()
        database = services["database"]
        fields = _enrich_fields(
            database.get_fields(config["farm"]["unlocked_slot_count"]),
            rules,
        )
        blessing_rules = rules.mechanics.get("blessing_rules", {})
        steal_rules = rules.mechanics.get("steal_rules", {})
        payload = {
            "config": config,
            "crops": rules.crop_options,
            "mechanics": rules.mechanics,
            "watering_rules": rules.watering_rules,
            "mutations": rules.mutations,
            "hero_crops": rules.get_hero_crops(),
            "fields": fields,
            "farm_summary": database.get_farm_summary(),
            "wallet": database.get_wallet_summary(),
            "ledger": database.get_wallet_ledger(),
            "raids": database.get_recent_raids(),
            "events": database.get_event_points(),
            "blessing": {
                **database.get_blessing_summary(reset_time=blessing_rules.get("reset_time", "05:00")),
                "rules": blessing_rules,
                "recent": database.get_recent_blessings(),
            },
            "steal_quota": {
                **database.get_theft_quota_today(reset_time=steal_rules.get("reset_time", "05:00")),
                "rules": steal_rules,
            },
            "clock_events": build_clock_events(rules.mechanics),
            "experiences": rules.get_experiences(),
        }
        payload.update(_enrich_bag_payload(rules, config))
        return payload

    def _crop_unit_values(crop, config, harvest_at_text, mutation_multiplier=1):
        unit_price = crop["base_sell_price"] * (1 + config["player"]["stall_bonus_pct"] / 100)
        harvest_dt = _parse_iso(harvest_at_text)
        weekend_multiplier = 2 if harvest_dt and _is_weekend_bonus(harvest_dt) else 1
        income = unit_price * weekend_multiplier * float(mutation_multiplier or 1)
        cost = crop["seed_cost"]
        return {
            "expected_cost": _format_money(cost),
            "expected_income": _format_money(income),
            "expected_net_income": _format_money(income - cost),
        }

    def _is_weekend_bonus(dt_value):
        weekday = dt_value.weekday()
        minute_of_day = dt_value.hour * 60 + dt_value.minute
        if weekday == 4:
            return minute_of_day >= 18 * 60
        return weekday in (5, 6)

    def _resolve_mutation_patch(rules, payload, crop):
        """把请求里的 mutation_entries 解析成可入库的字段；出错时返回 message。"""
        entries = payload.get("mutation_entries")
        if entries is None:
            return {}
        if not isinstance(entries, list):
            return {"error": "mutation_entries 需要是数组。"}
        entries = [str(name).strip() for name in entries if str(name).strip()]

        if not entries:
            return {
                "mutation_entries": [],
                "mutation_multiplier": 1,
                "hero_flag": 0,
            }

        if crop and not crop.get("can_mutate"):
            return {"error": f"{crop['name']} 是新手作物（8 级以下解锁），无法变异。"}

        resolved = rules.resolve_mutation_entries(entries)
        if resolved["unknown"]:
            return {"error": f"未知的变异词条：{ '、'.join(resolved['unknown']) }。"}
        if resolved["conflicts"]:
            return {"error": f"互斥词条不能同时存在：{ '、'.join(resolved['conflicts']) }。"}
        if len(resolved["names"]) > resolved["max_entries"]:
            return {"error": f"词条数量超上限：当前作物最多 {resolved['max_entries']} 条。"}

        return {
            "mutation_entries": resolved["names"],
            "mutation_multiplier": resolved["multiplier"],
            "hero_flag": 1 if resolved["has_hero"] else 0,
        }

    def _resolve_apply_slot_ids(slot_count, config):
        all_unlocked = services["database"].resolve_slot_ids(
            config["farm"]["unlocked_slot_count"],
            {"mode": "all"},
        )
        clamped_count = max(0, min(int(slot_count), len(all_unlocked)))
        return all_unlocked[:clamped_count]

    def _get_state_map():
        return {row["slot_id"]: row for row in services["database"].get_slot_state_rows()}

    def _build_slot_patch(scope, payload, config):
        rules = _current_rules()
        selected_slot_ids = services["database"].resolve_slot_ids(
            config["farm"]["unlocked_slot_count"],
            scope,
        )
        state_map = _get_state_map()
        assignments = []

        for slot_id in selected_slot_ids:
            current_state = state_map.get(slot_id, {})
            crop_id = payload.get("crop_id") or current_state.get("crop_id")
            if not crop_id:
                continue
            crop = rules.get_crop(crop_id)
            if not crop:
                continue

            phase = payload.get("phase") or current_state.get("phase") or "planned"
            explicit_start = payload.get("start_at")
            explicit_harvest = payload.get("harvest_at")

            existing_base = _parse_iso(current_state.get("planted_at") or current_state.get("planned_start_at"))
            existing_harvest = _parse_iso(current_state.get("harvest_at"))
            explicit_start_dt = _parse_iso(explicit_start) if explicit_start else existing_base or datetime.now()

            if explicit_harvest:
                harvest_dt = _parse_iso(explicit_harvest) or (explicit_start_dt + timedelta(minutes=crop["growth_minutes"]))
            elif explicit_start:
                if existing_base and existing_harvest and not payload.get("crop_id"):
                    duration = existing_harvest - existing_base
                    if duration.total_seconds() <= 0:
                        duration = timedelta(minutes=crop["growth_minutes"])
                else:
                    duration = timedelta(minutes=crop["growth_minutes"])
                harvest_dt = explicit_start_dt + duration
            elif existing_harvest:
                harvest_dt = existing_harvest
            else:
                harvest_dt = explicit_start_dt + timedelta(minutes=crop["growth_minutes"])

            mutation_patch = _resolve_mutation_patch(rules, payload, crop)
            if "error" in mutation_patch:
                return None, mutation_patch["error"], slot_id, []

            mutation_entries = mutation_patch.get(
                "mutation_entries",
                json.loads(current_state.get("mutation_entries_json") or "[]"),
            )
            mutation_multiplier = mutation_patch.get(
                "mutation_multiplier",
                float(current_state.get("mutation_multiplier") or 1),
            )
            hero_flag = mutation_patch.get(
                "hero_flag",
                int(bool(current_state.get("hero_flag"))),
            )

            finance = _crop_unit_values(
                crop,
                config,
                harvest_dt.isoformat(timespec="minutes"),
                mutation_multiplier=mutation_multiplier,
            )
            assignments.append(
                {
                    "slot_id": slot_id,
                    "phase": phase,
                    "crop_id": crop_id,
                    "strategy_id": "manual",
                    "strategy_name": "手动编辑",
                    "planned_start_at": explicit_start_dt.isoformat(timespec="minutes"),
                    "planted_at": explicit_start_dt.isoformat(timespec="minutes") if phase == "planted" else None,
                    "harvest_at": harvest_dt.isoformat(timespec="minutes"),
                    "watering_times": current_state.get("watering_times_json") or [],
                    "note": payload.get("note", ""),
                    "mutation_entries": mutation_entries,
                    "mutation_multiplier": mutation_multiplier,
                    "hero_flag": hero_flag,
                    **finance,
                }
            )
        return selected_slot_ids, None, None, assignments

    class FarmRequestHandler(BaseHTTPRequestHandler):
        server_version = "FarmReminder/0.3"

        def _send_json(self, payload, status=HTTPStatus.OK):
            body = _json_bytes(payload)
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, file_path):
            if not file_path.exists():
                self.send_error(HTTPStatus.NOT_FOUND.value)
                return

            body = file_path.read_bytes()
            content_type, _ = mimetypes.guess_type(file_path.name)
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", (content_type or "text/plain") + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b"{}"
            return json.loads(body.decode("utf-8"))

        def do_GET(self):
            path = urlparse(self.path).path

            if path == "/api/bootstrap":
                self._send_json(_dashboard_payload())
                return

            if path == "/api/stats":
                payload = _dashboard_payload()
                self._send_json(
                    {
                        "wallet": payload["wallet"],
                        "ledger": payload["ledger"],
                        "events": payload["events"],
                        "raids": payload["raids"],
                        "farm_summary": payload["farm_summary"],
                    }
                )
                return

            if path == "/api/experiences":
                self._send_json(services["rules"].get_experiences())
                return

            if path in ("/", "/index.html"):
                self._send_file(WEB_DIR / "index.html")
                return

            static_file = WEB_DIR / path.lstrip("/")
            if static_file.exists() and static_file.is_file():
                self._send_file(static_file)
                return

            self.send_error(HTTPStatus.NOT_FOUND.value)

        def do_POST(self):
            path = urlparse(self.path).path
            payload = self._read_json()

            if path == "/api/settings":
                saved = services["config"].save(payload)
                self._send_json({"ok": True, "config": saved, "dashboard": _dashboard_payload()})
                return

            if path == "/api/planner":
                config = _current_config()
                rules = _current_rules()
                crop_id = payload.get("crop_id")
                crop = rules.get_crop(crop_id)
                if not crop:
                    self._send_json({"ok": False, "message": "找不到对应作物。"}, status=HTTPStatus.BAD_REQUEST)
                    return
                plot_count = int(payload.get("plot_count") or config["farm"]["unlocked_slot_count"])
                watering_rule = rules.get_watering_rule(crop["growth_minutes"])
                planner_payload = build_planner_payload(crop, watering_rule, config, plot_count)
                self._send_json({"ok": True, "planner": planner_payload})
                return

            if path == "/api/plans/apply":
                config = _current_config()
                rules = _current_rules()
                crop = rules.get_crop(payload.get("crop_id"))
                if not crop:
                    self._send_json({"ok": False, "message": "找不到对应作物。"}, status=HTTPStatus.BAD_REQUEST)
                    return

                slot_ids = _resolve_apply_slot_ids(
                    payload.get("slot_count") or config["farm"]["unlocked_slot_count"],
                    config,
                )
                if not slot_ids:
                    self._send_json({"ok": False, "message": "没有可应用的已开格子。"}, status=HTTPStatus.BAD_REQUEST)
                    return

                assignments = []
                for slot_id in slot_ids:
                    finance = _crop_unit_values(crop, config, payload["harvest_at"])
                    assignments.append(
                        {
                            "slot_id": slot_id,
                            "crop_id": crop["crop_id"],
                            "strategy_id": payload.get("strategy_id", "natural"),
                            "strategy_name": payload.get("strategy_name", "自然成熟"),
                            "planned_start_at": payload["plant_at"],
                            "harvest_at": payload["harvest_at"],
                            "watering_times": payload.get("watering_times", []),
                            **finance,
                        }
                    )
                services["database"].apply_plan(assignments)
                self._send_json({"ok": True, "dashboard": _dashboard_payload()})
                return

            if path == "/api/slots/update":
                config = _current_config()
                scope = payload.get("scope") or {}
                _, error, error_slot, assignments = _build_slot_patch(scope, payload, config)
                if error:
                    self._send_json(
                        {"ok": False, "message": f"{error}（格子 {error_slot or '?'}）"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                for assignment in assignments:
                    services["database"].update_slot_states([assignment["slot_id"]], assignment)
                self._send_json({"ok": True, "dashboard": _dashboard_payload()})
                return

            if path == "/api/slots/start":
                config = _current_config()
                rules = _current_rules()
                scope = payload.get("scope") or {}
                slot_ids = services["database"].resolve_slot_ids(config["farm"]["unlocked_slot_count"], scope)
                crop_map = {
                    crop["crop_id"]: {"name": crop["name"], "seed_cost": crop["seed_cost"]}
                    for crop in rules.crop_options
                }
                reset_time = rules.mechanics.get("daily_reset_time", "05:00")
                result = services["database"].confirm_planted(
                    slot_ids,
                    payload.get("started_at"),
                    crop_map=crop_map,
                    reset_time=reset_time,
                )
                self._send_json({"ok": True, "result": result, "dashboard": _dashboard_payload()})
                return

            if path == "/api/slots/water":
                config = _current_config()
                scope = payload.get("scope") or {}
                slot_ids = services["database"].resolve_slot_ids(config["farm"]["unlocked_slot_count"], scope)
                result = services["database"].water_slots(
                    slot_ids,
                    payload.get("occurred_at"),
                    payload.get("reduce_minutes"),
                )
                self._send_json({"ok": True, "result": result, "dashboard": _dashboard_payload()})
                return

            if path == "/api/slots/harvest":
                config = _current_config()
                rules = _current_rules()
                scope = payload.get("scope") or {}
                slot_ids = services["database"].resolve_slot_ids(config["farm"]["unlocked_slot_count"], scope)
                result = services["database"].harvest_slots(
                    slot_ids,
                    payload.get("occurred_at"),
                    cultivation_points=rules.mechanics.get("cultivation_points_per_harvest", 10),
                )
                self._send_json({"ok": True, "result": result, "dashboard": _dashboard_payload()})
                return

            if path == "/api/slots/clear":
                config = _current_config()
                scope = payload.get("scope") or {}
                slot_ids = services["database"].resolve_slot_ids(config["farm"]["unlocked_slot_count"], scope)
                result_count = services["database"].clear_slot_states(slot_ids)
                self._send_json({"ok": True, "cleared": result_count, "dashboard": _dashboard_payload()})
                return

            if path == "/api/seeds":
                config = _current_config()
                rules = _current_rules()
                crop = rules.get_crop(payload.get("crop_id"))
                if not crop:
                    self._send_json({"ok": False, "message": "找不到对应作物。"}, status=HTTPStatus.BAD_REQUEST)
                    return
                try:
                    delta = int(payload.get("delta"))
                except (TypeError, ValueError):
                    self._send_json({"ok": False, "message": "变动数量必须是整数。"}, status=HTTPStatus.BAD_REQUEST)
                    return
                if delta == 0:
                    self._send_json({"ok": False, "message": "变动数量不能为 0。"}, status=HTTPStatus.BAD_REQUEST)
                    return
                result = services["database"].adjust_seed_inventory(
                    crop["crop_id"],
                    delta,
                    source=str(payload.get("source") or ""),
                    note=str(payload.get("note") or ""),
                )
                self._send_json({"ok": True, "result": result, "dashboard": _dashboard_payload()})
                return

            if path == "/api/fruits/sell":
                config = _current_config()
                rules = _current_rules()
                fruit_ids = payload.get("fruit_ids") or []
                if not isinstance(fruit_ids, list) or not fruit_ids:
                    self._send_json({"ok": False, "message": "请先勾选要卖出的果实批次。"}, status=HTTPStatus.BAD_REQUEST)
                    return

                fruits = services["database"].get_fruit_inventory(status="in_stock")
                selected_map = {int(row["id"]): row for row in fruits if int(row["id"]) in set(int(x) for x in fruit_ids)}
                if not selected_map:
                    self._send_json({"ok": False, "message": "选中的批次已经不在库。"}, status=HTTPStatus.BAD_REQUEST)
                    return

                cultivation_map = _cultivation_map(rules)
                unit_price_map = {}
                for row in selected_map.values():
                    crop = rules.get_crop(row["crop_id"])
                    if crop and row["crop_id"] not in unit_price_map:
                        level_info = cultivation_map.get(row["crop_id"], {"multiplier": 1.0})
                        unit_price_map[row["crop_id"]] = _format_money(
                            _fruit_unit_price(crop, config, level_info)
                        )

                result = services["database"].sell_fruits(
                    list(selected_map.keys()),
                    unit_price_map,
                    occurred_at=payload.get("occurred_at"),
                )
                self._send_json({"ok": True, "result": result, "dashboard": _dashboard_payload()})
                return

            if path == "/api/blessings":
                config = _current_config()
                rules = _current_rules()
                blessing_rules = rules.mechanics.get("blessing_rules", {})
                direction = payload.get("direction")
                if direction not in ("given", "received"):
                    self._send_json({"ok": False, "message": "方向必须是 given 或 received。"}, status=HTTPStatus.BAD_REQUEST)
                    return

                summary = services["database"].get_blessing_summary(
                    reset_time=blessing_rules.get("reset_time", "05:00")
                )
                if direction == "given" and summary["given_today"] >= int(blessing_rules.get("daily_give_limit", 10)):
                    self._send_json(
                        {"ok": False, "message": f"今天发出的祝福已达上限 {blessing_rules.get('daily_give_limit', 10)} 次（05:00 重置）。"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                if direction == "received" and summary["received_today"] >= int(blessing_rules.get("daily_receive_limit", 30)):
                    self._send_json(
                        {"ok": False, "message": f"今天被祝福已达上限 {blessing_rules.get('daily_receive_limit', 30)} 次。"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return

                rules_result = services["database"].add_blessing(
                    direction,
                    payload.get("occurred_at") or datetime.now().isoformat(timespec="minutes"),
                    counterparty_name=str(payload.get("counterparty_name") or ""),
                    slot_id=str(payload.get("slot_id") or ""),
                    crop_id=str(payload.get("crop_id") or ""),
                    note=str(payload.get("note") or ""),
                    per_crop_max=int(blessing_rules.get("per_crop_max", 3)),
                )
                if not rules_result.get("ok"):
                    self._send_json(rules_result, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({"ok": True, "dashboard": _dashboard_payload()})
                return

            if path == "/api/raids":
                config = _current_config()
                rules = _current_rules()
                crop = rules.get_crop(payload.get("crop_id"))
                if not crop:
                    self._send_json({"ok": False, "message": "找不到对应作物。"}, status=HTTPStatus.BAD_REQUEST)
                    return

                direction = payload.get("direction")
                if direction not in ("inbound", "outbound"):
                    self._send_json({"ok": False, "message": "方向参数不正确。"}, status=HTTPStatus.BAD_REQUEST)
                    return
                if direction == "inbound" and not str(payload.get("counterparty_name") or "").strip():
                    self._send_json({"ok": False, "message": "被偷菜时必须填写偷菜人。"}, status=HTTPStatus.BAD_REQUEST)
                    return

                unit_price = crop["base_sell_price"] * (1 + config["player"]["stall_bonus_pct"] / 100)
                if payload.get("is_weekend_bonus_time"):
                    unit_price *= rules.mechanics.get("weekend_bonus_multiplier", 2)
                payload["unit_price_snapshot"] = _format_money(unit_price)
                record = services["database"].record_raid(payload)
                self._send_json({"ok": True, "raid": record, "dashboard": _dashboard_payload()})
                return

            self.send_error(HTTPStatus.NOT_FOUND.value)

        def log_message(self, format_string, *args):
            return

    return FarmRequestHandler
