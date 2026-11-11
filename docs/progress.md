# DocuSign Master Service: Progress Report

**Status as of 2026-11-10: Day 24 of 28 complete (Weeks 1-3 done, Week 4 in progress).**
**Test suite: 165 passing.**

A FastAPI service that extracts DocuSign eSignature data (envelopes, recipients, documents, templates), survives rate limits and crashes through checkpointing, normalizes the data into tables, and exports it to MinIO as Parquet and JSON.

Stack: Python 3.13, FastAPI, PostgreSQL, SQLAlchemy + Alembic, MinIO, Docker Compose, pytest.

---

## Summary by week

| Week | Milestone | Status |
|------|-----------|--------|
| 1 | Setup, sandbox, authentication | Done (2026-10-28) |
| 2 | Envelope paging, rate limits, retries, scan engine | Done |
| 3 | Normalization tables, MinIO export | Done (2026-11-08) |
| 4 | Maintenance, error handling, audit, resume tests, e2e, docs | In progress (Day 24 done) |

---

## Week 1: Setup and authentication (Days 1-7)

- Project scaffold with FastAPI, health endpoint (`/api/health`), Docker and Compose wiring (app, Postgres, MinIO).
- MinIO set up and reachable from the app.
- Database models and Alembic migration: `jobs`, `job_checkpoints`, `audit_logs`, `failed_external_calls`; `JobService` skeleton.
- DocuSign sandbox set up: integration key, RSA keypair, consent granted.
- `DocuSignAuthClient.get_access_token` using JWT Grant, with token caching.
- `POST /api/validate-credentials`, verified against the real sandbox (returned `valid: true`).
- HMAC request authentication via middleware, with unit tests.
- README.md and DESIGN.md written.

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
- `RecipientNormalizer` (signers, carbon copies, etc., with status), `DocumentNormalizer`, `TemplateNormalizer`.
- `NormalizationService`, including the fix for datetimes not serializing into the JSONB result column.
- MinIO integration: one shared `MinioClient`, deterministic export paths `normalized/<job_id>/<table>.parquet` and `.json`.
- Normalization endpoints and Week 3 milestone tests.
- Verified end to end: a scan was normalized to 5 envelopes, 7 recipients, 11 documents and 1 template, and exported to MinIO as Parquet and JSON. A raw-data guard returns 409 when raw files are missing.
- Results written up in `docs/WEEK3_RESULTS.md`.

## Week 4: Operations, resilience, audit (Days 22-24 done)

### Day 22: Maintenance endpoints
- `GET /api/maintenance/jobs` (filter by status and type)
- `POST /api/maintenance/recover-stale-jobs` (marks `running` jobs with no recent heartbeat as `failed`; supports `dry_run`)
- `GET /api/maintenance/failed-calls` and `POST /api/maintenance/failed-calls/{id}/resolve`
- `POST /api/maintenance/cleanup` (removes old raw data; dry-run by default; skips completed scans that were never normalized unless told otherwise)
- Verified live against the Docker stack with `scripts/call_api.py`.

### Day 23: Error handling and dead-letter queue
- Per-envelope failures that are not systemic (not 401/403, not rate-limit, not network errors) are skipped and recorded in `failed_external_calls`; the scan continues and counts them as `<resource>_failed`.
- Systemic failures fail the job but leave it resumable from the exact index.
- `scan_runner` resume fix applied: duplicate starts are ignored while the heartbeat is fresh.

### Day 24: Audit trail
- `AuditService` (`log_event` never raises, so a logging failure cannot break real work; `query` supports filters and paging).
- `GET /api/audit` with `job_id`, `action`, `actor`, `since`, `until`, `limit`, `offset` (HMAC protected).
- New audit events: `scan_created`, `normalization_started`, `failed_call_recorded`; the existing lifecycle events now go through the same service.
- 13 new tests; full suite at 165 passing.
- Verified live: unfiltered, limit, job filter, action filter and offset paging all returned correct results.

---

## Architecture notes

**Layout:** `app/{api,core,db,docusign,normalizers,services,utils}` and `tests/`.

**Scan stages:** envelopes, then recipients, then documents, then templates. Each stage ends by saving a checkpoint that points at the next stage.

**Crash safety:**
- Raw page file is written first, checkpoint second, so a crash never skips data.
- The checkpoint stores the stage, a cursor (`start_position` / `index`) and cumulative counts.
- `jobs.updated_at` doubles as the heartbeat; stale `running` jobs are recovered by the maintenance endpoint.
- Per-envelope stages read envelope IDs from the files on disk, so resume does not depend on memory.

**Data flow:** DocuSign API, then raw JSON pages in `data/raw/<job_id>/`, then normalized tables in `jobs.result`, then Parquet and JSON in MinIO.

**API surface:** `/api/health` (public), `/api/validate-credentials`, `/api/scan` (including resume), `/api/normalization`, `/api/maintenance`, `/api/audit`. All except health are protected by HMAC.

---

## Known limitations and notes

- The HMAC signature covers method, path and body hash, but **not the query string**. A captured signed request could be replayed within the time window with different query parameters. Low risk for this project; fix would be to sign path plus query on both client and server.
- Audit events written by the background worker (scan lifecycle) have `actor = null`, since there is no authenticated request at that point. Maintenance endpoints record the HMAC key ID.
- Jobs created before Day 24 have no `scan_created` audit row.
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

---

## Remaining work

| Day | Task |
|-----|------|
| 25 | Resume tests (resume from paged stage, per-envelope stage, after 429/network failure, skip-then-resume, no duplicate pages, resume endpoint, audit trail) |
| 26 | End-to-end test |
| 27 | README and DESIGN.md final updates |
| 28 | Final write-up and submission |