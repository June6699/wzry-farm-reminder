"""端到端冒烟测试：临时数据库 + 临时端口，不触碰 data/app.db 与 data/config.json。

运行：py -3.11 smoke_test.py
"""

import json
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

TEMP_DIR = Path(tempfile.mkdtemp(prefix="farm-smoke-"))

import farm_reminder.paths as paths  # noqa: E402

paths.DB_PATH = TEMP_DIR / "app.db"
paths.CONFIG_PATH = TEMP_DIR / "config.json"

from farm_reminder.config_store import ConfigStore, DEFAULT_CONFIG  # noqa: E402
from farm_reminder.database import Database  # noqa: E402
from farm_reminder.rules import get_rule_store  # noqa: E402
from farm_reminder.server import build_handler  # noqa: E402

PORT = 8901
BASE = f"http://127.0.0.1:{PORT}"

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}  {detail}")


def api(path, payload=None):
    if payload is None:
        req = urllib.request.Request(BASE + path)
    else:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            BASE + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as error:
        return json.loads(error.read().decode("utf-8"))


def find_crop_id(boot, name):
    for crop in boot["crops"]:
        if crop["name"] == name:
            return crop["crop_id"]
    return None


def main():
    database = Database(path=paths.DB_PATH)
    database.initialize()
    config_store = ConfigStore(path=paths.CONFIG_PATH)
    config_store.save(DEFAULT_CONFIG)
    services = {
        "config": config_store,
        "rules": get_rule_store(),
        "database": database,
    }
    server = ThreadingHTTPServer(("127.0.0.1", PORT), build_handler(services))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    now = datetime.now()
    now_text = now.isoformat(timespec="minutes")
    harvest_text = (now + timedelta(hours=16)).isoformat(timespec="minutes")

    print("[1] bootstrap")
    boot = api("/api/bootstrap")
    check("作物 114 条", len(boot["crops"]) == 114)
    check("变异词条 6 类", len(boot["mutations"]["mutation_types"]) == 6)
    check("英雄作物 15 条", len(boot["mutations"]["hero_crops"]) == 15)
    check("巨大化徽章修复", all(
        item["badge"] == "giant"
        for item in boot["mutations"]["mutation_types"]
        if "巨" in item["name"]
    ))
    check("英雄词条防偷标记", next(
        item["anti_steal"] for item in boot["mutations"]["mutation_types"] if item["name"] == "英雄变异"
    ))
    check("mechanics 含祝福/偷菜/2级地", all(
        key in boot["mechanics"] for key in ("blessing_rules", "steal_rules", "tier2_field", "level_stall_strategy")
    ))
    check("时刻表已生成", len(boot["clock_events"]) >= 5 and "at" in boot["clock_events"][0])
    check("预置经验 8 条", len(boot["experiences"]["items"]) == 8)
    check("主题默认 system", boot["config"]["appearance"]["theme"] == "system")

    banana_id = find_crop_id(boot, "香蕉")
    radish_id = find_crop_id(boot, "白萝卜")
    check("找到香蕉/白萝卜", bool(banana_id) and bool(radish_id))

    print("[2] 种子背包")
    result = api("/api/seeds", {"crop_id": banana_id, "delta": 3, "source": "购买", "note": "测试"})
    check("登记种子成功", result.get("ok") and result["result"]["quantity"] == 3)
    result = api("/api/seeds", {"crop_id": banana_id, "delta": 0})
    check("delta=0 被拒绝", not result.get("ok"))

    print("[3] 种植 + 变异标记")
    result = api("/api/slots/update", {
        "scope": {"mode": "slot", "slot_id": "F1-R1-C1"},
        "crop_id": banana_id,
        "phase": "planned",
        "start_at": now_text,
        "harvest_at": harvest_text,
        "mutation_entries": ["紫色词条"],
    })
    check("规划并标记紫色词条", result.get("ok"))
    slot = next(
        slot for field in result["dashboard"]["fields"] for slot in field["slots"]
        if slot["slot_id"] == "F1-R1-C1"
    )
    check("倍率 ×2.5", abs(slot["mutation_multiplier"] - 2.5) < 1e-6, str(slot["mutation_multiplier"]))
    expected = 17500 * 1.2 * 2 * 2.5  # 售价 × 小摊20% × 周末 × 变异
    check("预计收入含变异", abs(slot["expected_income"] - expected) < 1.0, f'{slot["expected_income"]} vs {expected}')

    result = api("/api/slots/update", {
        "scope": {"mode": "slot", "slot_id": "F1-R1-C1"},
        "mutation_entries": ["巨大化", "超巨化"],
    })
    check("互斥词条被拒绝", not result.get("ok") and "互斥" in result.get("message", ""))

    result = api("/api/slots/update", {
        "scope": {"mode": "slot", "slot_id": "F1-R1-C1"},
        "mutation_entries": ["蓝色词条", "紫色词条", "材质词条", "巨大化"],
    })
    check("超过 3 条被拒绝", not result.get("ok") and "上限" in result.get("message", ""))

    result = api("/api/slots/update", {
        "scope": {"mode": "slot", "slot_id": "F1-R1-C1"},
        "mutation_entries": ["不存在的词条"],
    })
    check("未知词条被拒绝", not result.get("ok") and "未知" in result.get("message", ""))

    result = api("/api/slots/update", {
        "scope": {"mode": "slot", "slot_id": "F1-R2-C1"},
        "crop_id": radish_id,
        "phase": "planted",
        "start_at": now_text,
        "mutation_entries": ["紫色词条"],
    })
    check("新手作物不可变异", not result.get("ok") and "无法变异" in result.get("message", ""))

    print("[4] 种植消耗种子背包")
    result = api("/api/slots/start", {
        "scope": {"mode": "slot", "slot_id": "F1-R1-C1"},
        "started_at": now_text,
    })
    check("开始种植成功", result.get("ok") and result["result"]["processed_count"] == 1)
    check("优先消耗背包种子", result["result"]["seed_notes"] and "背包 1" in result["result"]["seed_notes"][0], str(result["result"].get("seed_notes")))
    seed_rows = result["dashboard"]["seed_inventory"]
    check("背包剩 2 个种子", seed_rows and seed_rows[0]["quantity"] == 2)

    print("[5] 英雄词条与收获产果实")
    api("/api/slots/update", {
        "scope": {"mode": "slot", "slot_id": "F1-R1-C1"},
        "mutation_entries": ["英雄变异", "紫色词条"],
    })
    result = api("/api/slots/harvest", {
        "scope": {"mode": "slot", "slot_id": "F1-R1-C1"},
        "occurred_at": harvest_text,
    })
    batches = result["result"]["fruit_batches"]
    check("收获产出 1 批果实", result["result"]["processed_count"] == 1 and len(batches) == 1)
    check("周末双倍数量 ×2", batches[0]["quantity"] == 2, str(batches[0]))
    check("词条与倍率随批次入库", batches[0]["mutation_multiplier"] == 70.0)
    fruits = result["dashboard"]["fruits_in_stock"]
    check("背包在库 1 批", len(fruits) == 1)
    unit_price = 17500 * 1.0 * 1.2  # 培育1级 × 小摊20%
    check("果实估值正确", abs(fruits[0]["estimated_total"] - unit_price * 2 * 70) < 1.0, str(fruits[0]["estimated_total"]))
    cultivation = result["dashboard"]["cultivation"]
    check("培育值 +10", cultivation and cultivation[0]["points"] == 10 and cultivation[0]["crop_name"] == "香蕉")
    ledger_types = [row["type"] for row in result["dashboard"]["ledger"]]
    check("收获不再直接入账", "harvest_income" not in ledger_types)

    print("[6] 卖出果实")
    fruit_id = fruits[0]["id"]
    result = api("/api/fruits/sell", {"fruit_ids": [fruit_id]})
    check("卖出成功", result.get("ok") and result["result"]["sold_count"] == 1)
    check("入账 294 万", abs(result["result"]["total_income"] - unit_price * 2 * 70) < 1.0, str(result["result"]["total_income"]))
    ledger_types = [row["type"] for row in result["dashboard"]["ledger"]]
    check("fruit_sell 流水已记账", "fruit_sell" in ledger_types)
    check("卖出后背包清空", len(result["dashboard"]["fruits_in_stock"]) == 0)
    check("图鉴聚合 1 组", len(result["dashboard"]["collection"]) == 1 and result["dashboard"]["collection"][0]["total_quantity"] == 2)

    print("[7] 祝福")
    result = api("/api/blessings", {"direction": "given", "counterparty_name": "好友A", "occurred_at": now_text})
    check("登记发出祝福", result.get("ok"))
    result = api("/api/blessings", {"direction": "received", "occurred_at": now_text})
    check("登记被祝福", result.get("ok"))
    boot = api("/api/bootstrap")
    check("今日计数 1/1", boot["blessing"]["given_today"] == 1 and boot["blessing"]["received_today"] == 1)

    api("/api/slots/update", {
        "scope": {"mode": "slot", "slot_id": "F1-R2-C1"},
        "crop_id": banana_id,
        "phase": "planted",
        "start_at": now_text,
    })
    api("/api/slots/start", {"scope": {"mode": "slot", "slot_id": "F1-R2-C1"}, "started_at": now_text})
    ok_count = 0
    for _ in range(4):
        result = api("/api/blessings", {"direction": "received", "slot_id": "F1-R2-C1", "occurred_at": now_text})
        if result.get("ok"):
            ok_count += 1
    check("单株祝福 3 次上限", ok_count == 3, f"ok_count={ok_count}")

    for _ in range(9):
        api("/api/blessings", {"direction": "given", "occurred_at": now_text})
    result = api("/api/blessings", {"direction": "given", "occurred_at": now_text})
    check("每日发出 10 次上限", not result.get("ok") and "上限" in result.get("message", ""))

    print("[8] 偷菜配额")
    result = api("/api/raids", {
        "direction": "outbound",
        "crop_id": banana_id,
        "quantity": 2,
        "is_weekend_bonus_time": True,
        "occurred_at": now_text,
    })
    check("登记偷菜", result.get("ok"))
    boot = api("/api/bootstrap")
    check("配额计数 1", boot["steal_quota"]["outbound_today"] == 1)

    print("[9] 主题设置")
    dark_config = {**boot["config"], "appearance": {"theme": "dark"}}
    result = api("/api/settings", dark_config)
    check("主题保存为 dark", result.get("ok") and result["config"]["appearance"]["theme"] == "dark")
    result = api("/api/settings", {**dark_config, "appearance": {"theme": "pink"}})
    check("非法主题回落 system", result["config"]["appearance"]["theme"] == "system")

    print("[10] experiences 端点")
    result = api("/api/experiences")
    check("experiences 返回预置内容", len(result["items"]) == 8 and result["repo_url"].startswith("https://github.com"))

    server.shutdown()
    print()
    print(f"结果：{len(PASSED)} 通过，{len(FAILED)} 失败")
    if FAILED:
        for name in FAILED:
            print(f"  - {name}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TEMP_DIR, ignore_errors=True)
