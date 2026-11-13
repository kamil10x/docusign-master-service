# DocuSign Master Service

A backend service that pulls eSignature data from DocuSign (envelopes, recipients,
documents, templates), survives rate limits and crashes, normalizes the data into
tables, and stores the results as Parquet and JSON in MinIO.

**Stack:** Python 3.13, FastAPI, PostgreSQL, SQLAlchemy + Alembic, MinIO, Docker Compose, pytest.

**Highlights**

- DocuSign JWT Grant authentication with token caching.
- Paged extraction with `429 / Retry-After` handling and retries with backoff and jitter.
- Checkpoint after every page, so a crashed or failed scan resumes where it stopped (no refetching, no duplicate pages).
- Dead-letter table for failed external calls; one bad envelope does not kill the scan.
- Stuck-job detection and recovery, cleanup of old raw data, and a queryable audit trail.
- HMAC-signed API with two rotating keys.
- 179 automated tests, including resume and full end-to-end pipeline tests.

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

/api/maintenance  ──► stuck-job recovery, failed-call review, cleanup
/api/audit        ──► who did what, and when
```

Normalized tables: `envelopes`, `recipients`, `documents`, `templates`.
See [DESIGN.md](DESIGN.md) for the full design and [docs/WRITEUP.md](docs/WRITEUP.md) for the project write-up.

---

## Project structure

```
app/
├── main.py                  FastAPI app, routers, HMAC middleware
├── config.py                Settings loaded from .env (pydantic-settings)
├── api/                     health, validate_credentials, scan, normalization, maintenance, audit
├── core/                    hmac_auth, rate_limiter, retry, dlq
├── db/                      SQLAlchemy models, session
├── docusign/                auth client (JWT Grant), API client, envelopes, templates, exceptions
├── normalizers/             base + envelope, recipient, document, template
├── services/                extraction, scan runner/stages, normalization (+ export),
│                            job service, audit service, MinIO client
└── utils/                   raw page storage, serializers (JSON/Parquet)
alembic/                     database migrations
scripts/                     helper scripts (seed envelopes, signed API calls, verification)
tests/                       unit, integration, resume and end-to-end tests
docs/                        progress report, write-up, weekly results
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
`./secrets` must be mounted into the **app** container (not only MinIO) so the background worker can read the RSA key.

---

## Authentication (HMAC)

Every route except `/api/health` requires these headers:

| Header | Value |
|---|---|
| `X-Key-Id` | `core` or `engineer` |
| `X-Timestamp` | current Unix time in seconds |
| `X-Signature` | `compute_signature(secret, timestamp, method, path, body)` |

The signature uses the secret for that key id, and requests older than
`HMAC_SIGNATURE_MAX_AGE` seconds are rejected. Two keys are valid at the same time,
so a key can be rotated without downtime. The helper scripts below sign requests for you.
See `app/core/hmac_auth.py` for the exact algorithm.

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
| GET | `/api/maintenance/jobs` | List jobs (filter by status and type) |
| POST | `/api/maintenance/recover-stale-jobs` | Mark `running` jobs with no recent heartbeat as `failed` (supports `dry_run`) |
| GET | `/api/maintenance/failed-calls` | List dead-letter rows (failed external calls) |
| POST | `/api/maintenance/failed-calls/{id}/resolve` | Mark a failed call as resolved |
| POST | `/api/maintenance/cleanup` | Remove old raw data (dry run by default) |
| GET | `/api/audit` | Audit trail, newest first |

Full request and response schemas are in the interactive docs at `/docs`.

### Scan lifecycle and resume

A scan moves through four stages: `envelopes → recipients → documents → templates`.
After every page (or every envelope, for the per-envelope stages) the service saves a checkpoint.

- **Write order:** the raw page file is written first, the checkpoint second. A crash between the two
  can only cause the same page to be written again (overwritten), never data to be skipped or duplicated.
- **Resume:** `POST /api/scan/{job_id}/resume` continues from the latest checkpoint. Pages already saved are not
  fetched again, and a completed job is not re-run.
- **Skipped items:** a per-envelope failure that is not systemic (not 401/403, not rate limiting, not a network error)
  is recorded in the dead-letter table, counted as `<resource>_failed`, and the scan carries on. Systemic failures
  fail the job but leave it resumable from the exact index.
- **Crashed workers:** the job's `updated_at` is its heartbeat. `recover-stale-jobs` marks a `running` job whose
  heartbeat is older than `JOB_CRASH_TIMEOUT_MINUTES` as `failed`, with a message pointing to the resume endpoint.
  Duplicate resume requests are ignored while the heartbeat is fresh.

### Audit trail

`GET /api/audit` accepts `job_id`, `action`, `actor`, `since`, `until`, `limit` and `offset`.
Recorded events include `scan_created`, `scan_started`, `scan_resumed`, `scan_completed`, `job_recovered_stale`,
`failed_call_recorded`, `normalization_started` and `normalization_completed`.
Audit logging never raises, so a logging problem cannot break real work. Events written by the background worker have
`actor = null`; maintenance calls record the HMAC key id.

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
python scripts/call_api.py POST /api/scan "{\"from_date\":\"2024-01-01\"}"   # start a scan
python -m scripts.call_normalization <job_id>                  # run normalization
python -m scripts.call_normalization <job_id> status
python -m scripts.call_normalization <job_id> results
```

`scripts/call_api.py` signs and sends any other request (maintenance, audit, scan status).

Read an exported file straight from MinIO:

```bash
docker compose exec app python -c "from app.services.minio_client import minio_client as m; import io, pandas as pd; print(pd.read_parquet(io.BytesIO(m.download_bytes('normalized/<job_id>/envelopes.parquet'))).head())"
```

---

## Tests

```bash
pytest -q
```

179 tests. DocuSign and MinIO are faked or mocked, so no network, Docker or credentials are needed.

| Area | What is covered |
|---|---|
| Auth | JWT Grant, token caching, credential validation, HMAC (signature, window, key rotation) |
| Resilience | Retry and backoff, `Retry-After`, rate limiter, dead-letter handling |
| Extraction | Paging, checkpoints, scan stages, scan runner, DocuSign endpoints (respx mocks) |
| **Resume** (`tests/test_resume.py`) | Failure mid-envelopes, mid-recipients, mid-documents; no refetching of saved pages; DLQ rows and `*_failed` counters survive a resume; crash between page write and checkpoint creates no duplicates; completed jobs are not re-run; crashed worker is recovered then resumed |
| Normalization | All four normalizers, serializers, MinIO client, export, service, API |
| Operations | Maintenance endpoints, audit service and API |
| **End to end** (`tests/test_e2e_pipeline.py`) | Scan → normalize → export → validate row counts in Parquet and JSON → audit trail; an interrupted-and-resumed scan produces the same result as a clean scan; 409 guards; idempotent re-run; API error codes |

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `500` or odd responses on port 8000 | A local Python process is also bound to `8000` and answers before Docker does. Stop it (`netstat -ano \| findstr :8000`). |
| Background scan fails on authentication | `./secrets` is not mounted into the **app** container, or `DOCUSIGN_PRIVATE_KEY_PATH` is wrong. |
| `409 No raw extraction data found` | `./data/raw/<job_id>` is gone (volume not mounted, or removed by cleanup). Run a new scan. |
| `Server disconnected` right after `docker compose up` | The app container is still starting; retry in a few seconds. |
| `401` from every call | Wrong `X-Key-Id`, stale `X-Timestamp`, or a signature built from a different secret. |

---

## Known limitations

- The "already running" guard for normalization works inside one process. Running several
  uvicorn workers would need a database-backed lock.
- Normalized rows are stored in `Job.result` (JSONB), which replaces the scan job's earlier result value.
  They are not yet in their own relational tables.
- Raw pages live under `data/`. If that folder is lost, completed scans can no longer be
  normalized (the API returns `409`); run a new scan.
- The HMAC signature covers method, path and body hash, but not the query string, and there is no nonce store, so a captured
  request could be replayed inside the `HMAC_SIGNATURE_MAX_AGE` window.
- Audit rows for jobs created before the audit feature (Day 24) have no `scan_created` event.

---

## Security notes

- Keep `.env` and `secrets/private.key` out of git (both are in `.gitignore`).
- Use real, random HMAC keys outside local development.
- Tokens, keys and signatures are never logged.