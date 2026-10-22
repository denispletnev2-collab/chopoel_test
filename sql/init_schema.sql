-- ============================================================================
-- СУБД: PostgreSQL 16+
-- Проект: «ЧёПоел» — Умный дневник питания КБЖУ с ИИ и геймификацией
-- Нормализованная реляционная схема базы данных (3-я нормальная форма, 3НФ)
-- ============================================================================

BEGIN;

-- 1. Таблица учётных записей пользователей (Сущность: ПОЛЬЗОВАТЕЛЬ)
CREATE TABLE IF NOT EXISTS accounts (
    username        VARCHAR(50) PRIMARY KEY,
    display_name    VARCHAR(100) NOT NULL,
    pass_hash       VARCHAR(128) NOT NULL, -- SHA-256 с солью chepoel_salt_v4_
    registered_date DATE         NOT NULL DEFAULT CURRENT_DATE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2. Справочник наград за уровни каждые 5 LVL (Сущность: НАГРАДА УРОВНЯ)
CREATE TABLE IF NOT EXISTS level_rewards (
    reward_lvl      INT PRIMARY KEY CHECK (reward_lvl >= 1),
    title           VARCHAR(100) NOT NULL,
    description     TEXT         NOT NULL DEFAULT '',
    banner_class    VARCHAR(40)  NOT NULL,
    frame_class     VARCHAR(40)  NOT NULL,
    nick_effect     VARCHAR(40)  NOT NULL DEFAULT ''
);

-- 3. Профиль, нормы КБЖУ и прогресс геймификации (Сущность: ПРОФИЛЬ И ЦЕЛИ, 1:1 с accounts)
CREATE TABLE IF NOT EXISTS profiles (
    profile_id        SERIAL PRIMARY KEY,
    username          VARCHAR(50)  NOT NULL UNIQUE REFERENCES accounts(username) ON DELETE CASCADE,
    nickname          VARCHAR(100) NOT NULL DEFAULT 'Атлет',
    status_text       VARCHAR(200) NOT NULL DEFAULT 'Иду к своей лучшей форме 🔥',
    avatar_emoji      VARCHAR(16)  NOT NULL DEFAULT '⚡',
    avatar_img_b64    TEXT         DEFAULT '',
    banner_img_b64    TEXT         DEFAULT '',
    frame_class       VARCHAR(40)  NOT NULL DEFAULT 'frame-emerald',
    banner_class      VARCHAR(40)  NOT NULL DEFAULT 'banner-aurora',
    nick_effect       VARCHAR(40)  NOT NULL DEFAULT '',
    goal_mode         VARCHAR(20)  NOT NULL DEFAULT 'lose' CHECK (goal_mode IN ('lose', 'maintain', 'gain')),
    goal_label        VARCHAR(60)  NOT NULL DEFAULT 'Похудение (-15%)',
    kcal_target       INT          NOT NULL DEFAULT 2000 CHECK (kcal_target BETWEEN 500 AND 10000),
    p_target          INT          NOT NULL DEFAULT 140  CHECK (p_target >= 0),
    f_target          INT          NOT NULL DEFAULT 65   CHECK (f_target >= 0),
    c_target          INT          NOT NULL DEFAULT 210  CHECK (c_target >= 0),
    bonus_xp          INT          NOT NULL DEFAULT 0,
    purchased_shields INT          NOT NULL DEFAULT 0    CHECK (purchased_shields >= 0),
    spent_shield_xp   INT          NOT NULL DEFAULT 0    CHECK (spent_shield_xp >= 0),
    last_seen_level   INT          NOT NULL DEFAULT 1    CHECK (last_seen_level >= 1),
    theme             VARCHAR(16)  NOT NULL DEFAULT 'dark',
    onboarded         BOOLEAN      NOT NULL DEFAULT TRUE,
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 4. Каталог продуктов РФ (615+ позиций) и пользовательских блюд (Сущность: ПРОДУКТ / БЛЮДО)
CREATE TABLE IF NOT EXISTS products (
    product_id        VARCHAR(64) PRIMARY KEY,
    creator_username  VARCHAR(50) REFERENCES accounts(username) ON DELETE SET NULL,
    name              VARCHAR(220) NOT NULL,
    brand             VARCHAR(120) NOT NULL DEFAULT '',
    category          VARCHAR(80)  NOT NULL DEFAULT 'Готовая еда',
    icon              VARCHAR(16)  NOT NULL DEFAULT '🍲',
    kcal100           INT          NOT NULL CHECK (kcal100 >= 0),
    p100              NUMERIC(6,1) NOT NULL DEFAULT 0 CHECK (p100 >= 0),
    f100              NUMERIC(6,1) NOT NULL DEFAULT 0 CHECK (f100 >= 0),
    c100              NUMERIC(6,1) NOT NULL DEFAULT 0 CHECK (c100 >= 0),
    default_portion   INT          NOT NULL DEFAULT 100 CHECK (default_portion > 0),
    barcode           VARCHAR(32)  DEFAULT '',
    is_custom         BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_products_name_trgm ON products (LOWER(name));
CREATE INDEX IF NOT EXISTS idx_products_category ON products (category);

-- 5. Суточный дневник питания и дисциплины (Сущность: ДЕНЬ ДНЕВНИКА)
CREATE TABLE IF NOT EXISTS daily_logs (
    day_id            SERIAL PRIMARY KEY,
    username          VARCHAR(50) NOT NULL REFERENCES accounts(username) ON DELETE CASCADE,
    log_date          DATE        NOT NULL,
    water_ml          INT         NOT NULL DEFAULT 0 CHECK (water_ml >= 0),
    freeze_used       BOOLEAN     NOT NULL DEFAULT FALSE, -- Защита Щитом заморозки
    penalty_redeemed  BOOLEAN     NOT NULL DEFAULT FALSE, -- Отработка штрафа квестом
    simulated_miss    BOOLEAN     NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_daily_logs_user_date UNIQUE (username, log_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_logs_user_date ON daily_logs (username, log_date DESC);

-- 6. Записи приёмов пищи за день (Сущность: ПРИЁМ ПИЩИ)
CREATE TABLE IF NOT EXISTS meal_entries (
    meal_id           SERIAL PRIMARY KEY,
    day_id            INT          NOT NULL REFERENCES daily_logs(day_id) ON DELETE CASCADE,
    product_id        VARCHAR(64)  REFERENCES products(product_id) ON DELETE SET NULL,
    meal_type         VARCHAR(20)  NOT NULL DEFAULT 'breakfast' CHECK (meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')),
    dish_name         VARCHAR(220) NOT NULL,
    grams             INT          NOT NULL CHECK (grams > 0),
    kcal              INT          NOT NULL CHECK (kcal >= 0),
    p                 NUMERIC(6,1) NOT NULL DEFAULT 0,
    f                 NUMERIC(6,1) NOT NULL DEFAULT 0,
    c                 NUMERIC(6,1) NOT NULL DEFAULT 0,
    kcal100           INT          NOT NULL DEFAULT 0,
    p100              NUMERIC(6,1) NOT NULL DEFAULT 0,
    f100              NUMERIC(6,1) NOT NULL DEFAULT 0,
    c100              NUMERIC(6,1) NOT NULL DEFAULT 0,
    logged_time       VARCHAR(10)  NOT NULL DEFAULT '12:00',
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_meal_entries_day_id ON meal_entries (day_id);

-- 7. История замеров веса тела (Сущность: ЗАМЕР ВЕСА)
CREATE TABLE IF NOT EXISTS weight_logs (
    weight_id         SERIAL PRIMARY KEY,
    username          VARCHAR(50)  NOT NULL REFERENCES accounts(username) ON DELETE CASCADE,
    measure_date      DATE         NOT NULL,
    weight_kg         NUMERIC(5,1) NOT NULL CHECK (weight_kg BETWEEN 25 AND 300),
    CONSTRAINT uq_weight_logs_user_date UNIQUE (username, measure_date)
);

CREATE INDEX IF NOT EXISTS idx_weight_logs_user_date ON weight_logs (username, measure_date ASC);

-- 8. Первичное заполнение справочника наград за уровни (1, 5, 10, 15, 20, 25, 30 LVL)
INSERT INTO level_rewards (reward_lvl, title, description, banner_class, frame_class, nick_effect)
VALUES
    (1,  '🌱 Стартовый набор (База)',        '3 базовые расцветки профиля и 3 базовые рамки аватара.',                                    'banner-aurora',  'frame-emerald', ''),
    (5,  '⚡ Кибер-Следопыт (Тир 1)',        'Неоновая расцветка Synthwave Cyber Grid, рамка Cyberpunk Neon и неоновый ник.',             'banner-cyber',   'frame-cyber',   'nick-cyber'),
    (10, '💜 Адепт Дисциплины (Тир 2)',      'Космическая расцветка Galactic Nitro Nebula, рамка Nitro Plasma и свечение ника Nitro.',    'banner-nebula',  'frame-discord', 'nick-nitro'),
    (15, '🔥 Машина Режима (Тир 3)',         'Огненная расцветка Crimson Inferno, пульсирующая рамка Hellfire Blaze и пламенный ник.',    'banner-tokyo',   'frame-fire',    'nick-fire'),
    (20, '👑 Повелитель Калорий (Тир 4)',    'Королевская расцветка Golden Imperial, золотая рамка Dragon Lore Gold и золотой никнейм.',  'banner-gold',    'frame-gold',    'nick-gold'),
    (25, '🌌 Архитектор Формы (Тир 5)',      'Живой анимированный баннер Quantum Matrix, плазменная рамка Quantum Singularity.',          'banner-quantum', 'frame-quantum', 'nick-quantum'),
    (30, '💎 Легенда ЧёПоел (Godlike Тир 6)','Полноцветный RGB-баннер Chroma Godlike, радужная рамка 360° и легендарный перелив ника.',   'banner-chroma',  'frame-chroma',  'nick-chroma')
ON CONFLICT (reward_lvl) DO NOTHING;

COMMIT;
