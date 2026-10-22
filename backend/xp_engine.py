# -*- coding: utf-8 -*-
"""Бизнес-логика расчёта норм КБЖУ (Миффлин — Сан-Жеор), опыта XP, уровней и штрафов дисциплины."""

from datetime import date, timedelta
from typing import Dict, Any, List

LEVEL_RANKS = [
    (1,  "🌱 Новичок режима"),
    (5,  "⚡ Кибер-Следопыт"),
    (10, "💜 Адепт Дисциплины"),
    (15, "🔥 Машина Режима"),
    (20, "👑 Повелитель Калорий"),
    (25, "🌌 Архитектор Формы"),
    (30, "💎 Легенда ЧёПоел"),
]


def get_xp_needed_for_next_level(lvl: int) -> int:
    """С каждым уровнем требуется на 85 XP больше, чем на предыдущем (база 200 XP)."""
    return 200 + (max(1, lvl) - 1) * 85


def get_rank_title_for_level(lvl: int) -> str:
    rank = LEVEL_RANKS[0][1]
    for min_lvl, title in LEVEL_RANKS:
        if lvl >= min_lvl:
            rank = title
    return rank


def evaluate_day_color_status(kcal: int, target_kcal: int, goal_mode: str) -> Dict[str, str]:
    """Определяет статус дня (green / yellow / red) в зависимости от сценария (lose / maintain / gain)."""
    if not kcal or kcal <= 0:
        return {"status": "none", "label": "Нет записей", "css": ""}
    ratio = kcal / max(1, target_kcal)

    if goal_mode == "lose":
        if 0.80 <= ratio <= 1.02:
            return {"status": "green", "label": "Идеальный дефицит (Зелёная зона)", "css": "cal-green"}
        if (0.70 <= ratio < 0.80) or (1.02 < ratio <= 1.12):
            lbl = "Заметный недобор калорий" if ratio < 0.80 else "Небольшое превышение нормы"
            return {"status": "yellow", "label": lbl, "css": "cal-yellow"}
        lbl = "Сильный недобор (голодание)" if ratio < 0.70 else "Перебор калорий"
        return {"status": "red", "label": lbl, "css": "cal-red"}

    if goal_mode == "gain":
        if 0.96 <= ratio <= 1.16:
            return {"status": "green", "label": "Отличный профицит для роста", "css": "cal-green"}
        if (0.86 <= ratio < 0.96) or (1.16 < ratio <= 1.26):
            return {"status": "yellow", "label": "Небольшое отклонение от цели набора", "css": "cal-yellow"}
        lbl = "Сильный недобор для массы" if ratio < 0.86 else "Слишком большой профицит"
        return {"status": "red", "label": lbl, "css": "cal-red"}

    if 0.90 <= ratio <= 1.08:
        return {"status": "green", "label": "Точное попадание в баланс", "css": "cal-green"}
    if (0.78 <= ratio < 0.90) or (1.08 < ratio <= 1.18):
        return {"status": "yellow", "label": "Умеренное отклонение от баланса", "css": "cal-yellow"}
    return {"status": "red", "label": "Сильное отклонение", "css": "cal-red"}


def calculate_mifflin_st_jeor(
    gender: str, age: int, height_cm: float, weight_kg: float, activity: float, goal_mode: str
) -> Dict[str, Any]:
    """Расчёт дневной нормы КБЖУ по формуле Миффлина — Сан-Жеора."""
    bmr = (10.0 * weight_kg) + (6.25 * height_cm) - (5.0 * age) + (5.0 if gender == "m" else -161.0)
    tdee = bmr * activity
    label = "Поддержание"
    if goal_mode == "lose":
        tdee *= 0.85
        label = "Похудение (-15%)"
    elif goal_mode == "gain":
        tdee *= 1.15
        label = "Набор массы (+15%)"

    kcal = max(800, round(tdee))
    p = max(20, round((kcal * 0.28) / 4.0))
    f = max(20, round((kcal * 0.28) / 9.0))
    c = max(20, round((kcal * 0.44) / 4.0))
    return {"kcal": kcal, "p": p, "f": f, "c": c, "mode": goal_mode, "label": label}


def compute_user_progression(
    days_dict: Dict[str, Any],
    kcal_target: int,
    goal_mode: str,
    custom_products_count: int,
    weight_logs_count: int,
    registered_date_str: str,
    purchased_shields: int = 0,
    spent_shield_xp: int = 0,
    bonus_xp: int = 0,
) -> Dict[str, Any]:
    """Вычисляет уровень, прогресс XP, стрик, пропущенные дни и баланс щитов заморозки."""
    total_meals = 0
    green_days = 0
    logged_days = 0
    water_norm_days = 0

    for d_str, day_obj in days_dict.items():
        if (day_obj.get("waterMl") or 0) >= 1500:
            water_norm_days += 1
        meals = day_obj.get("meals") or []
        if len(meals) > 0:
            logged_days += 1
            total_meals += len(meals)
            day_kcal = sum(int(m.get("kcal") or 0) for m in meals)
            ev = evaluate_day_color_status(day_kcal, kcal_target, goal_mode)
            if ev["status"] == "green":
                green_days += 1

    total_earned_shields = 1 + (green_days // 5) + max(0, int(purchased_shields))
    used_shields_count = sum(1 for d in days_dict.values() if d.get("freezeUsed"))
    available_shields = max(0, total_earned_shields - used_shields_count)

    today_str = date.today().isoformat()
    earliest_str = registered_date_str or today_str
    for d_str, d_obj in days_dict.items():
        meals = d_obj.get("meals") or []
        if len(meals) > 0 or d_obj.get("simulatedMiss") or d_obj.get("freezeUsed") or d_obj.get("penaltyRedeemed"):
            if d_str < earliest_str:
                earliest_str = d_str

    missed_days: List[str] = []
    frozen_days: List[str] = []
    redeemed_days: List[str] = []

    if earliest_str < today_str:
        cur = date.fromisoformat(earliest_str)
        today_dt = date.fromisoformat(today_str)
        safety = 0
        while cur < today_dt and safety < 366:
            d_str = cur.isoformat()
            d_obj = days_dict.get(d_str) or {}
            meals = d_obj.get("meals") or []
            if len(meals) == 0:
                if d_obj.get("freezeUsed"):
                    frozen_days.append(d_str)
                elif d_obj.get("penaltyRedeemed"):
                    redeemed_days.append(d_str)
                else:
                    missed_days.append(d_str)
            cur += timedelta(days=1)
            safety += 1

    # Стрик
    streak = 0
    cursor = date.today()
    for i in range(365):
        d_str = cursor.isoformat()
        d_obj = days_dict.get(d_str) or {}
        meals = d_obj.get("meals") or []
        if len(meals) > 0:
            streak += 1
        elif d_obj.get("freezeUsed") or d_obj.get("penaltyRedeemed"):
            pass
        elif i > 0:
            break
        cursor -= timedelta(days=1)

    streak_bonus_xp = 350 if streak >= 7 else (120 if streak >= 3 else 0)
    earned_xp = (
        (total_meals * 45)
        + (green_days * 140)
        + (water_norm_days * 60)
        + (custom_products_count * 75)
        + (weight_logs_count * 40)
        + streak_bonus_xp
        + int(bonus_xp or 0)
    )

    consecutive_miss_penalty = 50 if len(missed_days) >= 2 else 0
    penalty_xp = (len(missed_days) * 100) + consecutive_miss_penalty
    xp = max(0, earned_xp - penalty_xp - int(spent_shield_xp or 0))

    level = 1
    rem_xp = xp
    while level < 100:
        needed = get_xp_needed_for_next_level(level)
        if rem_xp >= needed:
            rem_xp -= needed
            level += 1
        else:
            break

    return {
        "level": level,
        "xp": xp,
        "earnedXp": earned_xp,
        "penaltyXp": penalty_xp,
        "missedDaysCount": len(missed_days),
        "missedDaysList": missed_days,
        "frozenDaysList": frozen_days,
        "redeemedDaysList": redeemed_days,
        "availableShields": available_shields,
        "usedShieldsCount": used_shields_count,
        "currentLevelXp": rem_xp,
        "nextLevelXp": get_xp_needed_for_next_level(level),
        "streak": streak,
        "totalMeals": total_meals,
        "greenDays": green_days,
        "loggedDays": logged_days,
        "waterNormDays": water_norm_days,
        "rankTitle": get_rank_title_for_level(level),
    }
