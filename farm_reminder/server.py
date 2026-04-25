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

    def _dashboard_payload():
        config = _current_config()
        rules = _current_rules()
        fields = _enrich_fields(
            services["database"].get_fields(config["farm"]["unlocked_slot_count"]),
            rules,
        )
        return {
            "config": config,
            "crops": rules.crop_options,
            "mechanics": rules.mechanics,
            "watering_rules": rules.watering_rules,
            "fields": fields,
            "farm_summary": services["database"].get_farm_summary(),
            "wallet": services["database"].get_wallet_summary(),
            "ledger": services["database"].get_wallet_ledger(),
            "raids": services["database"].get_recent_raids(),
            "events": services["database"].get_event_points(),
        }

    def _crop_unit_values(crop, config, harvest_at_text):
        unit_price = crop["base_sell_price"] * (1 + config["player"]["stall_bonus_pct"] / 100)
        harvest_dt = _parse_iso(harvest_at_text)
        weekend_multiplier = 2 if harvest_dt and _is_weekend_bonus(harvest_dt) else 1
        income = unit_price * weekend_multiplier
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

            finance = _crop_unit_values(crop, config, harvest_dt.isoformat(timespec="minutes"))
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
                    **finance,
                }
            )
        return selected_slot_ids, assignments

    class FarmRequestHandler(BaseHTTPRequestHandler):
        server_version = "FarmReminder/0.2"

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
                _, assignments = _build_slot_patch(scope, payload, config)
                for assignment in assignments:
                    services["database"].update_slot_states([assignment["slot_id"]], assignment)
                self._send_json({"ok": True, "dashboard": _dashboard_payload()})
                return

            if path == "/api/slots/start":
                config = _current_config()
                scope = payload.get("scope") or {}
                slot_ids = services["database"].resolve_slot_ids(config["farm"]["unlocked_slot_count"], scope)
                result = services["database"].confirm_planted(slot_ids, payload.get("started_at"))
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
                scope = payload.get("scope") or {}
                slot_ids = services["database"].resolve_slot_ids(config["farm"]["unlocked_slot_count"], scope)
                result = services["database"].harvest_slots(slot_ids, payload.get("occurred_at"))
                self._send_json({"ok": True, "result": result, "dashboard": _dashboard_payload()})
                return

            if path == "/api/slots/clear":
                config = _current_config()
                scope = payload.get("scope") or {}
                slot_ids = services["database"].resolve_slot_ids(config["farm"]["unlocked_slot_count"], scope)
                result_count = services["database"].clear_slot_states(slot_ids)
                self._send_json({"ok": True, "cleared": result_count, "dashboard": _dashboard_payload()})
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
