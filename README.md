# DocuSign Master Service

A backend service that pulls eSignature data from DocuSign (envelopes, recipients,
documents, templates), survives rate limits and crashes, normalizes the data into
tables, and stores the results as Parquet and JSON in MinIO.

**Stack:** Python 3.13, FastAPI, PostgreSQL, SQLAlchemy + Alembic, MinIO, Docker Compose.

---

## How it works

```
POST /api/scan ──► ExtractionService (background task)
                     envelopes → recipients → documents → templates
                     • JWT Grant auth, token cached
                     • 429 handling (Retry-After) + retry with backoff and jitter
                     • checkpoint saved after every page (resume after a crash)
                     • failed external calls recorded in a dead-letter table
                     ▼
                  data/raw/<job_id>/<resource>/page_000000.json

POST /api/normalization/{job_id} ──► NormalizationService
                     raw pages → Envelope / Recipient / Document / Template normalizers
                     ├─► Job.result (JSONB in PostgreSQL)
                     └─► MinIO: normalized/<job_id>/<table>.parquet
                                normalized/<job_id>/<table>.json
```

Normalized tables: `envelopes`, `recipients`, `documents`, `templates`.

---

## Project structure

```
app/
├── main.py                  FastAPI app, routers, HMAC middleware
├── config.py                Settings loaded from .env (pydantic-settings)
├── api/                     health, validate_credentials, scan, normalization, maintenance, audit
├── core/                    hmac_auth, rate_limiter, retry, dlq, config helpers
├── db/                      SQLAlchemy models, session
├── docusign/                auth client (JWT Grant), API client, envelopes, templates
├── normalizers/             base + envelope, recipient, document, template
├── services/                extraction, scan runner/stages, normalization (+ export),
│                            job service, audit service, MinIO client
└── utils/                   raw page storage, serializers (JSON/Parquet)
alembic/                     database migrations
scripts/                     helper scripts (seed envelopes, signed API calls)
tests/                       unit and integration tests
```

---

## Getting started

### 1. Configure

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

Fill in `.env`. The main groups are:

| Group | Keys |
|---|---|
| Database | `DATABASE_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DB_POOL_SIZE` |
| MinIO | `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`, `MINIO_SECURE` |
| DocuSign | `DOCUSIGN_INTEGRATION_KEY`, `DOCUSIGN_USER_ID`, `DOCUSIGN_ACCOUNT_ID`, `DOCUSIGN_AUTH_SERVER`, `DOCUSIGN_BASE_URL`, `DOCUSIGN_PRIVATE_KEY_PATH` |
| Rate limits / paging | `DOCUSIGN_MAX_RETRIES_ON_429`, `DOCUSIGN_DEFAULT_RETRY_AFTER_SECONDS`, `DOCUSIGN_DEFAULT_PAGE_SIZE` |
| Resilience | `EXTERNAL_CALL_MAX_RETRIES`, `EXTERNAL_CALL_RETRY_DELAYS`, `EXTERNAL_CALL_JITTER`, `DLQ_PAYLOAD_MAX_BYTES` |
| HMAC | `HMAC_ENABLED`, `HMAC_SECRET_KEY_CORE`, `HMAC_SECRET_KEY_ENGINEER`, `HMAC_SIGNATURE_MAX_AGE` |
| Job tracking | `JOB_HEARTBEAT_INTERVAL_SECONDS`, `JOB_CRASH_TIMEOUT_MINUTES` |

Generate each HMAC key with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Put the DocuSign RSA private key at `secrets/private.key`. **Never commit it.**
Inside Docker use `MINIO_ENDPOINT=minio:9000`; from your own machine use `localhost:9000`.

### 2. Run

```bash
docker compose up -d --build
docker compose exec app alembic upgrade head     # create / update tables
curl http://localhost:8000/api/health            # {"status":"ok"}
```

| Service | URL |
|---|---|
| API | http://localhost:8000 (docs at `/docs`) |
| MinIO console | http://localhost:9001 |
| PostgreSQL | localhost:5432 |

`./data` is mounted into the container, so raw pages survive container restarts.

---

## Authentication (HMAC)

Every route except `/api/health` requires these headers:

| Header | Value |
|---|---|
| `X-Key-Id` | `core` or `engineer` |
| `X-Timestamp` | current Unix time in seconds |
| `X-Signature` | `compute_signature(secret, timestamp, method, path, body)` |

The signature uses the secret for that key id, and requests older than
`HMAC_SIGNATURE_MAX_AGE` seconds are rejected. The helper scripts below sign
requests for you. See `app/core/hmac_auth.py` for the exact algorithm.

---

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness check (public) |
| POST | `/api/validate-credentials` | Check DocuSign JWT credentials |
| POST | `/api/scan` | Start a scan (`{"from_date": "2024-01-01"}`), returns `202` and a `job_id` |
| GET | `/api/scan/{job_id}` | Status, stage, per-resource counts, heartbeat |
| POST | `/api/scan/{job_id}/resume` | Resume from the latest checkpoint |
| POST | `/api/scan/{job_id}/cancel` | Cancel a job |
| POST | `/api/normalization/{job_id}` | Normalize a completed scan and export to MinIO |
| GET | `/api/normalization/{job_id}/status` | Normalization and export status |
| GET | `/api/normalization/{job_id}/results` | MinIO object paths per table |

### Normalization details

`POST /api/normalization/{job_id}` returns record counts and export paths.
Add `?include_data=true` to also receive the full rows (can be very large).

| Status | Meaning |
|---|---|
| 200 | Normalized and exported |
| 400 | `job_id` is not a valid UUID |
| 404 | Job not found |
| 409 | Scan not completed, raw data missing for the job, or a run already in progress |
| 500 | Normalization or export failed (see the audit log) |

The result is saved in the database before the export. If MinIO fails, the data is kept,
the failure is audited, and re-running is safe because export paths are fixed.

### Try it

```bash
python call_scan.py                                            # start a scan
python -m scripts.call_normalization <job_id>                  # run normalization
python -m scripts.call_normalization <job_id> status
python -m scripts.call_normalization <job_id> results
```

Read an exported file straight from MinIO:

```bash
docker compose exec app python -c "from app.services.minio_client import minio_client as m; import io, pandas as pd; print(pd.read_parquet(io.BytesIO(m.download_bytes('normalized/<job_id>/envelopes.parquet'))).head())"
```

---

## Tests

```bash
pytest -q
```

Tests cover HMAC auth, the retry and rate-limit logic, extraction paging and checkpoints,
all four normalizers, the normalization service, the serializers, the MinIO client,
and the normalization API. DocuSign and MinIO are mocked, so no network is needed.

---

## Known limitations

- The "already running" guard for normalization works inside one process. Running several
  uvicorn workers would need a database-backed lock.
- Normalized rows are stored in `Job.result`, which replaces the scan job's earlier result value.
- Raw pages live under `data/`. If that folder is lost, completed scans can no longer be
  normalized (the API returns `409`); run a new scan.

---

## Security notes

- Keep `.env` and `secrets/private.key` out of git.
- Use real, random HMAC keys outside local development.