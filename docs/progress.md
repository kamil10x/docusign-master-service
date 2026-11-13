# DocuSign Master Service: Progress Report

**Status as of 2026-11-12: Days 1-28 complete. Final cleanup and submission tag remain.**
**Test suite: 179 passing.**

A FastAPI service that extracts DocuSign eSignature data (envelopes, recipients, documents, templates), survives rate limits and crashes through checkpointing, normalizes the data into tables, and exports it to MinIO as Parquet and JSON.

Stack: Python 3.13, FastAPI, PostgreSQL, SQLAlchemy + Alembic, MinIO, Docker Compose, pytest.

---

## Summary by week

| Week | Milestone | Status |
|------|-----------|--------|
| 1 | Setup, sandbox, authentication | Done (2026-10-28) |
| 2 | Envelope paging, rate limits, retries, scan engine | Done |
| 3 | Normalization tables, MinIO export | Done (2026-11-08) |
| 4 | Maintenance, error handling, audit, resume tests, end-to-end test, documentation | Done (2026-11-12) |

---

## Week 1: Setup and authentication (Days 1-7)

- Project scaffold with FastAPI, health endpoint (`/api/health`), Docker and Compose wiring (app, Postgres, MinIO).
- MinIO set up and reachable from the app.
- Database models and Alembic migration: `jobs`, `job_checkpoints`, `audit_logs`, `failed_external_calls`; `JobService` skeleton.
- DocuSign sandbox set up: integration key, RSA keypair, consent granted.
- `DocuSignAuthClient.get_access_token` using JWT Grant, with token caching.
- `POST /api/validate-credentials`, verified against the real sandbox (returned `valid: true`).
- HMAC request authentication via middleware, with unit tests.
- README.md and DESIGN.md first versions.

## Week 2: Extraction engine (Days 8-14)

- Test envelopes created in the sandbox; `list_envelopes` with date range and `start_position` paging.
- Rate limiter (HTTP 429 with `Retry-After`) and retry helper (`is_retryable`, `retry_call`, exponential backoff with jitter).
- `get_envelope_recipients` and `get_envelope_documents` with rate limiting and retries.
- `list_templates` with paging.
- Raw page storage as JSON on disk under `data/raw/<job_id>/`, plus `save_checkpoint` / `get_latest_checkpoint`.
- `ExtractionService._execute_scan`: stage state machine, heartbeat updates, background execution.
- respx-mocked tests for paging, 429 handling and retries.

## Week 3: Normalization and export (Days 15-21)

- Normalizer base class and `EnvelopeNormalizer` (flattens envelopes, including custom fields).
- `RecipientNormalizer`, `DocumentNormalizer`, `TemplateNormalizer`.
- `NormalizationService`, including the fix for datetimes not serializing into the JSONB result column.
- MinIO integration: one shared `MinioClient`, deterministic export paths `normalized/<job_id>/<table>.parquet` and `.json`.
- Normalization endpoints (run, status, results) and Week 3 milestone tests.
- Verified end to end: a scan was normalized to 5 envelopes, 7 recipients, 11 documents and 1 template, and exported to MinIO as Parquet and JSON. A raw-data guard returns 409 when raw files are missing.
- Details in `docs/week3_results.md`.

## Week 4: Operations, resilience, audit, verification (Days 22-28)

### Day 22: Maintenance endpoints
- `GET /api/maintenance/jobs` (filter by status and type).
- `POST /api/maintenance/recover-stale-jobs` (marks `running` jobs with no recent heartbeat as `failed`; supports `dry_run`).
- `GET /api/maintenance/failed-calls` and `POST /api/maintenance/failed-calls/{id}/resolve`.
- `POST /api/maintenance/cleanup` (removes old raw data; dry run by default; skips completed scans that were never normalized unless told otherwise).
- Verified live against the Docker stack with `scripts/call_api.py`.

### Day 23: Error handling and dead-letter queue
- Per-envelope failures that are not systemic (not 401/403, not rate limit, not network) are skipped and recorded in `failed_external_calls`; the scan continues and counts them as `<resource>_failed`.
- Systemic failures fail the job but leave it resumable from the exact index.
- `scan_runner` resume fix: duplicate starts are ignored while the heartbeat is fresh.

### Day 24: Audit trail
- `AuditService` (`log_event` never raises; `query` supports filters and paging).
- `GET /api/audit` with `job_id`, `action`, `actor`, `since`, `until`, `limit`, `offset` (HMAC protected).
- New events `scan_created`, `normalization_started`, `failed_call_recorded`; lifecycle events now go through the same service.
- Verified live: unfiltered, limit, job filter, action filter and offset paging.

### Day 25: Resume tests (`tests/test_resume.py`, 7 tests)
A fake DocuSign client whose failures fire once lets one test fail a scan and then resume it. Covered:
- failure mid-envelopes saves the checkpoint at the failure point;
- resume continues from the checkpoint and never refetches a saved page (`env_starts == [0, 2, 2, 4]`);
- resume mid-recipients calls only the remaining envelopes;
- DLQ rows and `*_failed` counters survive a resume and are not duplicated;
- a crash between the page write and the checkpoint creates no duplicate pages (the page is overwritten);
- a completed job is not re-run;
- a crashed worker is recovered by the maintenance endpoint and then resumed, with the full audit trail (`scan_started`, `job_recovered_stale`, `scan_resumed`, `scan_completed`).

### Day 26: End-to-end tests (`tests/test_e2e_pipeline.py`, 7 tests)
Everything runs for real except DocuSign (deterministic fake) and MinIO (in-memory dict):
- full pipeline: scan, normalize, export, validate row counts in the stored result and inside every exported Parquet and JSON object, check object paths, check the audit trail (all five events, each once, first and last correct);
- an interrupted-and-resumed scan produces the same counts and the same set of exports as a clean scan;
- normalization refuses an unfinished job and a job whose raw data is gone, and exports nothing in either case;
- re-running normalization is idempotent (objects overwritten, not duplicated);
- status and results endpoints before and after normalization;
- API error codes: 400, 404, 409.

### Days 27-28: Documentation and submission
- README.md rewritten for the final system (all endpoints, resume and recovery behavior, audit, troubleshooting, tests, limitations).
- DESIGN.md brought in line with the implementation (checkpoint cursor, dead-letter policy, crash-safety invariants mapped to tests, future work).
- Project write-up in `docs/WRITEUP.md`.
- This progress report finalized.

---

## Architecture notes

**Layout:** `app/{api,core,db,docusign,normalizers,services,utils}` and `tests/`.

**Scan stages:** envelopes, recipients, documents, templates. Each stage ends by saving a checkpoint that points at the next stage.

**Crash safety:**
- Raw page file is written first, checkpoint second, so a crash never skips data and a replay only overwrites.
- The checkpoint stores the stage, a cursor (`start_position` / `index`) and cumulative counts.
- `jobs.updated_at` doubles as the heartbeat; stale `running` jobs are recovered by the maintenance endpoint.
- Per-envelope stages read envelope ids from the files on disk, so resume does not depend on memory.

**Data flow:** DocuSign API, then raw JSON pages in `data/raw/<job_id>/`, then normalized tables in `jobs.result`, then Parquet and JSON in MinIO.

**API surface:** `/api/health` (public), `/api/validate-credentials`, `/api/scan` (including resume and cancel), `/api/normalization`, `/api/maintenance`, `/api/audit`. All except health are HMAC protected.

---

## Issues found and fixed along the way

| Issue | Cause | Fix |
|-------|-------|-----|
| `HTTP 500` on `POST /api/scan` status calls | A local `python.exe` held port 8000 and answered before Docker; `JobCheckpoint` had no `stage` / `counts` | Stopped the local process; added `stage` and `counts` properties to the model |
| Background scan could not authenticate after container recreate | `./secrets` was mounted under `minio` instead of `app` | Moved the mount to the `app` service |
| `TypeError` writing normalized data to JSONB | `datetime` values are not JSON serializable | `jsonable_encoder` before the commit |
| Two MinIO clients | A second client was created next to the existing one | Kept one client, extended it, removed the duplicate |
| Normalization returned zeros with `200` | Raw files were lost when the container was recreated before `./data` was mounted | Raw-data guard returns `409`; `./data` mounted |
| `S3Error` test failures | Constructor argument order differs between minio versions | Tests use keyword arguments |

---

## Known limitations and notes

- The HMAC signature covers method, path and body hash, but **not the query string**, and there is no nonce store, so a captured request could be replayed inside the time window. Low risk for this project; the fix is to sign path plus query and cache nonces.
- Audit events written by the background worker have `actor = null`, since there is no authenticated request at that point. Maintenance endpoints record the HMAC key id.
- Jobs created before Day 24 have no `scan_created` audit row.
- Normalized rows live in `jobs.result` (JSONB) and in MinIO, not in relational tables.
- The "already running" guard for normalization is per process.
- Raw pages depend on the mounted `./data` folder.
- One test job from 2026-11-05 is still `pending` and was never started.

---

## Test growth

| Checkpoint | Tests passing |
|------------|---------------|
| End of Day 4 (auth) | 24 |
| Day 18 (normalizers) | 85 |
| Day 19-21 applied | 129 |
| Week 3 complete | 136 |
| Day 24 (audit) | 165 |
| Day 25 (resume tests) | 172 |
| Day 26 (end-to-end tests) | **179** |

---

## Final submission checklist

| Item | Status |
|------|--------|
| `pytest -q` is green (179 passed, no skips) | Done |
| README.md and DESIGN.md match the code | Done |
| `docs/PROGRESS.md` and `docs/WRITEUP.md` final | Done |
| Unused and duplicate files removed | Pending (see cleanup list) |
| Fresh clone: `docker compose up -d --build`, `alembic upgrade head`, scan, normalize, check MinIO | Pending |
| `.env`, `secrets/` and `data/` confirmed ignored by git | Pending |
| Final commit and tag (for example `v1.0.0`) pushed | Pending |