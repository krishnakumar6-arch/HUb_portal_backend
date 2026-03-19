-- Hub Portal — PostgreSQL Schema
-- Run this once to set up all tables
-- Compatible with Supabase, Neon, Railway PostgreSQL

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Hubs ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hubs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hub_code        VARCHAR(50) UNIQUE NOT NULL,
    hub_name        VARCHAR(200),
    sitting_location VARCHAR(200),
    city            VARCHAR(100),
    state           VARCHAR(100),
    tier            VARCHAR(50),
    facility_type   VARCHAR(50),
    site_category   VARCHAR(100),
    cost_centre     VARCHAR(100),
    sub_cost_centre VARCHAR(100),
    manager_name    VARCHAR(200),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_hubs_city  ON hubs(city);
CREATE INDEX IF NOT EXISTS idx_hubs_state ON hubs(state);
CREATE INDEX IF NOT EXISTS idx_hubs_tier  ON hubs(tier);

-- ── Expense Categories ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS expense_categories (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_key VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    raw_chains   TEXT
);

-- Seed the 7 standard categories
INSERT INTO expense_categories (category_key, display_name) VALUES
    ('Housekeeping',         'Housekeeping'),
    ('Tea / Coffee / Water', 'Tea / Coffee / Water'),
    ('Printing & Stationery','Printing & Stationery'),
    ('Repair & Maintenance', 'Repair & Maintenance'),
    ('Electricity',          'Electricity'),
    ('Internet & Mobile',    'Internet & Mobile'),
    ('Rent',                 'Rent'),
    ('Food & Welfare',       'Food & Welfare'),
    ('Travel & Transport',   'Travel & Transport'),
    ('Operations',           'Operations'),
    ('Miscellaneous',        'Miscellaneous'),
    ('Other',                'Other')
ON CONFLICT (category_key) DO NOTHING;

-- ── Expenses ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS expenses (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hub_id             UUID NOT NULL REFERENCES hubs(id) ON DELETE CASCADE,
    category_id        UUID REFERENCES expense_categories(id),
    raw_category_chain VARCHAR(300),
    employee_name      VARCHAR(200),
    employee_id        VARCHAR(50),
    role               VARCHAR(200),
    band               VARCHAR(20),
    expense_date       DATE,
    expense_amount     FLOAT,
    approved_amount    FLOAT,
    base_amount        FLOAT,
    transaction_status VARCHAR(50),
    report_id          VARCHAR(100),
    report_name        VARCHAR(300),
    description        TEXT,
    policy_violation   BOOLEAN DEFAULT FALSE,
    bill_available     VARCHAR(10),
    vendor_name        VARCHAR(200),
    attachment_url     TEXT,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_expenses_hub_id  ON expenses(hub_id);
CREATE INDEX IF NOT EXISTS idx_expenses_date    ON expenses(expense_date);
CREATE INDEX IF NOT EXISTS idx_expenses_status  ON expenses(transaction_status);
CREATE INDEX IF NOT EXISTS idx_expenses_cat     ON expenses(category_id);

-- ── Hub Monthly Aggregates ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hub_aggregates (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hub_id                 UUID NOT NULL REFERENCES hubs(id) ON DELETE CASCADE,
    category_id            UUID REFERENCES expense_categories(id),
    month                  INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    year                   INTEGER NOT NULL,
    total_amount           FLOAT DEFAULT 0,
    approved_amount        FLOAT DEFAULT 0,
    transaction_count      INTEGER DEFAULT 0,
    policy_violation_count INTEGER DEFAULT 0,
    refreshed_at           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(hub_id, category_id, month, year)
);

CREATE INDEX IF NOT EXISTS idx_agg_hub_id ON hub_aggregates(hub_id);
CREATE INDEX IF NOT EXISTS idx_agg_year   ON hub_aggregates(year);

-- ── Hub Square Footage ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hub_sqft (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hub_id         UUID UNIQUE NOT NULL REFERENCES hubs(id) ON DELETE CASCADE,
    sqft_area      FLOAT NOT NULL,
    effective_from DATE,
    source         VARCHAR(100) DEFAULT 'manual_upload',
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

-- ── Users ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hub_id           UUID REFERENCES hubs(id),   -- NULL = admin (sees all hubs)
    name             VARCHAR(200) NOT NULL,
    email            VARCHAR(200) UNIQUE NOT NULL,
    hashed_password  VARCHAR(300) NOT NULL,
    role             VARCHAR(20) NOT NULL DEFAULT 'hi', -- 'admin' | 'hi'
    department       VARCHAR(100),
    is_active        BOOLEAN DEFAULT TRUE,
    last_login       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ── ETL Logs ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS etl_logs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at       TIMESTAMPTZ DEFAULT NOW(),
    finished_at      TIMESTAMPTZ,
    status           VARCHAR(20) DEFAULT 'running',  -- running | success | failed
    rows_processed   INTEGER DEFAULT 0,
    rows_inserted    INTEGER DEFAULT 0,
    error_message    TEXT,
    triggered_by     VARCHAR(50) DEFAULT 'scheduler'
);

-- ── Seed admin user (password: admin123 — CHANGE IN PRODUCTION) ──────────────
-- bcrypt hash of "admin123"
INSERT INTO users (name, email, hashed_password, role, department) VALUES
    ('Admin User', 'admin@hubportal.in',
     '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW',
     'admin', 'Business Analytics')
ON CONFLICT (email) DO NOTHING;
