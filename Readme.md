# GovHub · GSA CALC+ Labor Rates Lambda

Weekly ingestion pipeline that fetches labor rate data from the GSA CALC+ API, stores it in Supabase, and computes pricing benchmarks used by the GovHub Pricing Intelligence feature.

---

## What This Does

GSA CALC+ (Contract-Awarded Labor Categories) is a federal database of labor rates from GSA Schedule contracts. It tells you what the government is actually paying for specific labor categories across thousands of vendors.

This Lambda:
1. Fetches all labor rate records from the GSA CALC+ API every Monday at 2am UTC
2. Validates and transforms each record using Pydantic
3. Upserts into `labor_rates` table — new records are inserted, changed rates are updated, nothing is duplicated
4. Computes p25/p50/p75 percentile benchmarks per labor category and stores them in `labor_rate_benchmarks`

The benchmarks power the **Pricing Intelligence** feature in GovHub — when a user is building a proposal, they can see market rate ranges for any labor category pulled live from real GSA contract data.

---

## Architecture

```
EventBridge (cron weekly)
        ↓
   AWS Lambda
        ↓
  GSA CALC+ API  ──→  5 pages fetched concurrently per batch
        ↓
  Pydantic validation + deduplication
        ↓
  Supabase (PostgreSQL)
    ├── labor_rates          ← always current, upserted weekly
    └── labor_rate_benchmarks ← weekly snapshot of p25/p50/p75 per category
```

---

## Project Structure

```
.github/
  workflows/
    deploy-labor-rates.yml   ← CI/CD pipeline
labor_rates/
  handler.py                 ← Lambda entry point + async fetch logic
  transform.py               ← Pydantic model + field mapping
  db.py                      ← DB connection, upsert, benchmarks
  Dockerfile                 ← Lambda container image
  requirements.txt
  .env                       ← local only, never commit
  .env.example               ← commit this
sql/
  001_create_labor_rates.sql ← run once in Supabase
```

---

## Database Tables

### `labor_rates`
Stores current labor rates. Upserted weekly — unique key is `(vendor_name, contract_number, labor_category)`.

| Column | Type | Source |
|---|---|---|
| `labor_category` | TEXT | API |
| `min_experience` | INTEGER | API |
| `education_level` | TEXT | API (enum-mapped) |
| `hourly_rate` | DECIMAL(10,2) | API |
| `schedule` | TEXT | API |
| `sin_number` | TEXT | API |
| `vendor_name` | TEXT | API |
| `contract_number` | TEXT | API |
| `source` | TEXT | Computed — always `gsa_calc` |
| `collected_date` | DATE | Computed — date of ingest run |

### `labor_rate_benchmarks`
Computed weekly across all current `labor_rates` data. One row per `(labor_category, week_start)`.

| Column | Type | Notes |
|---|---|---|
| `labor_category` | TEXT | |
| `week_start` | DATE | Monday of computed week |
| `p25_rate` | DECIMAL(10,2) | 25th percentile hourly rate |
| `p50_rate` | DECIMAL(10,2) | Median hourly rate |
| `p75_rate` | DECIMAL(10,2) | 75th percentile hourly rate |
| `sample_count` | INTEGER | Number of rates in category |

---

## Local Development

**1. Clone and set up environment**
```bash
git clone https://github.com/wajahat0513-web/govhub-GSA-LABOR-RATES-LAMBDA
cd govhub-GSA-LABOR-RATES-LAMBDA/labor_rates
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

**2. Create `.env` from example**
```bash
cp .env.example .env
```

Fill in `.env`:
```dotenv
DATABASE_URL=postgresql://postgres.xxxx:password@aws-1-us-east-2.pooler.supabase.com:5432/postgres
GSA_CALC_API_KEY=your_key_here
```

Get a free GSA API key at: https://api.data.gov/signup/

**3. Run the SQL migration in Supabase**

Go to Supabase → SQL Editor → paste and run `sql/001_create_labor_rates.sql`

**4. Run locally**
```bash
python handler.py
```

You'll see batch-by-batch logs as pages are fetched and inserted. Check your Supabase tables to verify data landed correctly.

**Controlling how many pages to fetch during testing** — open `handler.py` and set:
```python
MAX_PAGES = 10   # fetches 10 pages × 100 records = 1000 rows
MAX_PAGES = None # fetches everything (production)
```

---

## AWS Deployment

### One-time setup

**1. Create ECR repository**
```bash
aws ecr create-repository \
  --repository-name govhub/lambda-labor-rates \
  --region us-east-2
```

**2. Build and push image (first time only)**
```bash
# Authenticate
aws ecr get-login-password --region us-east-2 | \
  docker login --username AWS --password-stdin \
  341093766548.dkr.ecr.us-east-2.amazonaws.com

# Build (Windows requires --provenance=false)
docker build --platform linux/amd64 --provenance=false \
  -t govhub/lambda-labor-rates .

# Tag
docker tag govhub/lambda-labor-rates:latest \
  341093766548.dkr.ecr.us-east-2.amazonaws.com/govhub/lambda-labor-rates:latest

# Push
docker push \
  341093766548.dkr.ecr.us-east-2.amazonaws.com/govhub/lambda-labor-rates:latest
```

**3. Create Lambda function**
- AWS Console → Lambda → Create function → Container image
- Name: `govhub-labor-rates`
- Image: browse ECR → select `latest`
- Architecture: `x86_64`
- Timeout: `5 minutes`
- Memory: `256 MB`

**4. Add environment variables**

Lambda → Configuration → Environment variables:

| Key | Value |
|---|---|
| `DATABASE_URL` | your Supabase connection string |
| `GSA_CALC_API_KEY` | your GSA API key |

**5. Add EventBridge weekly trigger**
- Lambda → Add trigger → EventBridge
- Create new rule
- Schedule: `cron(0 2 ? * MON *)`  ← every Monday 2am UTC

**6. Add GitHub secrets**

Repo → Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `AWS_ACCESS_KEY_ID` | your AWS access key |
| `AWS_SECRET_ACCESS_KEY` | your AWS secret key |

---

## CI/CD

Every push to `main` automatically:
1. Builds a new Docker image tagged with `:latest` and the git commit SHA
2. Pushes both tags to ECR
3. Updates the Lambda to use the new image

Pipeline file: `.github/workflows/deploy-labor-rates.yml`

To trigger manually: Actions → Deploy · labor-rates Lambda → Run workflow

---

## Manual Lambda Invocation

From terminal:
```bash
aws lambda invoke \
  --function-name govhub-labor-rates \
  --region us-east-2 \
  output.json && cat output.json
```

Or from AWS Console → Lambda → `govhub-labor-rates` → Test button.

---

## Data Update Strategy

`labor_rates` uses an **upsert** strategy, not append. The conflict key is `(vendor_name, contract_number, labor_category)`.

- **New vendor/contract** → inserted as a new row
- **Rate changed** → `hourly_rate` and `collected_date` updated in place
- **No change** → row updated with new `collected_date`, values unchanged

`labor_rate_benchmarks` gets a new row every Monday per labor category so pricing trends are preserved week over week even though the raw rates table stays lean.

---

## Source

- **API:** GSA CALC+ `https://api.gsa.gov/acquisition/calc/v3/api/ceilingrates/`
- **Spec:** `01_SOURCE_FIELD_MAPPING_v1_0_20FEB26`
- **Parent project:** GovHub Platform — Project X-ray