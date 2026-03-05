-- ============================================================
-- GovHub · labor_rates + labor_rate_benchmarks
-- Run once in Supabase SQL Editor (or via migration runner)
-- ============================================================

-- ── labor_rates ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS labor_rates (
    id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    labor_category  TEXT          NOT NULL,
    min_experience  INTEGER,
    education_level TEXT,
    hourly_rate     DECIMAL(10,2) NOT NULL,
    schedule        TEXT,
    sin_number      TEXT,
    vendor_name     TEXT,
    contract_number TEXT,
    source          TEXT          NOT NULL DEFAULT 'gsa_calc',
    collected_date  DATE          NOT NULL DEFAULT CURRENT_DATE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    -- Upsert key: same vendor + contract + role = same record
    UNIQUE (vendor_name, contract_number, labor_category)
);

CREATE INDEX IF NOT EXISTS idx_labor_rates_category
    ON labor_rates (labor_category);

CREATE INDEX IF NOT EXISTS idx_labor_rates_collected
    ON labor_rates (collected_date);

-- ── labor_rate_benchmarks ────────────────────────────────────
CREATE TABLE IF NOT EXISTS labor_rate_benchmarks (
    id             UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    labor_category TEXT          NOT NULL,
    week_start     DATE          NOT NULL,
    p25_rate       DECIMAL(10,2),
    p50_rate       DECIMAL(10,2),
    p75_rate       DECIMAL(10,2),
    sample_count   INTEGER,
    computed_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    UNIQUE (labor_category, week_start)
);

CREATE INDEX IF NOT EXISTS idx_benchmarks_category
    ON labor_rate_benchmarks (labor_category);


-- ── If table already exists, run this instead to add the constraint ──
-- ALTER TABLE labor_rates
--     ADD CONSTRAINT labor_rates_upsert_key
--     UNIQUE (vendor_name, contract_number, labor_category);