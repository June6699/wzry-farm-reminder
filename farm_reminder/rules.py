import copy
import json
import re
from functools import lru_cache

from .paths import RULES_DIR, SOURCE_MARKDOWN_PATH, ensure_directories


CROPS_JSON_PATH = RULES_DIR / "crops.json"
WATERING_JSON_PATH = RULES_DIR / "watering_rules.json"
MECHANICS_JSON_PATH = RULES_DIR / "game_mechanics.json"
MUTATIONS_JSON_PATH = RULES_DIR / "mutations.json"
EXPERIENCES_JSON_PATH = RULES_DIR / "experiences.json"


DEFAULT_MECHANICS = {
    "weekend_bonus_enabled": True,
    "weekend_bonus_start": {
        "weekday": 4,
        "time": "18:00",
    },
    "weekend_bonus_end": {
        "weekday": 6,
        "time": "24:00",
    },
    "weekend_bonus_multiplier": 2,
    "stall_bonus_step_pct": 10,
    "stall_bonus_max_pct": 50,
    "default_slot_count_per_field": 12,
    "supported_field_count_options": [2, 3, 4],
    "anti_theft_hint": {
        "enabled": True,
        "safe_window_start": "00:00",
        "safe_window_end": "08:00",
        "source": "community_configurable",
    },
    "cultivation_levels": [
        {"level": 1, "multiplier": 1.0, "required_points": 0},
        {"level": 2, "multiplier": 1.1, "required_points": 100},
        {"level": 3, "multiplier": 1.2, "required_points": 300},
        {"level": 4, "multiplier": 1.3, "required_points": 600},
        {"level": 5, "multiplier": 1.4, "required_points": 1000},
        {"level": 6, "multiplier": 1.5, "required_points": 1500},
        {"level": 7, "multiplier": 1.6, "required_points": 2100},
        {"level": 8, "multiplier": 1.7, "required_points": 2800},
        {"level": 9, "multiplier": 1.8, "required_points": 3600},
        {"level": 10, "multiplier": 2.0, "required_points": 4500},
    ],
    "cultivation_points_per_harvest": 10,
    "blessing_rules": {
        "daily_give_limit": 10,
        "per_crop_max": 3,
        "daily_receive_limit": 30,
        "reset_time": "05:00",
    },
    "steal_rules": {
        "unlock_farm_level": 4,
        "window_start": "08:00",
        "window_end": "24:00",
        "per_plant_max_takes": 4,
        "per_plant_cap_ratio": 0.4,
        "daily_quota": 100,
        "hero_crop_immune": True,
        "reset_time": "05:00",
    },
    "day_night": {
        "day_start": "06:00",
        "night_start": "18:00",
    },
    "daily_reset_time": "05:00",
    "tier2_field": {
        "unlock_farm_level": 44,
        "yield_bonus_ratio": 0.5,
    },
    "level_stall_strategy": {
        "hero_tail_digits": [1, 6],
        "economy_tail_digits": [5, 0],
        "collab_tail_digits": [4, 9],
    },
}


DEFAULT_MUTATIONS = {
    "mutation_types": [
        {"name": "蓝色词条", "rarity": "常见", "multiplier": 1.5, "anti_steal": False, "badge": "blue", "note": "颜色系变异"},
        {"name": "紫色词条", "rarity": "常见", "multiplier": 2.5, "anti_steal": False, "badge": "purple", "note": "高级颜色系"},
        {"name": "材质词条", "rarity": "中等", "multiplier": 4.0, "anti_steal": False, "badge": "teal", "note": "钻石/金属/冰冻等元素效果"},
        {"name": "巨大化", "rarity": "稀有", "multiplier": 8.0, "anti_steal": False, "badge": "giant", "note": "体型变大，与超巨化互斥"},
        {"name": "超巨化", "rarity": "稀有", "multiplier": 10.0, "anti_steal": False, "badge": "giant", "note": "培育台专属，与巨大化互斥"},
        {"name": "英雄变异", "rarity": "极稀有", "multiplier": 28.0, "anti_steal": True, "badge": "hero", "note": "英雄主题外观，不可被偷"},
    ],
    "hero_crops": [],
    "stack_rules": {
        "base_mutate_farm_level": 8,
        "normal_max_entries": 3,
        "hero_extra_entry_farm_level": 60,
        "hero_max_entries": 4,
        "mutually_exclusive": [["巨大化", "超巨化"]],
    },
    "trigger_rules": {
        "base_chance": 0.2,
        "blessing_is_best": True,
        "steal_can_trigger": True,
        "manual_water_bonus_pct": 15,
        "last_water_high_frequency_window": True,
    },
}


def parse_cn_duration_to_minutes(value):
    text = str(value).strip()
    if not text:
        return 0

    total_minutes = 0.0
    for match in re.findall(r"(\d+)小时", text):
        total_minutes += int(match) * 60
    for match in re.findall(r"(\d+)分钟", text):
        total_minutes += int(match)
    if "分钟" not in text:
        for match in re.findall(r"(\d+)分(?!钟)", text):
            total_minutes += int(match)
    for match in re.findall(r"(\d+)秒", text):
        total_minutes += int(match) / 60
    return int(round(total_minutes))


def _parse_markdown_table(text, heading):
    lines = text.splitlines()
    in_section = False
    table_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped == heading:
            in_section = True
            continue
        if not in_section:
            continue
        if stripped.startswith("|"):
            table_lines.append(stripped)
            continue
        if table_lines:
            break

    if len(table_lines) < 2:
        raise ValueError(f"Unable to parse markdown table for heading: {heading}")

    headers = [cell.strip() for cell in table_lines[0].split("|")[1:-1]]
    rows = []
    for row_line in table_lines[2:]:
        cells = [cell.strip() for cell in row_line.split("|")[1:-1]]
        if len(cells) != len(headers):
            continue
        rows.append(dict(zip(headers, cells)))
    return rows


def _parse_crops(text):
    rows = _parse_markdown_table(text, "## 一、1-83级完整基础作物数据表")
    crops = []
    for index, row in enumerate(rows, 1):
        crop_id = f"crop-{index:03d}"
        crops.append(
            {
                "crop_id": crop_id,
                "unlock_level": int(row["解锁等级"].replace("级", "")),
                "name": row["作物名称"],
                "growth_minutes": parse_cn_duration_to_minutes(row["自然成熟时间"]),
                "growth_label": row["自然成熟时间"],
                "seed_cost": int(row["种子购买价格"]),
                "base_sell_price": int(row["初始单株售价"]),
                "hourly_income": int(row["每小时收益"]),
                "exp_gain": int(row["获得经验"]),
                "can_mutate": "✅" in row["可变异"],
                "icon_path": "",
            }
        )
    return crops


def _parse_watering_rules(text):
    rows = _parse_markdown_table(text, "## 六、浇水加速机制（更新版）")
    rules = []
    for row in rows:
        natural_minutes = parse_cn_duration_to_minutes(row["作物自然成熟时间"])
        rules.append(
            {
                "natural_minutes": natural_minutes,
                "natural_label": row["作物自然成熟时间"],
                "reduce_minutes": parse_cn_duration_to_minutes(row["一次浇水减少时间"]),
                "watered_growth_minutes": parse_cn_duration_to_minutes(row["浇水后成熟时间"]),
                "interval_minutes": parse_cn_duration_to_minutes(row["浇水间隔"]),
                "max_count": int(row["最多浇水次数"].replace("次", "")),
                "late_block_minutes": 64 if natural_minutes == 32 * 60 else 0,
            }
        )
    return rules


def _mutation_badge(name):
    text = str(name)
    if "蓝" in text:
        return "blue"
    if "紫" in text:
        return "purple"
    if "巨" in text:
        return "giant"
    if "英雄" in text:
        return "hero"
    if "材质" in text or "元素" in text:
        return "teal"
    return "neutral"


def _parse_mutation_types(text):
    rows = _parse_markdown_table(text, "### 1. 变异词条与售价倍率")
    types = []
    for row in rows:
        multiplier_text = re.sub(r"[^\d.]", "", str(row.get("售价倍率", "")))
        note = row.get("叠加说明", "")
        types.append(
            {
                "name": row["词条类型"],
                "rarity": row.get("稀有度", ""),
                "multiplier": float(multiplier_text) if multiplier_text else 1.0,
                "anti_steal": "不可被偷" in note or "防偷" in note,
                "badge": _mutation_badge(row["词条类型"]),
                "note": note,
            }
        )
    return types


def _parse_hero_crops(text):
    rows = _parse_markdown_table(text, "## 二、英雄变异作物完整清单")
    hero_crops = []
    for row in rows:
        hero_crops.append(
            {
                "unlock_level": int(str(row["解锁等级"]).replace("级", "")),
                "name": row["英雄变异名称"],
                "base_crop_name": row["对应普通作物"],
                "growth_label": row["成熟时间"],
                "legacy_multiplier_note": row.get("售价倍率（S43 旧口径）", ""),
            }
        )
    return hero_crops


def _parse_mutations(text):
    payload = copy.deepcopy(DEFAULT_MUTATIONS)
    payload["mutation_types"] = _parse_mutation_types(text)
    payload["hero_crops"] = _parse_hero_crops(text)
    return payload


def _write_json(path, payload):
    with path.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, ensure_ascii=False, indent=2)


def _load_json_file(path):
    with path.open("r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def _needs_regeneration():
    if not CROPS_JSON_PATH.exists() or not WATERING_JSON_PATH.exists():
        return True

    try:
        crops = _load_json_file(CROPS_JSON_PATH)
        watering_rules = _load_json_file(WATERING_JSON_PATH)
    except (OSError, json.JSONDecodeError):
        return True

    first_crop = next((crop for crop in crops if crop.get("name") == "白萝卜"), None)
    rice_crop = next((crop for crop in crops if crop.get("name") == "水稻"), None)
    one_minute_rule = next((rule for rule in watering_rules if int(rule.get("natural_minutes", 0)) == 1), None)

    if not first_crop or first_crop.get("growth_minutes") != 1:
        return True
    if not rice_crop or rice_crop.get("growth_minutes") != 40:
        return True
    if not one_minute_rule or one_minute_rule.get("watered_growth_minutes") != 1:
        return True
    return False


def _needs_mutation_regeneration():
    if not MUTATIONS_JSON_PATH.exists():
        return True
    try:
        payload = _load_json_file(MUTATIONS_JSON_PATH)
    except (OSError, json.JSONDecodeError):
        return True
    return not (
        isinstance(payload, dict)
        and isinstance(payload.get("mutation_types"), list)
        and payload["mutation_types"]
        and isinstance(payload.get("hero_crops"), list)
        and isinstance(payload.get("stack_rules"), dict)
    )


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


def ensure_rule_files():
    ensure_directories()

    if _needs_regeneration():
        source_text = SOURCE_MARKDOWN_PATH.read_text(encoding="utf-8")
        _write_json(CROPS_JSON_PATH, _parse_crops(source_text))
        _write_json(WATERING_JSON_PATH, _parse_watering_rules(source_text))

    if not MECHANICS_JSON_PATH.exists():
        _write_json(MECHANICS_JSON_PATH, DEFAULT_MECHANICS)

    if _needs_mutation_regeneration():
        source_text = SOURCE_MARKDOWN_PATH.read_text(encoding="utf-8")
        _write_json(MUTATIONS_JSON_PATH, _parse_mutations(source_text))


class RuleStore:
    def __init__(self):
        self.reload()

    def reload(self):
        ensure_rule_files()
        self.crops = self._load_json(CROPS_JSON_PATH)
        self.watering_rules = self._load_json(WATERING_JSON_PATH)
        self.mechanics = _deep_merge(
            DEFAULT_MECHANICS,
            self._load_json(MECHANICS_JSON_PATH),
        )
        self.mutations = _deep_merge(
            DEFAULT_MUTATIONS,
            self._load_json(MUTATIONS_JSON_PATH),
        )
        self._crop_map = {crop["crop_id"]: crop for crop in self.crops}
        self._watering_map = {rule["natural_minutes"]: rule for rule in self.watering_rules}
        self._mutation_type_map = {
            mutation["name"]: mutation for mutation in self.mutations.get("mutation_types", [])
        }
        self._cultivation_levels = sorted(
            self.mechanics.get("cultivation_levels", []),
            key=lambda item: item["level"],
        )

    @staticmethod
    def _load_json(path):
        with path.open("r", encoding="utf-8") as file_handle:
            return json.load(file_handle)

    def get_crop(self, crop_id):
        return self._crop_map.get(crop_id)

    def get_watering_rule(self, natural_minutes):
        return self._watering_map.get(natural_minutes)

    def get_mutation_type(self, name):
        return self._mutation_type_map.get(name)

    def get_hero_crops(self):
        return self.mutations.get("hero_crops", [])

    @property
    def crop_options(self):
        return sorted(self.crops, key=lambda crop: (crop["unlock_level"], crop["growth_minutes"], crop["name"]))

    @property
    def mutation_options(self):
        return self.mutations.get("mutation_types", [])

    def resolve_mutation_entries(self, names):
        """把词条名列表解析成结构化结果；未知名与互斥冲突原样返回。"""
        clean_names = []
        for name in names or []:
            text = str(name).strip()
            if text and text not in clean_names:
                clean_names.append(text)

        stack_rules = self.mutations.get("stack_rules", {})
        exclusive_pairs = stack_rules.get("mutually_exclusive", [])

        unknown = [name for name in clean_names if name not in self._mutation_type_map]
        conflicts = []
        for pair in exclusive_pairs:
            hit = [name for name in clean_names if name in pair]
            if len(hit) > 1:
                conflicts.extend(hit)

        entries = [self._mutation_type_map[name] for name in clean_names if name in self._mutation_type_map]
        multiplier = 1.0
        for entry in entries:
            multiplier *= float(entry.get("multiplier", 1.0))

        has_hero = any(entry.get("anti_steal") for entry in entries)
        if has_hero:
            max_entries = stack_rules.get("hero_max_entries", 4)
        else:
            max_entries = stack_rules.get("normal_max_entries", 3)

        return {
            "names": clean_names,
            "entries": entries,
            "unknown": unknown,
            "conflicts": conflicts,
            "multiplier": round(multiplier, 4),
            "has_hero": has_hero,
            "max_entries": max_entries,
        }

    def get_cultivation_level(self, points):
        """按培育值返回当前等级配置（无记录时为 1 级）。"""
        points = int(points or 0)
        current = self._cultivation_levels[0] if self._cultivation_levels else {"level": 1, "multiplier": 1.0, "required_points": 0}
        for level_item in self._cultivation_levels:
            if points >= int(level_item.get("required_points", 0)):
                current = level_item
        return current

    def cultivation_level_by_number(self, level_number):
        for level_item in self._cultivation_levels:
            if int(level_item.get("level", 0)) == int(level_number):
                return level_item
        return self._cultivation_levels[0] if self._cultivation_levels else {"level": 1, "multiplier": 1.0}

    def get_experiences(self):
        if not EXPERIENCES_JSON_PATH.exists():
            return {"repo_url": "", "updated_at": "", "items": []}
        try:
            payload = _load_json_file(EXPERIENCES_JSON_PATH)
        except (OSError, json.JSONDecodeError):
            return {"repo_url": "", "updated_at": "", "items": []}
        if not isinstance(payload, dict):
            return {"repo_url": "", "updated_at": "", "items": []}
        payload.setdefault("repo_url", "")
        payload.setdefault("updated_at", "")
        payload.setdefault("items", [])
        return payload


@lru_cache(maxsize=1)
def get_rule_store():
    return RuleStore()
