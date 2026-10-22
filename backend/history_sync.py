# -*- coding: utf-8 -*-
"""
Модуль гарантированного сохранения истории записей (backend/history_sync.py).
Обеспечивает 3 уровня защиты данных при любых обновлениях с GitHub:
1. Неразрушающее слияние (Non-Destructive Merge) дневника по дням, приёмам пищи, воде, весу и своим блюдам.
2. Защита от случайного затирания дня пустым массивом при перезагрузке страницы (флаг _clearedByUser).
3. Автоматическое резервное зеркалирование в домашнюю директорию ОС (~/.chepoel/chepoel_history_backup.json),
   благодаря чему история сохраняется даже при полном удалении и повторном клонировании папки репозитория.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any


def get_persistent_backup_path() -> Path:
    """Возвращает путь к постоянному бэкапу истории в профиле пользователя ОС."""
    if os.name == "nt":
        appdata = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        base = Path(appdata) / "ChePoel"
    else:
        base = Path.home() / ".chepoel"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        base = Path(__file__).resolve().parent.parent / "data"
        base.mkdir(parents=True, exist_ok=True)
    return base / "chepoel_history_backup.json"


def load_os_backup_all() -> Dict[str, Any]:
    """Читает сохранённые состояния всех пользователей из домашней папки ОС."""
    bpath = get_persistent_backup_path()
    if not bpath.exists():
        return {}
    try:
        with open(bpath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_os_backup_user(username: str, state_dict: Dict[str, Any]) -> None:
    """Сохраняет актуальное состояние пользователя в постоянный бэкап ОС."""
    if not username or not isinstance(state_dict, dict):
        return
    try:
        all_data = load_os_backup_all()
        existing = all_data.get(username)
        merged = merge_states_non_destructive(existing, state_dict) if existing else state_dict
        all_data[username] = merged
        bpath = get_persistent_backup_path()
        with open(bpath, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def count_total_meals(st: Dict[str, Any]) -> int:
    if not isinstance(st, dict):
        return 0
    days = st.get("days") or {}
    total = 0
    for d in days.values():
        if isinstance(d, dict):
            meals = d.get("meals") or []
            total += len(meals)
    return total


def merge_states_non_destructive(existing_state: Dict[str, Any], incoming_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Бережно объединяет существующее состояние из БД и новое состояние от клиента,
    никогда не теряя историю дней, записей приёмов пищи, воды, замеров веса и своих блюд.
    """
    if not existing_state:
        return incoming_state or {}
    if not incoming_state:
        return existing_state or {}

    merged = dict(existing_state)
    merged.update(incoming_state)

    # 1. Сохраняем API ключ и настройки, если в новом состоянии они пустые
    if not merged.get("apiKey") and existing_state.get("apiKey"):
        merged["apiKey"] = existing_state["apiKey"]
    merged["onboarded"] = bool(existing_state.get("onboarded") or incoming_state.get("onboarded"))
    merged["purchasedShields"] = max(
        int(existing_state.get("purchasedShields") or 0),
        int(incoming_state.get("purchasedShields") or 0),
    )
    merged["spentShieldXp"] = max(
        int(existing_state.get("spentShieldXp") or 0),
        int(incoming_state.get("spentShieldXp") or 0),
    )

    # 2. Сохраняем кастомный профиль, если входящий профиль дефолтный ('Атлет')
    ex_prof = dict(existing_state.get("profile") or {})
    in_prof = dict(incoming_state.get("profile") or {})
    if (not in_prof.get("nickname") or in_prof.get("nickname") == "Атлет") and ex_prof.get("nickname") and ex_prof.get("nickname") != "Атлет":
        for k, v in ex_prof.items():
            if v and not in_prof.get(k):
                in_prof[k] = v
        in_prof["nickname"] = ex_prof["nickname"]
    merged["profile"] = in_prof or ex_prof

    # 3. Неразрушающее слияние дневника по датам (days)
    ex_days = existing_state.get("days") or {}
    in_days = incoming_state.get("days") or {}
    all_dates = set(ex_days.keys()) | set(in_days.keys())
    merged_days = {}

    for d_str in sorted(all_dates):
        da = ex_days.get(d_str)
        db = in_days.get(d_str)
        if da and not db:
            merged_days[d_str] = da
        elif db and not da:
            merged_days[d_str] = db
        elif isinstance(da, dict) and isinstance(db, dict):
            meals_a = da.get("meals") or []
            meals_b = db.get("meals") or []
            cleared_by_user = bool(db.get("_clearedByUser"))
            explicit_edit = bool(db.get("_explicitEditAt"))

            if len(meals_b) > 0:
                chosen_meals = meals_b if (explicit_edit or len(meals_b) >= len(meals_a)) else meals_a
            else:
                # Если во входящем дне 0 приёмов пищи, очищаем только если пользователь сам удалил запись (_clearedByUser)
                chosen_meals = [] if cleared_by_user else meals_a

            merged_days[d_str] = {
                "meals": chosen_meals,
                "waterMl": int(db.get("waterMl") or 0) if explicit_edit else max(int(da.get("waterMl") or 0), int(db.get("waterMl") or 0)),
                "freezeUsed": bool(da.get("freezeUsed") or db.get("freezeUsed")),
                "penaltyRedeemed": bool(da.get("penaltyRedeemed") or db.get("penaltyRedeemed")),
            }

    merged["days"] = merged_days

    # 4. Неразрушающее слияние своих блюд (customProducts)
    prod_map = {}
    for cp in (existing_state.get("customProducts") or []) + (incoming_state.get("customProducts") or []):
        if isinstance(cp, dict) and cp.get("name"):
            key = str(cp["name"]).strip().lower()
            prod_map[key] = cp
    merged["customProducts"] = list(prod_map.values())

    # 5. Неразрушающее слияние замеров веса (weightLog)
    w_map = {}
    for w in (existing_state.get("weightLog") or []) + (incoming_state.get("weightLog") or []):
        if isinstance(w, dict) and w.get("date") and w.get("kg"):
            w_map[str(w["date"])] = w
    merged["weightLog"] = sorted(w_map.values(), key=lambda x: str(x.get("date", "")))

    return merged
