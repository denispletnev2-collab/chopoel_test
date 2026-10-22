# -*- coding: utf-8 -*-
"""Реляционные ORM-модели SQLAlchemy 2.0 (7 таблиц в 3НФ для PostgreSQL / SQLite)."""

from datetime import date, datetime
from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime,
    ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship
from .database import Base


class Account(Base):
    """1. Таблица учётных записей пользователей (accounts)."""
    __tablename__ = "accounts"

    username = Column(String(50), primary_key=True, index=True)
    display_name = Column(String(100), nullable=False, default="Атлет")
    pass_hash = Column(String(128), nullable=False, default="sha256_synced")
    registered_date = Column(Date, nullable=False, default=date.today)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    profile = relationship("Profile", back_populates="account", uselist=False, cascade="all, delete-orphan")
    daily_logs = relationship("DailyLog", back_populates="account", cascade="all, delete-orphan")
    weight_logs = relationship("WeightLog", back_populates="account", cascade="all, delete-orphan")
    custom_products = relationship("Product", back_populates="creator")


class LevelReward(Base):
    """2. Справочник наград за уровни каждые 5 LVL (level_rewards)."""
    __tablename__ = "level_rewards"

    reward_lvl = Column(Integer, primary_key=True)
    title = Column(String(100), nullable=False)
    description = Column(Text, nullable=False, default="")
    banner_class = Column(String(40), nullable=False)
    frame_class = Column(String(40), nullable=False)
    nick_effect = Column(String(40), nullable=False, default="")


class Profile(Base):
    """3. Персональный профиль, цели КБЖУ и прогресс геймификации (profiles)."""
    __tablename__ = "profiles"

    profile_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), ForeignKey("accounts.username", ondelete="CASCADE"), unique=True, nullable=False)
    nickname = Column(String(100), nullable=False, default="Атлет")
    status_text = Column(String(200), nullable=False, default="Иду к своей лучшей форме 🔥")
    avatar_emoji = Column(String(16), nullable=False, default="⚡")
    avatar_img_b64 = Column(Text, default="")
    banner_img_b64 = Column(Text, default="")
    frame_class = Column(String(40), nullable=False, default="frame-emerald")
    banner_class = Column(String(40), nullable=False, default="banner-aurora")
    nick_effect = Column(String(40), nullable=False, default="")
    goal_mode = Column(String(20), nullable=False, default="lose")
    goal_label = Column(String(60), nullable=False, default="Похудение (-15%)")
    kcal_target = Column(Integer, nullable=False, default=2000)
    p_target = Column(Integer, nullable=False, default=140)
    f_target = Column(Integer, nullable=False, default=65)
    c_target = Column(Integer, nullable=False, default=210)
    bonus_xp = Column(Integer, nullable=False, default=0)
    purchased_shields = Column(Integer, nullable=False, default=0)
    spent_shield_xp = Column(Integer, nullable=False, default=0)
    last_seen_level = Column(Integer, nullable=False, default=1)
    theme = Column(String(16), nullable=False, default="dark")
    api_key = Column(Text, default="")
    onboarded = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account", back_populates="profile")


class Product(Base):
    """4. Каталог продуктов РФ (620+ позиций) и пользовательских блюд (products)."""
    __tablename__ = "products"

    product_id = Column(String(64), primary_key=True)
    creator_username = Column(String(50), ForeignKey("accounts.username", ondelete="SET NULL"), nullable=True)
    name = Column(String(220), nullable=False, index=True)
    brand = Column(String(120), nullable=False, default="")
    category = Column(String(80), nullable=False, default="Готовая еда", index=True)
    icon = Column(String(16), nullable=False, default="🍲")
    kcal100 = Column(Integer, nullable=False, default=0)
    p100 = Column(Numeric(6, 1), nullable=False, default=0.0)
    f100 = Column(Numeric(6, 1), nullable=False, default=0.0)
    c100 = Column(Numeric(6, 1), nullable=False, default=0.0)
    default_portion = Column(Integer, nullable=False, default=100)
    barcode = Column(String(32), default="")
    is_custom = Column(Boolean, nullable=False, default=False)
    is_liquid = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    creator = relationship("Account", back_populates="custom_products")
    meal_entries = relationship("MealEntry", back_populates="product")


class DailyLog(Base):
    """5. Суточный дневник питания и дисциплины (daily_logs)."""
    __tablename__ = "daily_logs"
    __table_args__ = (
        UniqueConstraint("username", "log_date", name="uq_daily_logs_user_date"),
    )

    day_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), ForeignKey("accounts.username", ondelete="CASCADE"), nullable=False, index=True)
    log_date = Column(Date, nullable=False, index=True)
    water_ml = Column(Integer, nullable=False, default=0)
    freeze_used = Column(Boolean, nullable=False, default=False)
    penalty_redeemed = Column(Boolean, nullable=False, default=False)
    simulated_miss = Column(Boolean, nullable=False, default=False)

    account = relationship("Account", back_populates="daily_logs")
    meals = relationship("MealEntry", back_populates="daily_log", cascade="all, delete-orphan", order_by="MealEntry.meal_id")


class MealEntry(Base):
    """6. Записи приёмов пищи за конкретный день (meal_entries)."""
    __tablename__ = "meal_entries"

    meal_id = Column(Integer, primary_key=True, autoincrement=True)
    day_id = Column(Integer, ForeignKey("daily_logs.day_id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(String(64), ForeignKey("products.product_id", ondelete="SET NULL"), nullable=True)
    meal_type = Column(String(20), nullable=False, default="breakfast")
    dish_name = Column(String(220), nullable=False)
    grams = Column(Integer, nullable=False, default=100)
    kcal = Column(Integer, nullable=False, default=0)
    p = Column(Numeric(6, 1), nullable=False, default=0.0)
    f = Column(Numeric(6, 1), nullable=False, default=0.0)
    c = Column(Numeric(6, 1), nullable=False, default=0.0)
    kcal100 = Column(Integer, nullable=False, default=0)
    p100 = Column(Numeric(6, 1), nullable=False, default=0.0)
    f100 = Column(Numeric(6, 1), nullable=False, default=0.0)
    c100 = Column(Numeric(6, 1), nullable=False, default=0.0)
    is_liquid = Column(Boolean, nullable=False, default=False)
    photo_b64 = Column(Text, default="")
    logged_time = Column(String(16), nullable=False, default="12:00")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    daily_log = relationship("DailyLog", back_populates="meals")
    product = relationship("Product", back_populates="meal_entries")


class WeightLog(Base):
    """7. История замеров веса тела пользователя (weight_logs)."""
    __tablename__ = "weight_logs"
    __table_args__ = (
        UniqueConstraint("username", "measure_date", name="uq_weight_logs_user_date"),
        CheckConstraint("weight_kg BETWEEN 25 AND 300", name="chk_weight_kg_range"),
    )

    weight_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), ForeignKey("accounts.username", ondelete="CASCADE"), nullable=False, index=True)
    measure_date = Column(Date, nullable=False)
    weight_kg = Column(Numeric(5, 1), nullable=False)

    account = relationship("Account", back_populates="weight_logs")
