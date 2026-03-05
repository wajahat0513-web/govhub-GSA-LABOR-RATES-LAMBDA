import os
import json
import asyncio
import logging
import aiohttp
from datetime import date
from transform import extract_results, transform_record
from db import get_conn, insert_rates, compute_benchmarks

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://api.gsa.gov/acquisition/calc/v3/api/ceilingrates/"
PAGE_SIZE = 50  # records per page — do not change unless API changes
BATCH_SIZE = 5  # pages fetched concurrently per batch
MAX_PAGES = 10  # set to an int e.g. 10 to cap pages for testing, None = fetch all
MAX_RETRIES = 3


async def fetch_page(session: aiohttp.ClientSession, api_key: str, page: int) -> list:
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    params = {"page": page, "page_size": PAGE_SIZE}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.get(
                BASE_URL,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 429:
                    logger.warning(f"Rate limit on page {page} — sleeping 65s")
                    await asyncio.sleep(65)
                    continue

                resp.raise_for_status()
                return extract_results(await resp.json())

        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            logger.warning(f"Page {page} attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(3 * attempt)
            else:
                logger.error(
                    f"Page {page} failed after {MAX_RETRIES} attempts — skipping"
                )
                return []


async def fetch_batch(
    session: aiohttp.ClientSession, api_key: str, pages: list[int]
) -> list:
    results = await asyncio.gather(*[fetch_page(session, api_key, p) for p in pages])
    return [row for page_rows in results for row in page_rows]


async def fetch_and_save(api_key: str, collected_date: str) -> int:
    conn = get_conn()
    total_saved = 0
    page = 1

    async with aiohttp.ClientSession() as session:
        while True:
            # Respect MAX_PAGES cap if set
            if MAX_PAGES and page > MAX_PAGES:
                logger.info(f"Reached MAX_PAGES={MAX_PAGES} — stopping")
                break

            pages = list(range(page, page + BATCH_SIZE))
            logger.info(f"Fetching pages {pages[0]}–{pages[-1]}")
            raw_rows = await fetch_batch(session, api_key, pages)

            if not raw_rows:
                logger.info("No more data — done")
                break

            records = [r for raw in raw_rows if (r := transform_record(raw))]
            logger.info(
                f"Batch {pages[0]}–{pages[-1]} | {len(raw_rows)} raw | {len(records)} valid"
            )

            if records:
                total_saved += insert_rates(conn, records)

            # Fewer rows than a full batch means we've hit the last page
            if len(raw_rows) < PAGE_SIZE * BATCH_SIZE:
                break

            page += BATCH_SIZE

    compute_benchmarks(conn, collected_date)
    conn.close()
    return total_saved


def run():
    api_key = os.environ["GSA_CALC_API_KEY"]
    collected_date = date.today().isoformat()

    total = asyncio.run(fetch_and_save(api_key, collected_date))
    logger.info(f"Done — {total} rows saved")

    return {"collected_date": collected_date, "rows_inserted": total}


# ── Lambda entry point ────────────────────────────────────
def handler(event, context):
    result = run()
    return {"statusCode": 200, "body": json.dumps(result)}


# ── Local entry point ─────────────────────────────────────
if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    result = run()
    print(result)
