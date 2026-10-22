# -*- coding: utf-8 -*-
"""
Главный сервер приложения «ЧёПоел» на Python (FastAPI + SQLAlchemy 2.0 + PostgreSQL / SQLite).
Гарантирует 100% сохранение истории записей (приёмов пищи, воды, веса, своих блюд и профиля)
благодаря неразрушающему слиянию (history_sync.py) и автобэкапу в домашней папке пользователя.
"""

import hashlib
import os
from datetime import date, datetime
from typing import Any, Dict

from fastapi import FastAPI, Depends, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from .database import Base, engine, get_db, ensure_non_destructive_migrations
from .models import Account, Profile, Product, DailyLog, MealEntry, WeightLog, LevelReward
from .schemas import AuthRegisterRequest, AuthLoginRequest, MealItemSchema
from .seed_products import seed_database
from .xp_engine import compute_user_progression, calculate_mifflin_st_jeor
from .history_sync import (
    merge_states_non_destructive,
    load_os_backup_all,
    save_os_backup_user,
)

app = FastAPI(
    title="ЧёПоел API (Python + PostgreSQL / SQLite)",
    description="Реляционный бэкенд умного дневника КБЖУ с защитой истории записей (3НФ)",
    version="6.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def hash_password(raw_password: str) -> str:
    """Хэширование пароля SHA-256 с солью chepoel_salt_v4_."""
    salted = "chepoel_salt_v4_" + (raw_password or "").strip()
    return hashlib.sha256(salted.encode("utf-8")).hexdigest()


def assemble_user_state(db: Session, username: str) -> dict:
    """Собирает полное состояние пользователя из 7 нормализованных таблиц и объединяет с бэкапом ОС."""
    acc = db.query(Account).filter(Account.username == username).first()
    os_backups = load_os_backup_all()
    backup_state = os_backups.get(username)

    if not acc:
        if backup_state:
            # Автовосстановление из постоянного бэкапа ОС, если папка БД была пересоздана после git clone
            persist_merged_state_to_db(db, username, backup_state)
            acc = db.query(Account).filter(Account.username == username).first()
        if not acc:
            raise HTTPException(status_code=404, detail=f"Пользователь @{username} ещё не создан")

    prof = acc.profile
    if not prof:
        prof = Profile(username=username, nickname=acc.display_name or username)
        db.add(prof)
        db.commit()
        db.refresh(prof)

    days_dict = {}
    logs = db.query(DailyLog).filter(DailyLog.username == username).all()
    for log in logs:
        d_str = log.log_date.isoformat()
        meals_list = []
        for m in log.meals:
            is_liq = bool(getattr(m, "is_liquid", False))
            meals_list.append({
                "id": m.meal_id,
                "name": m.dish_name,
                "mealType": m.meal_type,
                "grams": m.grams,
                "kcal": m.kcal,
                "p": float(m.p),
                "f": float(m.f),
                "c": float(m.c),
                "kcal100": m.kcal100,
                "p100": float(m.p100),
                "f100": float(m.f100),
                "c100": float(m.c100),
                "isLiquid": is_liq,
                "liquidMl": m.grams if is_liq else 0,
                "photo": getattr(m, "photo_b64", "") or "",
                "time": m.logged_time,
                "productId": m.product_id,
            })
        days_dict[d_str] = {
            "meals": meals_list,
            "waterMl": log.water_ml,
            "freezeUsed": bool(log.freeze_used),
            "penaltyRedeemed": bool(log.penalty_redeemed),
            "simulatedMiss": bool(log.simulated_miss),
        }

    weights = (
        db.query(WeightLog)
        .filter(WeightLog.username == username)
        .order_by(WeightLog.measure_date.asc())
        .all()
    )
    weight_log_list = [{"date": w.measure_date.isoformat(), "kg": float(w.weight_kg)} for w in weights]

    custom_prods = (
        db.query(Product)
        .filter(Product.creator_username == username, Product.is_custom == True)  # noqa: E712
        .order_by(Product.created_at.desc())
        .all()
    )
    custom_products_list = [
        {
            "id": p.product_id,
            "name": p.name,
            "brand": p.brand,
            "category": p.category,
            "icon": p.icon,
            "kcal100": p.kcal100,
            "p100": float(p.p100),
            "f100": float(p.f100),
            "c100": float(p.c100),
            "portion": p.default_portion,
            "custom": True,
            "isLiquid": bool(getattr(p, "is_liquid", False)),
        }
        for p in custom_prods
    ]

    reg_str = acc.registered_date.isoformat() if acc.registered_date else date.today().isoformat()
    stats = compute_user_progression(
        days_dict=days_dict,
        kcal_target=prof.kcal_target,
        goal_mode=prof.goal_mode,
        custom_products_count=len(custom_products_list),
        weight_logs_count=len(weight_log_list),
        registered_date_str=reg_str,
        purchased_shields=prof.purchased_shields,
        spent_shield_xp=prof.spent_shield_xp,
        bonus_xp=prof.bonus_xp,
    )

    assembled = {
        "username": acc.username,
        "displayName": acc.display_name,
        "registeredDate": reg_str,
        "onboarded": bool(prof.onboarded),
        "theme": prof.theme or "dark",
        "apiKey": getattr(prof, "api_key", "") or "",
        "purchasedShields": prof.purchased_shields,
        "spentShieldXp": prof.spent_shield_xp,
        "bonusXp": prof.bonus_xp,
        "lastSeenLevel": prof.last_seen_level,
        "goals": {
            "kcal": prof.kcal_target,
            "p": prof.p_target,
            "f": prof.f_target,
            "c": prof.c_target,
            "mode": prof.goal_mode,
            "label": prof.goal_label,
        },
        "profile": {
            "nickname": prof.nickname,
            "status": prof.status_text,
            "avatarEmoji": prof.avatar_emoji,
            "avatarImg": prof.avatar_img_b64 or "",
            "bannerImg": prof.banner_img_b64 or "",
            "frame": prof.frame_class,
            "banner": prof.banner_class,
            "nickEffect": prof.nick_effect or "",
        },
        "days": days_dict,
        "weightLog": weight_log_list,
        "customProducts": custom_products_list,
        "computedStats": stats,
        "_updatedAt": int(datetime.utcnow().timestamp() * 1000),
    }

    if backup_state:
        assembled = merge_states_non_destructive(backup_state, assembled)
    return assembled


def persist_merged_state_to_db(
    db: Session,
    uname: str,
    incoming_raw: Dict[str, Any],
    pass_hash: str = None,
    display_name: str = None,
) -> Dict[str, Any]:
    """
    Неразрушающее сохранение состояния пользователя в 7 таблиц БД и в постоянный бэкап ОС.
    Никогда не удаляет прошлые дни или приёмы пищи, если пользователь явно не удалял запись.
    """
    uname = (uname or "guest").strip().lower()

    existing_state = None
    acc = db.query(Account).filter(Account.username == uname).first()
    if acc:
        try:
            existing_state = assemble_user_state(db, uname)
        except Exception:
            existing_state = None
    else:
        os_backups = load_os_backup_all()
        existing_state = os_backups.get(uname)

    state = merge_states_non_destructive(existing_state, incoming_raw) if existing_state else incoming_raw

    p_data = state.get("profile") or {}
    g_data = state.get("goals") or {}
    disp = str(display_name or p_data.get("nickname") or uname)[:100]
    reg_str = str(state.get("registeredDate") or date.today().isoformat())[:10]
    try:
        reg_dt = date.fromisoformat(reg_str)
    except ValueError:
        reg_dt = date.today()

    if not acc:
        acc = Account(
            username=uname,
            display_name=disp,
            pass_hash=pass_hash or "sha256_synced",
            registered_date=reg_dt,
        )
        db.add(acc)
        db.flush()
    else:
        if display_name or p_data.get("nickname"):
            acc.display_name = disp
        if pass_hash:
            acc.pass_hash = pass_hash

    prof = acc.profile
    if not prof:
        prof = Profile(username=uname)
        db.add(prof)
        db.flush()

    prof.nickname = str(p_data.get("nickname") or disp or "Атлет")[:100]
    prof.status_text = str(p_data.get("status") or "Иду к своей лучшей форме 🔥")[:200]
    prof.avatar_emoji = str(p_data.get("avatarEmoji") or "⚡")[:16]
    prof.avatar_img_b64 = str(p_data.get("avatarImg") or "")
    prof.banner_img_b64 = str(p_data.get("bannerImg") or "")
    prof.frame_class = str(p_data.get("frame") or "frame-emerald")[:40]
    prof.banner_class = str(p_data.get("banner") or "banner-aurora")[:40]
    prof.nick_effect = str(p_data.get("nickEffect") or "")[:40]

    prof.goal_mode = str(g_data.get("mode") or "lose")[:20]
    prof.goal_label = str(g_data.get("label") or "Похудение (-15%)")[:60]
    prof.kcal_target = max(500, int(g_data.get("kcal") or 2000))
    prof.p_target = max(0, int(g_data.get("p") or 140))
    prof.f_target = max(0, int(g_data.get("f") or 65))
    prof.c_target = max(0, int(g_data.get("c") or 210))

    prof.theme = str(state.get("theme") or "dark")[:16]
    prof.api_key = str(state.get("apiKey") or "")
    prof.onboarded = bool(state.get("onboarded", True))
    prof.purchased_shields = max(0, int(state.get("purchasedShields") or 0))
    prof.spent_shield_xp = max(0, int(state.get("spentShieldXp") or 0))
    prof.bonus_xp = int(state.get("bonusXp") or 0)
    prof.last_seen_level = max(1, int(state.get("lastSeenLevel") or 1))

    # Пользовательские блюда
    for cp in (state.get("customProducts") or []):
        if not isinstance(cp, dict) or not cp.get("name"):
            continue
        pid = str(cp.get("id") or f"custom_{uname}_{abs(hash(cp['name'])) % 1000000}")[:64]
        existing_prod = db.query(Product).filter(Product.product_id == pid).first()
        if not existing_prod:
            db.add(Product(
                product_id=pid,
                creator_username=uname,
                name=str(cp.get("name"))[:220],
                brand=str(cp.get("brand") or "")[:120],
                category=str(cp.get("category") or "Мои блюда")[:80],
                icon=str(cp.get("icon") or "🍲")[:16],
                kcal100=max(0, int(cp.get("kcal100") or 100)),
                p100=max(0.0, float(cp.get("p100") or 0.0)),
                f100=max(0.0, float(cp.get("f100") or 0.0)),
                c100=max(0.0, float(cp.get("c100") or 0.0)),
                default_portion=max(1, int(cp.get("portion") or 100)),
                is_custom=True,
                is_liquid=bool(cp.get("isLiquid")),
            ))
        else:
            existing_prod.name = str(cp.get("name"))[:220]
            existing_prod.kcal100 = max(0, int(cp.get("kcal100") or 100))
            existing_prod.p100 = max(0.0, float(cp.get("p100") or 0.0))
            existing_prod.f100 = max(0.0, float(cp.get("f100") or 0.0))
            existing_prod.c100 = max(0.0, float(cp.get("c100") or 0.0))
            existing_prod.default_portion = max(1, int(cp.get("portion") or 100))
            existing_prod.is_liquid = bool(cp.get("isLiquid"))

    # Суточный дневник и приёмы пищи
    for d_str, d_val in (state.get("days") or {}).items():
        if not isinstance(d_val, dict):
            continue
        try:
            parsed_date = date.fromisoformat(str(d_str)[:10])
        except ValueError:
            continue

        day_row = (
            db.query(DailyLog)
            .filter(DailyLog.username == uname, DailyLog.log_date == parsed_date)
            .first()
        )
        if not day_row:
            day_row = DailyLog(username=uname, log_date=parsed_date)
            db.add(day_row)
            db.flush()

        day_row.water_ml = max(0, int(d_val.get("waterMl") or 0))
        day_row.freeze_used = bool(d_val.get("freezeUsed"))
        day_row.penalty_redeemed = bool(d_val.get("penaltyRedeemed"))
        day_row.simulated_miss = bool(d_val.get("simulatedMiss"))

        meals_in = d_val.get("meals") or []
        db.query(MealEntry).filter(MealEntry.day_id == day_row.day_id).delete()
        for m in meals_in:
            if not isinstance(m, dict):
                continue
            grams = max(1, int(m.get("grams") or 100))
            kcal = max(0, int(m.get("kcal") or 0))
            m_type = str(m.get("mealType") or "breakfast")
            if m_type not in ("breakfast", "lunch", "dinner", "snack"):
                m_type = "breakfast"
            db.add(MealEntry(
                day_id=day_row.day_id,
                product_id=m.get("productId"),
                meal_type=m_type,
                dish_name=str(m.get("name") or "Блюдо")[:220],
                grams=grams,
                kcal=kcal,
                p=max(0.0, float(m.get("p") or 0.0)),
                f=max(0.0, float(m.get("f") or 0.0)),
                c=max(0.0, float(m.get("c") or 0.0)),
                kcal100=int(m.get("kcal100") or round((kcal / grams) * 100)),
                p100=float(m.get("p100") or round((float(m.get("p") or 0.0) / grams) * 100, 1)),
                f100=float(m.get("f100") or round((float(m.get("f") or 0.0) / grams) * 100, 1)),
                c100=float(m.get("c100") or round((float(m.get("c") or 0.0) / grams) * 100, 1)),
                is_liquid=bool(m.get("isLiquid")),
                photo_b64=str(m.get("photo") or ""),
                logged_time=str(m.get("time") or "12:00")[:16],
            ))

    # Замеры веса
    for w in (state.get("weightLog") or []):
        if not isinstance(w, dict) or not w.get("date") or not w.get("kg"):
            continue
        try:
            w_date = date.fromisoformat(str(w["date"])[:10])
        except ValueError:
            continue
        kg_val = max(25.0, min(300.0, float(w["kg"])))
        w_row = (
            db.query(WeightLog)
            .filter(WeightLog.username == uname, WeightLog.measure_date == w_date)
            .first()
        )
        if w_row:
            w_row.weight_kg = kg_val
        else:
            db.add(WeightLog(username=uname, measure_date=w_date, weight_kg=kg_val))

    db.commit()
    final_state = assemble_user_state(db, uname)
    save_os_backup_user(uname, final_state)
    return final_state


@app.on_event("startup")
def on_startup():
    """Автоматическое создание 7 таблиц (3НФ), неразрушающая миграция и восстановление истории."""
    Base.metadata.create_all(bind=engine)
    ensure_non_destructive_migrations(engine)
    db = next(get_db())
    try:
        seed_database(db)
        # Автовосстановление всех пользователей из постоянного бэкапа ОС при чистом запуске
        os_backups = load_os_backup_all()
        for uname, b_state in os_backups.items():
            if isinstance(b_state, dict):
                persist_merged_state_to_db(db, uname, b_state)
    finally:
        db.close()


# ==================== HEALTH & ACCOUNTS ====================

@app.get("/api/health")
def api_health(db: Session = Depends(get_db)):
    """Проверка соединения с БД и статистика 7 таблиц."""
    return {
        "status": "ok",
        "engine": "Python FastAPI + SQLAlchemy 2.0 (3NF)",
        "tables": {
            "accounts": db.query(Account).count(),
            "profiles": db.query(Profile).count(),
            "products": db.query(Product).count(),
            "daily_logs": db.query(DailyLog).count(),
            "meal_entries": db.query(MealEntry).count(),
            "weight_logs": db.query(WeightLog).count(),
            "level_rewards": db.query(LevelReward).count(),
        },
    }


@app.get("/api/auth/accounts")
def api_list_accounts(db: Session = Depends(get_db)):
    """Список зарегистрированных аккаунтов для быстрого переключения."""
    rows = db.query(Account).filter(Account.username != "guest").order_by(Account.username.asc()).all()
    return {
        "status": "ok",
        "accounts": [
            {
                "username": r.username,
                "displayName": r.display_name,
                "registeredDate": r.registered_date.isoformat() if r.registered_date else "",
            }
            for r in rows
        ],
    }


@app.post("/api/auth/register")
def api_register(req: AuthRegisterRequest, db: Session = Depends(get_db)):
    """Регистрация или обновление профиля пользователя с сохранением истории."""
    uname = req.username.strip().lower()
    disp = (req.displayName or req.display_name or uname).strip()
    p_hash = req.passHash or (hash_password(req.password) if req.password else "sha256_synced")

    init_state = req.state or {
        "profile": {"nickname": disp},
        "goals": {"kcal": 2000, "p": 140, "f": 65, "c": 210, "mode": "lose", "label": "Похудение (-15%)"},
        "days": {},
        "weightLog": [],
        "customProducts": [],
        "onboarded": True,
    }
    saved = persist_merged_state_to_db(db, uname, init_state, pass_hash=p_hash, display_name=disp)
    return {
        "status": "ok",
        "username": uname,
        "displayName": disp,
        "state": saved,
    }


@app.post("/api/auth/login")
def api_login(req: AuthLoginRequest, db: Session = Depends(get_db)):
    """Вход пользователя и загрузка всей сохранённой истории."""
    uname = req.username.strip().lower()
    acc = db.query(Account).filter(Account.username == uname).first()
    if not acc:
        # Проверяем, есть ли пользователь в постоянном бэкапе ОС
        os_backups = load_os_backup_all()
        if uname in os_backups:
            persist_merged_state_to_db(db, uname, os_backups[uname])
            acc = db.query(Account).filter(Account.username == uname).first()
    if not acc:
        raise HTTPException(status_code=404, detail=f"Аккаунт @{uname} не найден")

    p_hash = req.passHash or (hash_password(req.password) if req.password else "")
    if acc.pass_hash and acc.pass_hash not in ("sha256_synced", "guest_no_pass") and p_hash and acc.pass_hash != p_hash:
        raise HTTPException(status_code=401, detail="Неверный пароль")

    return {
        "status": "ok",
        "username": uname,
        "displayName": acc.display_name,
        "state": assemble_user_state(db, uname),
    }


@app.get("/api/users/{username}/state")
def api_get_user_state(username: str, db: Session = Depends(get_db)):
    """Чтение полного состояния пользователя из 7 таблиц БД."""
    uname = username.strip().lower()
    return {"status": "ok", "username": uname, "state": assemble_user_state(db, uname)}


@app.put("/api/users/{username}/state")
def api_sync_user_state(username: str, payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    """Неразрушающая синхронизация состояния пользователя с сохранением истории записей."""
    uname = username.strip().lower()
    saved = persist_merged_state_to_db(db, uname, payload)
    return {
        "status": "synced",
        "username": uname,
        "updatedAt": datetime.utcnow().isoformat(),
        "state": saved,
    }


@app.get("/api/products")
def api_search_products(
    q: str = Query(default="", description="Поисковый запрос по названию или категории"),
    limit: int = Query(default=45, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Поиск продуктов в таблице products."""
    query = db.query(Product)
    if q.strip():
        pattern = f"%{q.strip().lower()}%"
        query = query.filter(
            func.lower(Product.name).like(pattern) | func.lower(Product.category).like(pattern)
        )
    rows = query.order_by(Product.is_custom.desc(), Product.product_id.asc()).limit(limit).all()
    return [
        {
            "id": p.product_id,
            "name": p.name,
            "brand": p.brand,
            "category": p.category,
            "icon": p.icon,
            "kcal100": p.kcal100,
            "p100": float(p.p100),
            "f100": float(p.f100),
            "c100": float(p.c100),
            "portion": p.default_portion,
            "custom": p.is_custom,
            "isLiquid": bool(getattr(p, "is_liquid", False)),
        }
        for p in rows
    ]


@app.get("/api/calc-norms")
def api_calculate_norms(
    gender: str = "m",
    age: int = 24,
    height_cm: float = 178.0,
    weight_kg: float = 75.0,
    activity: float = 1.375,
    goal_mode: str = "lose",
):
    """Расчёт норм КБЖУ на стороне Python-сервера по формуле Миффлина — Сан-Жеора."""
    return calculate_mifflin_st_jeor(gender, age, height_cm, weight_kg, activity, goal_mode)


FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def serve_index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    @app.get("/index.html")
    def serve_index_explicit():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    @app.get("/schema")
    def serve_schema():
        schema_file = os.path.join(FRONTEND_DIR, "chepoel_db_schema.html")
        if os.path.exists(schema_file):
            return FileResponse(schema_file)
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
