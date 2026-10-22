# -*- coding: utf-8 -*-
"""Скрипт первичного заполнения PostgreSQL каталогом из 615 продуктов РФ и наград уровней."""

import json
import os
from sqlalchemy.orm import Session
from .models import Product, LevelReward

DEFAULT_REWARDS = [
    (1,  "🌱 Стартовый набор (База)",         "3 базовые расцветки профиля и 3 базовые рамки аватара.",                                   "banner-aurora",  "frame-emerald", ""),
    (5,  "⚡ Кибер-Следопыт (Тир 1)",         "Неоновая расцветка Synthwave Cyber Grid, рамка Cyberpunk Neon и неоновый ник.",            "banner-cyber",   "frame-cyber",   "nick-cyber"),
    (10, "💜 Адепт Дисциплины (Тир 2)",       "Космическая расцветка Galactic Nitro Nebula, рамка Nitro Plasma и свечение ника Nitro.",   "banner-nebula",  "frame-discord", "nick-nitro"),
    (15, "🔥 Машина Режима (Тир 3)",          "Огненная расцветка Crimson Inferno, пульсирующая рамка Hellfire Blaze и пламенный ник.",   "banner-tokyo",   "frame-fire",    "nick-fire"),
    (20, "👑 Повелитель Калорий (Тир 4)",     "Королевская расцветка Golden Imperial, золотая рамка Dragon Lore Gold и золотой никнейм.", "banner-gold",    "frame-gold",    "nick-gold"),
    (25, "🌌 Архитектор Формы (Тир 5)",       "Живой анимированный баннер Quantum Matrix, плазменная рамка Quantum Singularity.",         "banner-quantum", "frame-quantum", "nick-quantum"),
    (30, "💎 Легенда ЧёПоел (Godlike Тир 6)", "Полноцветный RGB-баннер Chroma Godlike, радужная рамка 360° и легендарный перелив ника.",  "banner-chroma",  "frame-chroma",  "nick-chroma"),
]


def seed_database(db: Session) -> dict:
    """Заполняет таблицы level_rewards и products (615 продуктов РФ), если они пусты."""
    existing_rewards = db.query(LevelReward).count()
    if existing_rewards == 0:
        for lvl, title, desc, banner, frame, nick in DEFAULT_REWARDS:
            db.add(LevelReward(
                reward_lvl=lvl,
                title=title,
                description=desc,
                banner_class=banner,
                frame_class=frame,
                nick_effect=nick,
            ))
        db.commit()

    existing_products = db.query(Product).filter(Product.is_custom == False).count()  # noqa: E712
    inserted_products = 0
    if existing_products == 0:
        json_path = os.path.join(os.path.dirname(__file__), "data", "ru-products.json")
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                items = json.load(f)
            for idx, item in enumerate(items):
                pid = str(item.get("id") or f"ru_{idx + 1}")
                per = item.get("per100g") or {}
                db.add(Product(
                    product_id=pid,
                    creator_username=None,
                    name=str(item.get("name") or "Продукт"),
                    brand=str(item.get("brand") or ""),
                    category=str(item.get("category") or "Готовая еда"),
                    icon=str(item.get("icon") or "🍲"),
                    kcal100=int(item.get("kcal100") if item.get("kcal100") is not None else per.get("cal", 0)),
                    p100=float(item.get("p100") if item.get("p100") is not None else per.get("p", 0.0)),
                    f100=float(item.get("f100") if item.get("f100") is not None else per.get("f", 0.0)),
                    c100=float(item.get("c100") if item.get("c100") is not None else per.get("c", 0.0)),
                    default_portion=int(item.get("portion") or item.get("defaultGrams") or 100),
                    barcode=str(item.get("barcode") or ""),
                    is_custom=False,
                ))
                inserted_products += 1
            db.commit()

    return {
        "rewards_count": db.query(LevelReward).count(),
        "products_count": db.query(Product).count(),
        "newly_seeded_products": inserted_products,
    }
