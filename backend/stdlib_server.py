#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ЧёПоел — Встроенный локальный сервер и реляционная СУБД (7 таблиц в 3НФ).
Работает мгновенно на стандартной библиотеке Python (sqlite3 + ThreadingHTTPServer)
без необходимости устанавливать внешние пакеты или настраивать подключения вручную.
"""

import json
import mimetypes
import os
import re
import sqlite3
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    from .history_sync import merge_states_non_destructive, save_user_backup_snapshot, load_user_backup_snapshot, get_all_backup_accounts
except ImportError:
    from history_sync import merge_states_non_destructive, save_user_backup_snapshot, load_user_backup_snapshot, get_all_backup_accounts

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE_PATH = DATA_DIR / "chepoel.db"


def get_db_conn() -> sqlite3.Connection:
    if os.name == "nt":
        conn = sqlite3.connect(str(DB_FILE_PATH), timeout=15.0, check_same_thread=False, isolation_level=None)
    else:
        conn = sqlite3.connect(f"file:{DB_FILE_PATH.as_posix()}?nolock=1", uri=True, timeout=15.0, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = OFF;")
    conn.execute("PRAGMA synchronous = OFF;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA locking_mode = EXCLUSIVE;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn



def ensure_schema_migrations(cur):
    """Безопасная миграция схемы БД при обновлении поверх предыдущей версии (без потери данных)."""
    def get_cols(table_name):
        cur.execute(f"PRAGMA table_info({table_name})")
        return {row[1] for row in cur.fetchall()}

    prof_cols = get_cols("profiles")
    for col_name, col_def in [
        ("api_key", "TEXT DEFAULT ''"),
        ("purchased_shields", "INTEGER NOT NULL DEFAULT 0"),
        ("spent_shield_xp", "INTEGER NOT NULL DEFAULT 0"),
        ("bonus_xp", "INTEGER NOT NULL DEFAULT 0"),
        ("last_seen_level", "INTEGER NOT NULL DEFAULT 1"),
        ("theme", "TEXT DEFAULT 'dark'"),
        ("onboarded", "INTEGER NOT NULL DEFAULT 0"),
        ("nick_effect", "TEXT DEFAULT ''"),
        ("avatar_img_b64", "TEXT DEFAULT ''"),
        ("banner_img_b64", "TEXT DEFAULT ''"),
    ]:
        if col_name not in prof_cols:
            cur.execute(f"ALTER TABLE profiles ADD COLUMN {col_name} {col_def}")

    prod_cols = get_cols("products")
    if "is_liquid" not in prod_cols:
        cur.execute("ALTER TABLE products ADD COLUMN is_liquid INTEGER NOT NULL DEFAULT 0")

    day_cols = get_cols("daily_logs")
    for col_name, col_def in [
        ("freeze_used", "INTEGER NOT NULL DEFAULT 0"),
        ("penalty_redeemed", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        if col_name not in day_cols:
            cur.execute(f"ALTER TABLE daily_logs ADD COLUMN {col_name} {col_def}")

    meal_cols = get_cols("meal_entries")
    for col_name, col_def in [
        ("is_liquid", "INTEGER NOT NULL DEFAULT 0"),
        ("photo_b64", "TEXT DEFAULT ''"),
        ("logged_time", "TEXT NOT NULL DEFAULT '12:00'"),
    ]:
        if col_name not in meal_cols:
            cur.execute(f"ALTER TABLE meal_entries ADD COLUMN {col_name} {col_def}")


def init_db_and_seed():
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            username        TEXT PRIMARY KEY,
            display_name    TEXT NOT NULL DEFAULT 'Атлет',
            pass_hash       TEXT NOT NULL DEFAULT 'guest_no_pass',
            registered_date TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS level_rewards (
            reward_lvl      INTEGER PRIMARY KEY,
            title           TEXT NOT NULL,
            banner_class    TEXT NOT NULL,
            frame_class     TEXT NOT NULL,
            nick_effect     TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS profiles (
            profile_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            username          TEXT NOT NULL UNIQUE REFERENCES accounts(username) ON DELETE CASCADE,
            nickname          TEXT NOT NULL DEFAULT 'Атлет',
            status_text       TEXT DEFAULT 'Иду к своей лучшей форме 🔥',
            avatar_emoji      TEXT DEFAULT '⚡',
            avatar_img_b64    TEXT DEFAULT '',
            banner_img_b64    TEXT DEFAULT '',
            frame_class       TEXT DEFAULT 'frame-emerald',
            banner_class      TEXT DEFAULT 'banner-aurora',
            nick_effect       TEXT DEFAULT '',
            goal_mode         TEXT NOT NULL DEFAULT 'lose',
            goal_label        TEXT DEFAULT 'Похудение (-15%)',
            kcal_target       INTEGER NOT NULL DEFAULT 2000,
            p_target          INTEGER NOT NULL DEFAULT 140,
            f_target          INTEGER NOT NULL DEFAULT 65,
            c_target          INTEGER NOT NULL DEFAULT 210,
            bonus_xp          INTEGER NOT NULL DEFAULT 0,
            purchased_shields INTEGER NOT NULL DEFAULT 0,
            spent_shield_xp   INTEGER NOT NULL DEFAULT 0,
            last_seen_level   INTEGER NOT NULL DEFAULT 1,
            theme             TEXT DEFAULT 'dark',
            api_key           TEXT DEFAULT '',
            onboarded         INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS products (
            product_id       TEXT PRIMARY KEY,
            creator_username TEXT REFERENCES accounts(username) ON DELETE SET NULL,
            name             TEXT NOT NULL,
            brand            TEXT DEFAULT '',
            category         TEXT NOT NULL DEFAULT 'Готовая еда',
            kcal100          INTEGER NOT NULL DEFAULT 100,
            p100             REAL NOT NULL DEFAULT 0,
            f100             REAL NOT NULL DEFAULT 0,
            c100             REAL NOT NULL DEFAULT 0,
            default_portion  INTEGER NOT NULL DEFAULT 100,
            barcode          TEXT DEFAULT '',
            is_custom        INTEGER NOT NULL DEFAULT 0,
            is_liquid        INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS daily_logs (
            day_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username         TEXT NOT NULL REFERENCES accounts(username) ON DELETE CASCADE,
            log_date         TEXT NOT NULL,
            water_ml         INTEGER NOT NULL DEFAULT 0,
            freeze_used      INTEGER NOT NULL DEFAULT 0,
            penalty_redeemed INTEGER NOT NULL DEFAULT 0,
            UNIQUE (username, log_date)
        );

        CREATE TABLE IF NOT EXISTS meal_entries (
            meal_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            day_id           INTEGER NOT NULL REFERENCES daily_logs(day_id) ON DELETE CASCADE,
            product_id       TEXT REFERENCES products(product_id) ON DELETE SET NULL,
            meal_type        TEXT NOT NULL DEFAULT 'breakfast',
            dish_name        TEXT NOT NULL,
            grams            INTEGER NOT NULL DEFAULT 100,
            kcal             INTEGER NOT NULL DEFAULT 0,
            p                REAL NOT NULL DEFAULT 0,
            f                REAL NOT NULL DEFAULT 0,
            c                REAL NOT NULL DEFAULT 0,
            is_liquid        INTEGER NOT NULL DEFAULT 0,
            photo_b64        TEXT DEFAULT '',
            logged_time      TEXT NOT NULL DEFAULT '12:00'
        );

        CREATE TABLE IF NOT EXISTS weight_logs (
            weight_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            username         TEXT NOT NULL REFERENCES accounts(username) ON DELETE CASCADE,
            measure_date     TEXT NOT NULL,
            weight_kg        REAL NOT NULL,
            UNIQUE (username, measure_date)
        );
        """)

        ensure_schema_migrations(cur)

        # 1. Награды за уровни
        cur.execute("SELECT COUNT(*) FROM level_rewards")
        if cur.fetchone()[0] == 0:
            rewards = [
                (1,  "Стартовый набор (База)",         "banner-aurora",  "frame-emerald", ""),
                (5,  "Кибер-Следопыт (Тир 1)",         "banner-cyber",   "frame-cyber",   "nick-cyber"),
                (10, "Адепт Дисциплины (Тир 2)",       "banner-nebula",  "frame-discord", "nick-nitro"),
                (15, "Машина Режима (Тир 3)",          "banner-tokyo",   "frame-fire",    "nick-fire"),
                (20, "Повелитель Калорий (Тир 4)",     "banner-gold",    "frame-gold",    "nick-gold"),
                (25, "Архитектор Формы (Тир 5)",       "banner-quantum", "frame-quantum", "nick-quantum"),
                (30, "Легенда ЧёПоел (Godlike Тир 6)", "banner-chroma",  "frame-chroma",  "nick-chroma"),
            ]
            cur.executemany(
                "INSERT INTO level_rewards (reward_lvl, title, banner_class, frame_class, nick_effect) VALUES (?, ?, ?, ?, ?)",
                rewards
            )

        # 2. Каталог 615+ продуктов РФ
        cur.execute("SELECT COUNT(*) FROM products WHERE is_custom = 0")
        if cur.fetchone()[0] == 0:
            json_path = os.path.join(FRONTEND_DIR, "assets", "data", "ru-products.json")
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    items = json.load(f)
                batch = []
                for idx, item in enumerate(items):
                    pid = item.get("id") or f"ru_{idx+1}"
                    per = item.get("per100g") or {}
                    batch.append((
                        pid,
                        None,
                        str(item.get("name", "Продукт"))[:200],
                        str(item.get("brand", ""))[:100],
                        str(item.get("category", "Готовая еда"))[:60],
                        int(item.get("kcal100", per.get("cal", 100))),
                        float(item.get("p100", per.get("p", 0))),
                        float(item.get("f100", per.get("f", 0))),
                        float(item.get("c100", per.get("c", 0))),
                        int(item.get("portion", item.get("defaultGrams", 100))),
                        str(item.get("barcode", ""))[:32],
                        0,
                        1 if item.get("isLiquid") else 0
                    ))
                cur.executemany(
                    """INSERT OR IGNORE INTO products
                       (product_id, creator_username, name, brand, category, kcal100, p100, f100, c100, default_portion, barcode, is_custom, is_liquid)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    batch
                )
        conn.commit()
        # Автовосстановление истории записей из системного бэкапа пользователя (~/.chepoel)
        backup_accs = get_all_backup_accounts()
        for b_uname, b_entry in backup_accs.items():
            if not isinstance(b_entry, dict) or not b_entry.get("state"):
                continue
            save_user_state(
                conn,
                b_uname,
                b_entry["state"],
                pass_hash=b_entry.get("passHash") or None,
                display_name=b_entry.get("displayName") or None,
            )
        conn.commit()
    finally:
        conn.close()


def get_health_dict():
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        tables = {}
        for t in ("accounts", "profiles", "products", "daily_logs", "meal_entries", "weight_logs", "level_rewards"):
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            tables[t] = cur.fetchone()[0]
        return {"status": "ok", "tables": tables}
    finally:
        conn.close()


def build_user_state(conn, uname: str):
    cur = conn.cursor()
    cur.execute("SELECT * FROM accounts WHERE username = ?", (uname,))
    acc = cur.fetchone()
    cur.execute("SELECT * FROM profiles WHERE username = ?", (uname,))
    prof = cur.fetchone()
    if not acc or not prof:
        return None

    days_dict = {}
    cur.execute("SELECT * FROM daily_logs WHERE username = ?", (uname,))
    for d in cur.fetchall():
        cur.execute("SELECT * FROM meal_entries WHERE day_id = ? ORDER BY meal_id ASC", (d["day_id"],))
        meals = [
            {
                "name": m["dish_name"],
                "mealType": m["meal_type"],
                "grams": m["grams"],
                "kcal": m["kcal"],
                "p": float(m["p"]),
                "f": float(m["f"]),
                "c": float(m["c"]),
                "isLiquid": bool(m["is_liquid"]),
                "liquidMl": m["grams"] if m["is_liquid"] else 0,
                "photo": m["photo_b64"] or "",
                "time": m["logged_time"]
            }
            for m in cur.fetchall()
        ]
        days_dict[d["log_date"]] = {
            "waterMl": d["water_ml"],
            "freezeUsed": bool(d["freeze_used"]),
            "penaltyRedeemed": bool(d["penalty_redeemed"]),
            "meals": meals
        }

    cur.execute("SELECT * FROM weight_logs WHERE username = ? ORDER BY measure_date ASC", (uname,))
    weight_list = [{"date": w["measure_date"], "kg": float(w["weight_kg"])} for w in cur.fetchall()]

    cur.execute("SELECT * FROM products WHERE creator_username = ? AND is_custom = 1", (uname,))
    custom_products = [
        {
            "id": cp["product_id"],
            "name": cp["name"],
            "category": cp["category"],
            "kcal100": cp["kcal100"],
            "p100": float(cp["p100"]),
            "f100": float(cp["f100"]),
            "c100": float(cp["c100"]),
            "portion": cp["default_portion"],
            "custom": True,
            "isLiquid": bool(cp["is_liquid"])
        }
        for cp in cur.fetchall()
    ]

    return {
        "goals": {
            "kcal": prof["kcal_target"],
            "p": prof["p_target"],
            "f": prof["f_target"],
            "c": prof["c_target"],
            "mode": prof["goal_mode"],
            "label": prof["goal_label"] or "Похудение (-15%)"
        },
        "profile": {
            "nickname": prof["nickname"],
            "status": prof["status_text"],
            "avatarEmoji": prof["avatar_emoji"],
            "avatarImg": prof["avatar_img_b64"] or "",
            "bannerImg": prof["banner_img_b64"] or "",
            "frame": prof["frame_class"],
            "banner": prof["banner_class"],
            "nickEffect": prof["nick_effect"] or ""
        },
        "days": days_dict,
        "weightLog": weight_list,
        "customProducts": custom_products,
        "registeredDate": acc["registered_date"],
        "purchasedShields": prof["purchased_shields"],
        "spentShieldXp": prof["spent_shield_xp"],
        "bonusXp": prof["bonus_xp"],
        "lastSeenLevel": prof["last_seen_level"],
        "apiKey": prof["api_key"] if "api_key" in prof.keys() else "",
        "theme": prof["theme"] or "dark",
        "onboarded": bool(prof["onboarded"])
    }


def save_user_state(conn, uname: str, state: dict, pass_hash: str = None, display_name: str = None):
    existing_st = build_user_state(conn, uname) or load_user_backup_snapshot(uname)
    if existing_st:
        state = merge_states_non_destructive(existing_st, state)
    cur = conn.cursor()
    prof_data = state.get("profile") or {}
    goals_data = state.get("goals") or {}
    reg_date = str(state.get("registeredDate") or date.today().isoformat())[:16]
    disp = str(display_name or prof_data.get("nickname") or uname)[:100]

    cur.execute("SELECT username, display_name, pass_hash FROM accounts WHERE username = ?", (uname,))
    acc = cur.fetchone()
    if not acc:
        cur.execute(
            "INSERT INTO accounts (username, display_name, pass_hash, registered_date) VALUES (?, ?, ?, ?)",
            (uname, disp, pass_hash or "sha256_synced", reg_date)
        )
    else:
        new_disp = disp if (display_name or prof_data.get("nickname")) else acc["display_name"]
        new_hash = pass_hash if pass_hash else acc["pass_hash"]
        cur.execute(
            "UPDATE accounts SET display_name = ?, pass_hash = ?, registered_date = ? WHERE username = ?",
            (new_disp, new_hash, reg_date, uname)
        )

    cur.execute("SELECT profile_id FROM profiles WHERE username = ?", (uname,))
    if not cur.fetchone():
        cur.execute("INSERT INTO profiles (username) VALUES (?)", (uname,))

    cur.execute(
        """UPDATE profiles SET
           nickname = ?, status_text = ?, avatar_emoji = ?, avatar_img_b64 = ?, banner_img_b64 = ?,
           frame_class = ?, banner_class = ?, nick_effect = ?,
           goal_mode = ?, goal_label = ?, kcal_target = ?, p_target = ?, f_target = ?, c_target = ?,
           purchased_shields = ?, spent_shield_xp = ?, bonus_xp = ?, last_seen_level = ?,
           theme = ?, api_key = ?, onboarded = ?
           WHERE username = ?""",
        (
            str(prof_data.get("nickname") or display_name or "Атлет")[:100],
            str(prof_data.get("status") or "")[:200],
            str(prof_data.get("avatarEmoji") or "⚡")[:16],
            str(prof_data.get("avatarImg") or ""),
            str(prof_data.get("bannerImg") or ""),
            str(prof_data.get("frame") or "frame-emerald")[:40],
            str(prof_data.get("banner") or "banner-aurora")[:40],
            str(prof_data.get("nickEffect") or "")[:40],
            str(goals_data.get("mode") or "lose")[:20],
            str(goals_data.get("label") or "Похудение")[:60],
            int(goals_data.get("kcal") or 2000),
            int(goals_data.get("p") or 140),
            int(goals_data.get("f") or 65),
            int(goals_data.get("c") or 210),
            int(state.get("purchasedShields") or 0),
            int(state.get("spentShieldXp") or 0),
            int(state.get("bonusXp") or 0),
            int(state.get("lastSeenLevel") or 1),
            str(state.get("theme") or "dark")[:16],
            str(state.get("apiKey") or "")[:256],
            1 if state.get("onboarded", True) else 0,
            uname
        )
    )

    for cp in (state.get("customProducts") or []):
        pid = str(cp.get("id") or f"custom_{uname}")[:64]
        cur.execute(
            """INSERT INTO products
               (product_id, creator_username, name, category, kcal100, p100, f100, c100, default_portion, is_custom, is_liquid)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(product_id) DO UPDATE SET
               creator_username=excluded.creator_username, name=excluded.name, category=excluded.category,
               kcal100=excluded.kcal100, p100=excluded.p100, f100=excluded.f100, c100=excluded.c100,
               default_portion=excluded.default_portion, is_custom=1, is_liquid=excluded.is_liquid""",
            (
                pid, uname, str(cp.get("name") or "Моё блюдо")[:200],
                str(cp.get("category") or "Мои блюда")[:60],
                int(cp.get("kcal100") or 100), float(cp.get("p100") or 0),
                float(cp.get("f100") or 0), float(cp.get("c100") or 0),
                int(cp.get("portion") or 100), 1 if cp.get("isLiquid") else 0
            )
        )

    days_map = state.get("days") or {}
    for d_str, d_val in days_map.items():
        if not isinstance(d_val, dict):
            continue
        cur.execute(
            """INSERT INTO daily_logs (username, log_date, water_ml, freeze_used, penalty_redeemed)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(username, log_date) DO UPDATE SET
               water_ml=excluded.water_ml, freeze_used=excluded.freeze_used, penalty_redeemed=excluded.penalty_redeemed""",
            (
                uname, d_str, int(d_val.get("waterMl") or 0),
                1 if d_val.get("freezeUsed") else 0,
                1 if d_val.get("penaltyRedeemed") else 0
            )
        )
        cur.execute("SELECT day_id FROM daily_logs WHERE username = ? AND log_date = ?", (uname, d_str))
        day_id = cur.fetchone()["day_id"]
        cur.execute("DELETE FROM meal_entries WHERE day_id = ?", (day_id,))
        for m in (d_val.get("meals") or []):
            cur.execute(
                """INSERT INTO meal_entries
                   (day_id, meal_type, dish_name, grams, kcal, p, f, c, is_liquid, photo_b64, logged_time)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    day_id,
                    str(m.get("mealType") or "breakfast")[:20],
                    str(m.get("name") or "Блюдо")[:200],
                    max(1, int(m.get("grams") or 100)),
                    int(m.get("kcal") or 0),
                    float(m.get("p") or 0),
                    float(m.get("f") or 0),
                    float(m.get("c") or 0),
                    1 if m.get("isLiquid") else 0,
                    str(m.get("photo") or ""),
                    str(m.get("time") or "12:00")[:16]
                )
            )

    for w in (state.get("weightLog") or []):
        m_date = str(w.get("date") or "")[:16]
        kg_val = float(w.get("kg") or 0)
        if not m_date or kg_val < 30 or kg_val > 250:
            continue
        cur.execute(
            """INSERT INTO weight_logs (username, measure_date, weight_kg)
               VALUES (?, ?, ?)
               ON CONFLICT(username, measure_date) DO UPDATE SET weight_kg=excluded.weight_kg""",
            (uname, m_date, kg_val)
        )


class ChePoelRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, status_code: int, payload: dict):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            return self._send_json(200, get_health_dict())

        if path == "/api/auth/accounts":
            conn = get_db_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT username, display_name, registered_date FROM accounts WHERE username != 'guest' ORDER BY username ASC")
                accs = [{"username": r["username"], "displayName": r["display_name"], "registeredDate": r["registered_date"]} for r in cur.fetchall()]
                return self._send_json(200, {"status": "ok", "accounts": accs})
            finally:
                conn.close()

        m_user = re.match(r"^/api/users/([^/]+)/state$", path)
        if m_user:
            uname = unquote(m_user.group(1)).strip().lower() or "guest"
            conn = get_db_conn()
            try:
                st = build_user_state(conn, uname)
                if not st:
                    return self._send_json(404, {"detail": f"Профиль @{uname} ещё не создан"})
                return self._send_json(200, {"status": "ok", "username": uname, "state": st})
            finally:
                conn.close()

        # Раздача статики фронтенда
        if path in ("/", "/index.html"):
            target_file = os.path.join(FRONTEND_DIR, "index.html")
        elif path == "/schema":
            target_file = os.path.join(FRONTEND_DIR, "chepoel_db_schema.html")
        else:
            rel = path.lstrip("/")
            target_file = os.path.abspath(os.path.join(FRONTEND_DIR, rel))
            if not target_file.startswith(str(FRONTEND_DIR)):
                self.send_error(403)
                return

        if os.path.isfile(target_file):
            mime, _ = mimetypes.guess_type(target_file)
            with open(target_file, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", (mime or "text/html") + "; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_json_body()

        if path == "/api/auth/register":
            uname = str(body.get("username") or "").strip().lower()
            disp = str(body.get("displayName") or uname).strip()
            pass_hash = str(body.get("passHash") or "")
            if len(uname) < 3:
                return self._send_json(400, {"detail": "Логин должен содержать минимум 3 символа"})
            conn = get_db_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT username FROM accounts WHERE username = ?", (uname,))
                if cur.fetchone():
                    return self._send_json(409, {"detail": f"Аккаунт @{uname} уже существует"})
                init_state = body.get("state") or {
                    "profile": {"nickname": disp},
                    "goals": {"kcal": 2000, "p": 140, "f": 65, "c": 210, "mode": "lose", "label": "Похудение (-15%)"},
                    "days": {},
                    "weightLog": [],
                    "customProducts": [],
                    "onboarded": False
                }
                save_user_state(conn, uname, init_state, pass_hash=pass_hash, display_name=disp)
                conn.commit()
                st = build_user_state(conn, uname)
                return self._send_json(200, {"status": "ok", "username": uname, "displayName": disp, "state": st})
            finally:
                conn.close()

        if path == "/api/auth/login":
            uname = str(body.get("username") or "").strip().lower()
            pass_hash = str(body.get("passHash") or "")
            conn = get_db_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM accounts WHERE username = ?", (uname,))
                acc = cur.fetchone()
                if not acc:
                    return self._send_json(404, {"detail": f"Аккаунт @{uname} не найден"})
                if acc["pass_hash"] and acc["pass_hash"] not in ("sha256_synced", "guest_no_pass") and acc["pass_hash"] != pass_hash:
                    return self._send_json(401, {"detail": "Неверный пароль"})
                st = build_user_state(conn, uname)
                return self._send_json(200, {"status": "ok", "username": uname, "displayName": acc["display_name"], "state": st})
            finally:
                conn.close()

        self.send_error(404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        m_user = re.match(r"^/api/users/([^/]+)/state$", parsed.path)
        if m_user:
            uname = unquote(m_user.group(1)).strip().lower() or "guest"
            body = self._read_json_body()
            conn = get_db_conn()
            try:
                save_user_state(conn, uname, body)
                conn.commit()
                st = build_user_state(conn, uname)
                if st:
                    save_user_backup_snapshot(uname, st)
                return self._send_json(200, {"status": "saved", "username": uname, "state": st})
            finally:
                conn.close()
        self.send_error(404)


def run_local_server(host="127.0.0.1", port=8000):
    init_db_and_seed()
    httpd = ThreadingHTTPServer((host, port), ChePoelRequestHandler)
    httpd.serve_forever()


if __name__ == "__main__":
    run_local_server()
