import math
from datetime import datetime, timedelta, time


def parse_hhmm(value):
    hour_text, minute_text = str(value).split(":")
    return int(hour_text), int(minute_text)


def hhmm_to_minutes(value):
    hour, minute = parse_hhmm(value)
    return hour * 60 + minute


def combine_date_and_hhmm(day_value, hhmm_value):
    hour, minute = parse_hhmm(hhmm_value)
    return datetime.combine(day_value, time(hour=hour, minute=minute))


def ceil_to_step(dt_value, step_minutes=5):
    discard = timedelta(
        minutes=dt_value.minute % step_minutes,
        seconds=dt_value.second,
        microseconds=dt_value.microsecond,
    )
    dt_value = dt_value - discard
    if discard:
        dt_value += timedelta(minutes=step_minutes)
    return dt_value


def format_datetime(dt_value):
    return dt_value.strftime("%Y-%m-%d %H:%M")


def format_duration(minutes):
    total = int(round(minutes))
    if total <= 0:
        return "0分钟"
    hours, minute_value = divmod(total, 60)
    parts = []
    if hours:
        parts.append(f"{hours}小时")
    if minute_value:
        parts.append(f"{minute_value}分钟")
    return "".join(parts)


def is_in_daily_window(dt_value, start_hhmm, end_hhmm):
    minute_of_day = dt_value.hour * 60 + dt_value.minute
    start_minutes = hhmm_to_minutes(start_hhmm)
    end_minutes = hhmm_to_minutes(end_hhmm)
    if start_minutes < end_minutes:
        return start_minutes <= minute_of_day < end_minutes
    return minute_of_day >= start_minutes or minute_of_day < end_minutes


def is_weekend_bonus_time(dt_value):
    weekday = dt_value.weekday()
    minute_of_day = dt_value.hour * 60 + dt_value.minute
    if weekday == 4:
        return minute_of_day >= 18 * 60
    if weekday == 5:
        return True
    if weekday == 6:
        return True
    return False


def _build_strategy(crop, rule, strategy_id):
    if strategy_id == "watered" and rule:
        effective_growth = int(rule["watered_growth_minutes"])
        interval = int(rule["interval_minutes"])
        max_count = int(rule["max_count"])
        required_count = 0
        if interval > 0 and effective_growth > interval:
            required_count = max(0, math.ceil(effective_growth / interval) - 1)
        required_count = min(required_count, max_count)
        return {
            "strategy_id": "watered",
            "strategy_name": "浇水压缩成熟",
            "growth_minutes": effective_growth,
            "watering_count": required_count,
            "interval_minutes": interval,
            "late_block_minutes": int(rule.get("late_block_minutes", 0)),
            "reduce_minutes": int(rule["reduce_minutes"]),
        }

    return {
        "strategy_id": "natural",
        "strategy_name": "自然成熟",
        "growth_minutes": int(crop["growth_minutes"]),
        "watering_count": 0,
        "interval_minutes": 0,
        "late_block_minutes": 0,
        "reduce_minutes": 0,
    }


def _build_plan_from_plant_time(crop, strategy, plant_at, config, plot_count):
    harvest_at = plant_at + timedelta(minutes=strategy["growth_minutes"])
    watering_times = []
    if strategy["watering_count"] > 0 and strategy["interval_minutes"] > 0:
        for index in range(1, strategy["watering_count"] + 1):
            watering_times.append(plant_at + timedelta(minutes=strategy["interval_minutes"] * index))

    stall_pct = int(config["player"]["stall_bonus_pct"])
    unit_price = crop["base_sell_price"] * (1 + stall_pct / 100)
    income = unit_price * plot_count
    is_weekend = is_weekend_bonus_time(harvest_at)
    if is_weekend:
        income *= 2
    cost = crop["seed_cost"] * plot_count
    net_income = income - cost

    anti_theft_enabled = bool(config["planner"]["anti_theft_enabled"])
    anti_theft_safe = (
        anti_theft_enabled
        and is_in_daily_window(
            harvest_at,
            config["planner"]["anti_theft_safe_start"],
            config["planner"]["anti_theft_safe_end"],
        )
    )

    return {
        "strategy_id": strategy["strategy_id"],
        "strategy_name": strategy["strategy_name"],
        "plot_count": plot_count,
        "plant_at": plant_at.isoformat(timespec="minutes"),
        "plant_at_label": format_datetime(plant_at),
        "harvest_at": harvest_at.isoformat(timespec="minutes"),
        "harvest_at_label": format_datetime(harvest_at),
        "growth_label": format_duration(strategy["growth_minutes"]),
        "watering_times": [
            {
                "time": watering_time.isoformat(timespec="minutes"),
                "label": format_datetime(watering_time),
            }
            for watering_time in watering_times
        ],
        "watering_count": len(watering_times),
        "is_weekend_bonus_time": is_weekend,
        "is_anti_theft_safe": anti_theft_safe,
        "unit_price": round(unit_price, 2),
        "seed_cost_total": round(cost, 2),
        "estimated_income": round(income, 2),
        "estimated_net_income": round(net_income, 2),
    }


def _find_first_matching_plan(crop, strategy, config, plot_count, predicate, step_minutes=5):
    horizon_days = int(config["planner"]["search_horizon_days"])
    now = datetime.now()
    start_harvest = ceil_to_step(now + timedelta(minutes=strategy["growth_minutes"]), step_minutes)
    total_steps = int((horizon_days * 24 * 60) / step_minutes)

    for step in range(total_steps + 1):
        harvest_candidate = start_harvest + timedelta(minutes=step * step_minutes)
        if not predicate(harvest_candidate):
            continue
        plant_at = harvest_candidate - timedelta(minutes=strategy["growth_minutes"])
        if plant_at < now:
            continue
        return _build_plan_from_plant_time(crop, strategy, plant_at, config, plot_count)
    return None


def _find_best_weekend_plan(crop, strategy, config, plot_count, require_anti_theft=False):
    preferred_minutes = hhmm_to_minutes(config["planner"]["weekend_target_time"])
    horizon_days = max(7, int(config["planner"]["search_horizon_days"]) * 2)
    now = datetime.now()
    start_harvest = ceil_to_step(now + timedelta(minutes=strategy["growth_minutes"]), 5)
    best_score = None
    best_plan = None

    for step in range(int((horizon_days * 24 * 60) / 5) + 1):
        harvest_candidate = start_harvest + timedelta(minutes=step * 5)
        if not is_weekend_bonus_time(harvest_candidate):
            continue
        if require_anti_theft and not is_in_daily_window(
            harvest_candidate,
            config["planner"]["anti_theft_safe_start"],
            config["planner"]["anti_theft_safe_end"],
        ):
            continue

        plant_at = harvest_candidate - timedelta(minutes=strategy["growth_minutes"])
        if plant_at < now:
            continue

        minute_of_day = harvest_candidate.hour * 60 + harvest_candidate.minute
        day_rank = 0 if harvest_candidate.weekday() == 4 else 1 if harvest_candidate.weekday() == 5 else 2
        score = (day_rank, abs(minute_of_day - preferred_minutes), harvest_candidate)
        if best_score is None or score < best_score:
            best_score = score
            best_plan = _build_plan_from_plant_time(crop, strategy, plant_at, config, plot_count)

    return best_plan


def build_planner_payload(crop, watering_rule, config, plot_count):
    strategies = [_build_strategy(crop, watering_rule, "natural")]
    if config["planner"]["auto_use_watering_strategy"] and watering_rule:
        strategies.append(_build_strategy(crop, watering_rule, "watered"))

    plant_now_assessments = []
    anti_theft_recommendations = []
    weekend_recommendations = []
    combined_recommendations = []

    now = datetime.now()
    for strategy in strategies:
        plant_now_plan = _build_plan_from_plant_time(crop, strategy, now, config, plot_count)
        if config["planner"]["anti_theft_enabled"] and not plant_now_plan["is_anti_theft_safe"]:
            plant_now_plan["status"] = "risk"
            plant_now_plan["summary"] = "如果现在播种，收获会落在可偷时段。"
        else:
            plant_now_plan["status"] = "safe"
            plant_now_plan["summary"] = "如果现在播种，这条方案可以落在防偷窗口内。"
        if plant_now_plan["is_weekend_bonus_time"]:
            plant_now_plan["summary"] += " 同时还能吃到周末双倍。"
        plant_now_assessments.append(plant_now_plan)

        anti_theft_plan = None
        if config["planner"]["anti_theft_enabled"]:
            anti_theft_plan = _find_first_matching_plan(
                crop,
                strategy,
                config,
                plot_count,
                lambda harvest_candidate: is_in_daily_window(
                    harvest_candidate,
                    config["planner"]["anti_theft_safe_start"],
                    config["planner"]["anti_theft_safe_end"],
                ),
            )
        if anti_theft_plan:
            anti_theft_plan["summary"] = "这是当前能卡进防偷窗口的最早可行方案。"
            anti_theft_recommendations.append(anti_theft_plan)

        weekend_plan = _find_best_weekend_plan(crop, strategy, config, plot_count, require_anti_theft=False)
        if weekend_plan:
            weekend_plan["summary"] = "这是当前最接近周末目标收获时间的双倍方案。"
            weekend_recommendations.append(weekend_plan)

        combined_plan = None
        if config["planner"]["anti_theft_enabled"]:
            combined_plan = _find_best_weekend_plan(crop, strategy, config, plot_count, require_anti_theft=True)
        if combined_plan:
            combined_plan["summary"] = "这条方案同时满足周末双倍和防偷窗口。"
            combined_recommendations.append(combined_plan)

    anti_theft_recommendation = anti_theft_recommendations[0] if anti_theft_recommendations else None
    weekend_recommendation = weekend_recommendations[0] if weekend_recommendations else None
    combined_recommendation = combined_recommendations[0] if combined_recommendations else None

    warning = ""
    if config["planner"]["anti_theft_enabled"]:
        all_risky_now = all(item["status"] == "risk" for item in plant_now_assessments)
        if all_risky_now and not anti_theft_recommendation:
            warning = "现在立刻播种无法卡进防偷窗口，继续种会暴露在可偷时段。"
        elif all_risky_now:
            warning = "现在立刻播种来不及防偷，建议按推荐时间再种。"

    return {
        "generated_at": datetime.now().isoformat(timespec="minutes"),
        "crop": crop,
        "plot_count": plot_count,
        "plant_now_assessments": plant_now_assessments,
        "anti_theft_recommendation": anti_theft_recommendation,
        "weekend_recommendation": weekend_recommendation,
        "combined_recommendation": combined_recommendation,
        "warning": warning,
    }
