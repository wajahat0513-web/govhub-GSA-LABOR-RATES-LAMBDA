import os
import logging
import psycopg2
from psycopg2.extras import execute_values
from datetime import date, timedelta

logger = logging.getLogger(__name__)


def get_conn():
    return psycopg2.connect(
        os.environ["DATABASE_URL"],
        sslmode="require",
        connect_timeout=10,
    )


def insert_rates(conn, records) -> int:
    if not records:
        return 0

    # Deduplicate within batch — last occurrence wins for same conflict key
    seen = {}
    for r in records:
        key = (r.vendor_name, r.contract_number, r.labor_category)
        seen[key] = r

    rows = [r.to_row() for r in seen.values()]

    sql = """
        INSERT INTO labor_rates
            (labor_category, min_experience, education_level, hourly_rate,
             schedule, sin_number, vendor_name, contract_number,
             source, collected_date)
        VALUES %s
        ON CONFLICT (vendor_name, contract_number, labor_category)
        DO UPDATE SET
            hourly_rate     = EXCLUDED.hourly_rate,
            min_experience  = EXCLUDED.min_experience,
            education_level = EXCLUDED.education_level,
            schedule        = EXCLUDED.schedule,
            sin_number      = EXCLUDED.sin_number,
            collected_date  = EXCLUDED.collected_date;
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows, page_size=500)
    conn.commit()
    logger.info(
        f"Upserted {len(rows)} rows into labor_rates ({len(records) - len(rows)} duplicates dropped)"
    )
    return len(rows)


def compute_benchmarks(conn, collected_date: str):
    d = date.fromisoformat(collected_date)
    week_start = d - timedelta(days=d.weekday())

    sql = """
        INSERT INTO labor_rate_benchmarks
            (labor_category, week_start, p25_rate, p50_rate, p75_rate, sample_count)
        SELECT
            labor_category,
            %s::date,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY hourly_rate),
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY hourly_rate),
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY hourly_rate),
            COUNT(*)
        FROM labor_rates
        GROUP BY labor_category
        ON CONFLICT (labor_category, week_start)
        DO UPDATE SET
            p25_rate     = EXCLUDED.p25_rate,
            p50_rate     = EXCLUDED.p50_rate,
            p75_rate     = EXCLUDED.p75_rate,
            sample_count = EXCLUDED.sample_count,
            computed_at  = NOW();
    """
    with conn.cursor() as cur:
        cur.execute(sql, (week_start,))
    conn.commit()
    logger.info(f"Benchmarks upserted for week starting {week_start}")
