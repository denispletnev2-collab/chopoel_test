# -*- coding: utf-8 -*-
"""
Подключение к СУБД PostgreSQL / SQLite через SQLAlchemy 2.0
с автоматической неразрушающей миграцией колонок (без потери истории записей).
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_SQLITE_URL = f"sqlite:///{(DATA_DIR / 'chepoel.db').as_posix()}"

DATABASE_URL = os.getenv("DATABASE_URL", "")

def _build_engine():
    if DATABASE_URL:
        try:
            eng = create_engine(DATABASE_URL, pool_pre_ping=True)
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            return eng
        except Exception as e:
            print(f"[ЧёПоел DB] PostgreSQL недоступен ({e}), включён локальный SQLite движок (data/chepoel.db)")
    return create_engine(
        DEFAULT_SQLITE_URL,
        connect_args={"check_same_thread": False},
    )

engine = _build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_non_destructive_migrations(eng):
    """Добавляет новые колонки v6 в существующие таблицы без удаления истории."""
    try:
        insp = inspect(eng)
        existing_tables = set(insp.get_table_names())
        migrations = {
            "profiles": [
                ("api_key", "TEXT DEFAULT ''"),
                ("purchased_shields", "INTEGER NOT NULL DEFAULT 0"),
                ("spent_shield_xp", "INTEGER NOT NULL DEFAULT 0"),
                ("bonus_xp", "INTEGER NOT NULL DEFAULT 0"),
                ("last_seen_level", "INTEGER NOT NULL DEFAULT 1"),
                ("theme", "VARCHAR(16) DEFAULT 'dark'"),
                ("onboarded", "BOOLEAN DEFAULT TRUE"),
                ("nick_effect", "VARCHAR(40) DEFAULT ''"),
                ("avatar_img_b64", "TEXT DEFAULT ''"),
                ("banner_img_b64", "TEXT DEFAULT ''"),
            ],
            "products": [
                ("is_liquid", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ],
            "daily_logs": [
                ("freeze_used", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("penalty_redeemed", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("simulated_miss", "BOOLEAN NOT NULL DEFAULT FALSE"),
            ],
            "meal_entries": [
                ("is_liquid", "BOOLEAN NOT NULL DEFAULT FALSE"),
                ("photo_b64", "TEXT DEFAULT ''"),
                ("logged_time", "VARCHAR(16) DEFAULT '12:00'"),
            ],
        }
        with eng.begin() as conn:
            for tbl, cols in migrations.items():
                if tbl not in existing_tables:
                    continue
                cur_cols = {c["name"] for c in insp.get_columns(tbl)}
                for col_name, col_def in cols:
                    if col_name not in cur_cols:
                        conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_def}"))
    except Exception as e:
        print(f"[ЧёПоел DB] Предупреждение миграции: {e}")


def get_db():
    """Генератор сессии БД для зависимостей FastAPI (Depends)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
