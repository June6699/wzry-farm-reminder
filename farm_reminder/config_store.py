import copy
import json
from datetime import datetime

from .paths import CONFIG_PATH


DEFAULT_CONFIG = {
    "player": {
        "nickname": "我的王者农场",
        "game_id": "",
        "level": 18,
        "avatar_path": "",
        "stall_bonus_pct": 20,
        "starting_balance": 0,
    },
    "farm": {
        "unlocked_slot_count": 12,
        "slots_per_field": 12,
        "total_field_count": 4,
    },
    "notifications": {
        "operation_buffer_min": 5,
        "plant_remind_ahead_min": 5,
        "water_remind_ahead_min": 10,
        "harvest_remind_ahead_min": 10,
        "channels": ["desktop", "sound"],
    },
    "planner": {
        "weekend_target_time": "18:05",
        "prefer_weekend_bonus": True,
        "prefer_anti_theft": True,
        "anti_theft_enabled": True,
        "anti_theft_safe_start": "00:00",
        "anti_theft_safe_end": "08:00",
        "auto_use_watering_strategy": True,
        "search_horizon_days": 14,
    },
    "meta": {
        "created_at": "",
        "updated_at": "",
    },
}


def _deep_merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        merged = {}
        for key in base.keys() | override.keys():
            if key in base and key in override:
                merged[key] = _deep_merge(base[key], override[key])
            elif key in override:
                merged[key] = copy.deepcopy(override[key])
            else:
                merged[key] = copy.deepcopy(base[key])
        return merged
    return copy.deepcopy(override)


def _is_valid_hhmm(value):
    try:
        hour_text, minute_text = str(value).split(":")
        hour = int(hour_text)
        minute = int(minute_text)
        return 0 <= hour <= 23 and 0 <= minute <= 59
    except (TypeError, ValueError):
        return False


def _clamp_int(value, minimum, maximum, fallback):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))


def _normalize_farm_config(farm):
    unlocked_slot_count = farm.get("unlocked_slot_count")
    if unlocked_slot_count is None and "unlocked_field_count" in farm:
        try:
            unlocked_slot_count = int(farm["unlocked_field_count"]) * 12
        except (TypeError, ValueError):
            unlocked_slot_count = DEFAULT_CONFIG["farm"]["unlocked_slot_count"]

    farm["slots_per_field"] = _clamp_int(
        farm.get("slots_per_field"),
        12,
        12,
        DEFAULT_CONFIG["farm"]["slots_per_field"],
    )
    farm["total_field_count"] = _clamp_int(
        farm.get("total_field_count"),
        4,
        4,
        DEFAULT_CONFIG["farm"]["total_field_count"],
    )
    max_slot_count = farm["slots_per_field"] * farm["total_field_count"]
    farm["unlocked_slot_count"] = _clamp_int(
        unlocked_slot_count,
        1,
        max_slot_count,
        DEFAULT_CONFIG["farm"]["unlocked_slot_count"],
    )
    return farm


def sanitize_config(config):
    merged = _deep_merge(DEFAULT_CONFIG, config or {})

    player = merged["player"]
    player["nickname"] = str(player.get("nickname", DEFAULT_CONFIG["player"]["nickname"])).strip() or DEFAULT_CONFIG["player"]["nickname"]
    player["game_id"] = str(player.get("game_id", "")).strip()
    player["level"] = _clamp_int(player.get("level"), 1, 100, DEFAULT_CONFIG["player"]["level"])
    player["stall_bonus_pct"] = _clamp_int(player.get("stall_bonus_pct"), 0, 200, DEFAULT_CONFIG["player"]["stall_bonus_pct"])
    player["starting_balance"] = _clamp_int(player.get("starting_balance"), -999999999, 999999999, DEFAULT_CONFIG["player"]["starting_balance"])
    player["avatar_path"] = str(player.get("avatar_path", "")).strip()

    merged["farm"] = _normalize_farm_config(merged["farm"])

    notifications = merged["notifications"]
    notifications["operation_buffer_min"] = _clamp_int(notifications.get("operation_buffer_min"), 0, 120, DEFAULT_CONFIG["notifications"]["operation_buffer_min"])
    notifications["plant_remind_ahead_min"] = _clamp_int(notifications.get("plant_remind_ahead_min"), 0, 120, DEFAULT_CONFIG["notifications"]["plant_remind_ahead_min"])
    notifications["water_remind_ahead_min"] = _clamp_int(notifications.get("water_remind_ahead_min"), 0, 180, DEFAULT_CONFIG["notifications"]["water_remind_ahead_min"])
    notifications["harvest_remind_ahead_min"] = _clamp_int(notifications.get("harvest_remind_ahead_min"), 0, 180, DEFAULT_CONFIG["notifications"]["harvest_remind_ahead_min"])
    channels = notifications.get("channels") or []
    if not isinstance(channels, list):
        channels = DEFAULT_CONFIG["notifications"]["channels"]
    notifications["channels"] = [str(channel) for channel in channels]

    planner = merged["planner"]
    planner["prefer_weekend_bonus"] = bool(planner.get("prefer_weekend_bonus", True))
    planner["prefer_anti_theft"] = bool(planner.get("prefer_anti_theft", True))
    planner["anti_theft_enabled"] = bool(planner.get("anti_theft_enabled", True))
    planner["auto_use_watering_strategy"] = bool(planner.get("auto_use_watering_strategy", True))
    planner["search_horizon_days"] = _clamp_int(planner.get("search_horizon_days"), 3, 30, DEFAULT_CONFIG["planner"]["search_horizon_days"])
    if not _is_valid_hhmm(planner.get("weekend_target_time")):
        planner["weekend_target_time"] = DEFAULT_CONFIG["planner"]["weekend_target_time"]
    if not _is_valid_hhmm(planner.get("anti_theft_safe_start")):
        planner["anti_theft_safe_start"] = DEFAULT_CONFIG["planner"]["anti_theft_safe_start"]
    if not _is_valid_hhmm(planner.get("anti_theft_safe_end")):
        planner["anti_theft_safe_end"] = DEFAULT_CONFIG["planner"]["anti_theft_safe_end"]

    now_text = datetime.now().isoformat(timespec="seconds")
    meta = merged["meta"]
    meta["created_at"] = meta.get("created_at") or now_text
    meta["updated_at"] = now_text
    return merged


class ConfigStore:
    def __init__(self, path=CONFIG_PATH):
        self.path = path

    def load(self):
        if not self.path.exists():
            config = sanitize_config(DEFAULT_CONFIG)
            self.save(config)
            return config

        with self.path.open("r", encoding="utf-8") as file_handle:
            raw = json.load(file_handle)
        config = sanitize_config(raw)
        if config != raw:
            self.save(config)
        return config

    def save(self, config):
        sanitized = sanitize_config(config)
        with self.path.open("w", encoding="utf-8") as file_handle:
            json.dump(sanitized, file_handle, ensure_ascii=False, indent=2)
        return sanitized
