import json
import re
from functools import lru_cache

from .paths import RULES_DIR, SOURCE_MARKDOWN_PATH, ensure_directories


CROPS_JSON_PATH = RULES_DIR / "crops.json"
WATERING_JSON_PATH = RULES_DIR / "watering_rules.json"
MECHANICS_JSON_PATH = RULES_DIR / "game_mechanics.json"


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


def _write_json(path, payload):
    with path.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, ensure_ascii=False, indent=2)


def _needs_regeneration():
    if not CROPS_JSON_PATH.exists() or not WATERING_JSON_PATH.exists():
        return True

    try:
        crops = json.loads(CROPS_JSON_PATH.read_text(encoding="utf-8"))
        watering_rules = json.loads(WATERING_JSON_PATH.read_text(encoding="utf-8"))
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


def ensure_rule_files():
    ensure_directories()
    if (
        CROPS_JSON_PATH.exists()
        and WATERING_JSON_PATH.exists()
        and MECHANICS_JSON_PATH.exists()
        and not _needs_regeneration()
    ):
        return

    source_text = SOURCE_MARKDOWN_PATH.read_text(encoding="utf-8")
    _write_json(CROPS_JSON_PATH, _parse_crops(source_text))
    _write_json(WATERING_JSON_PATH, _parse_watering_rules(source_text))
    if not MECHANICS_JSON_PATH.exists():
        _write_json(MECHANICS_JSON_PATH, DEFAULT_MECHANICS)


class RuleStore:
    def __init__(self):
        self.reload()

    def reload(self):
        ensure_rule_files()
        self.crops = self._load_json(CROPS_JSON_PATH)
        self.watering_rules = self._load_json(WATERING_JSON_PATH)
        self.mechanics = self._load_json(MECHANICS_JSON_PATH)
        self._crop_map = {crop["crop_id"]: crop for crop in self.crops}
        self._watering_map = {rule["natural_minutes"]: rule for rule in self.watering_rules}

    @staticmethod
    def _load_json(path):
        with path.open("r", encoding="utf-8") as file_handle:
            return json.load(file_handle)

    def get_crop(self, crop_id):
        return self._crop_map.get(crop_id)

    def get_watering_rule(self, natural_minutes):
        return self._watering_map.get(natural_minutes)

    @property
    def crop_options(self):
        return sorted(self.crops, key=lambda crop: (crop["unlock_level"], crop["growth_minutes"], crop["name"]))


@lru_cache(maxsize=1)
def get_rule_store():
    return RuleStore()
