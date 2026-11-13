# DocuSign Master Service: Design

Last updated: 2026-11-12 (final, end of Week 4)

## 1. Purpose

The service extracts eSignature data from DocuSign (envelopes, recipients, documents, templates), survives rate limits and crashes, normalizes the data into tables, and writes Parquet and JSON files to object storage. Clients drive it through a small HMAC-protected REST API.

## 2. Goals and non-goals

**Goals**
- Authenticate to DocuSign with JWT Grant.
- Page through large envelope sets without losing progress.
- Respect DocuSign rate limits (HTTP 429) with backoff.
- Resume interrupted scans from the last checkpoint, with no refetching and no duplicates.
- Isolate bad records so one failing envelope does not stop a scan.
- Normalize raw JSON into flat, queryable tables and export them to MinIO.
- Keep an audit trail and a record of every failed external call.

**Non-goals**
- A UI.
- Writing or sending envelopes in DocuSign.
- Multi-tenant user management (HMAC keys are the only client identity).

## 3. Architecture

```
Client --HMAC--> FastAPI (app/api)
                    |
        +-----------+-------------+------------------+
        v                         v                  v
  ScanRunner ──► ExtractionService   NormalizationService   Maintenance / Audit
        |             |                   |   |                  |
        v             v                   |   +--> MinIO         v
   JobService    DocuSign client          |       (Parquet,   Postgres
   (jobs,        (auth, paging,           |        JSON)      (jobs, checkpoints,
   checkpoints)  429 + retry)             v                    audit, failed calls)
                      |             Normalizers
                      v
              data/raw/<job_id>/  (raw JSON pages on disk)
```

| Layer | Folder | Responsibility |
|-------|--------|----------------|
| API | `app/api` | Routers, request validation, status codes |
| Core | `app/core` | HMAC verification, rate limiter, retry, dead-letter helper |
| Config | `app/config.py` | Settings from environment (pydantic-settings) |
| DB | `app/db` | SQLAlchemy models, sessions; Alembic migrations in `alembic/` |
| DocuSign | `app/docusign` | JWT Grant auth, API client, envelope and template calls, typed exceptions |
| Services | `app/services` | Extraction, scan runner and stages, normalization and export, job service, audit service, MinIO client |
| Normalizers | `app/normalizers` | Raw JSON to flat rows, one module per resource |
| Utils | `app/utils` | Atomic raw page storage, JSON/Parquet serializers |

## 4. Authentication

### 4.1 To DocuSign

- JWT Grant: the service signs a JWT with the RSA private key (impersonating the configured user) and exchanges it for an access token.
- The token is cached in memory and refreshed shortly before expiry.
- The userinfo call resolves the account and base URL; `POST /api/validate-credentials` exercises this whole path.
- `consent_required` errors are reported clearly so the one-time consent step can be redone.
- Tokens and keys are never logged.

### 4.2 To this service

HMAC request signing:
- Headers: `X-Key-Id` (`core` or `engineer`), `X-Timestamp` (Unix seconds), `X-Signature`.
- The signature is computed over timestamp, method, path and request body with the secret for that key id, and compared in constant time.
- Requests older than `HMAC_SIGNATURE_MAX_AGE` seconds are rejected.
- Two keys are valid at the same time so keys can be rotated with no downtime.
- `/api/health` is public; everything else is protected.

Known gaps (accepted for this project): the query string is not part of the signature, and there is no nonce store, so a captured request can be replayed inside the time window. The fix would be to sign `path?query` on both sides and keep a short-lived nonce cache.

## 5. Data model

Four tables, created by the Alembic migration.

| Table | Purpose |
|-------|---------|
| `jobs` | One row per scan run: type, status, parameters, error message, `result` (JSONB, holds normalized output), `updated_at` used as the heartbeat |
| `job_checkpoints` | Resume points: `job_id`, `resource_type` (the stage), `cursor` (JSONB) |
| `audit_logs` | `job_id`, `action`, `actor`, details, timestamp |
| `failed_external_calls` | Dead-letter rows: endpoint, envelope id, status, attempts, error, resolved flag |

**Checkpoint cursor.** The cursor holds the position within the stage (`start_position` and `page_number` for paged stages, `index` for per-envelope stages) and cumulative counts under `_counts`, for example `{"envelopes": 5, "recipients": 4, "recipients_failed": 1}`. The model exposes `stage` and `counts` as read-only properties so the API does not need extra columns.

**Normalized data.** Normalized rows are stored in `jobs.result` (JSONB) and exported to MinIO. This keeps the schema small and exports reproducible; relational tables for the normalized data are listed under future work.

## 6. Scan lifecycle

Statuses: `pending → running → completed | failed` (a job can also be cancelled).
Stages: `envelopes → recipients → documents → templates → completed`.

1. `POST /api/scan` creates a `pending` job (audit: `scan_created`) and returns `202`; a background task starts the scan (`scan_started`).
2. **Paged stages** (envelopes, templates) fetch one page, write it to `data/raw/<job_id>/<resource>/page_NNNNNN.json`, then save a checkpoint with the next `start_position`.
3. **Per-envelope stages** (recipients, documents) read the envelope ids back from the raw files on disk and call DocuSign once per envelope, checkpointing the index. Resume therefore does not depend on anything held in memory.
4. After each unit of work the heartbeat (`updated_at`) is refreshed.
5. On success the job becomes `completed` (`scan_completed`).
6. On failure the job becomes `failed`, and the checkpoint points at the exact place to continue.
7. `POST /api/scan/{id}/resume` (`scan_resumed`) continues from the latest checkpoint.

### 6.1 Crash-safety invariants

| Invariant | How it is achieved | Test |
|-----------|--------------------|------|
| A page is never skipped | Raw file is written first, checkpoint second | `test_failure_mid_envelopes_saves_checkpoint_at_failure_point` |
| A page is never duplicated | Page files are named by page number and written atomically (temp file + rename), so a re-write overwrites | `test_crash_between_page_write_and_checkpoint_creates_no_duplicates` |
| Saved work is not fetched again | Resume starts from the checkpoint cursor | `test_resume_continues_from_checkpoint_without_refetching_pages`, `test_resume_mid_recipients_only_fetches_remaining_envelopes` |
| Failures survive a resume | Dead-letter rows live in the database; `*_failed` counters live in the checkpoint; completed stages are not re-run | `test_resume_keeps_dlq_rows_and_failed_counters` |
| A finished job is final | Resume on a `completed` job does nothing | `test_completed_job_is_not_rerun` |
| A dead worker is recoverable | Stale `running` jobs are marked `failed`, then resumed | `test_crashed_worker_is_recovered_then_resumed` |

### 6.2 Stale-job recovery

A job in `running` whose `updated_at` is older than `JOB_CRASH_TIMEOUT_MINUTES` is treated as crashed. `POST /api/maintenance/recover-stale-jobs` marks it `failed` (`job_recovered_stale`) with a message that names the resume endpoint. The call supports `dry_run`. A duplicate start or resume is ignored while the heartbeat is fresh.

## 7. Envelope paging

- Call the envelope list endpoint with `from_date`, `start_position` and `count`.
- Advance `start_position` by the number of envelopes actually returned; stop when `totalSetSize` is reached or a page is empty.
- DocuSign returns numbers as strings; they are cast where needed.
- Drafts only appear when filtering by status `created`; the scan covers the default listing.

## 8. Rate limits, retries and the dead-letter queue

All DocuSign calls go through one wrapper so behavior is uniform:

- **429:** wait for `Retry-After` when present, otherwise exponential backoff with jitter, up to `DOCUSIGN_MAX_RETRIES_ON_429`.
- **5xx and network errors:** a bounded number of retries with backoff.
- **401:** refresh the token once and retry.
- **Non-retryable errors (400, 404, ...):** fail immediately.
- **Exhausted retries:** a typed exception is raised.

**Dead-letter policy (per-envelope stages).** A failure that is *not systemic* (not 401/403, not rate limiting, not a network error) is recorded in `failed_external_calls`, counted as `<resource>_failed`, and the scan continues with the next envelope. Systemic failures fail the job instead, because every following call would fail the same way. Payloads stored with a failed call are truncated to `DLQ_PAYLOAD_MAX_BYTES`. Operators review rows through `/api/maintenance/failed-calls` and close them with the resolve endpoint.

## 9. Normalization and export

- `NormalizationService` reads raw pages from disk and runs the four normalizers.
- It refuses jobs that are not `completed` (`409`) and jobs whose raw files are gone (`409`, instead of returning `200` with zeros).
- The result is committed to `jobs.result` first, then exported. A MinIO failure is audited and raised, the data is kept, and a re-run overwrites the same objects.
- Every table the normalizers return is exported; empty tables are skipped.
- Export paths are deterministic: `normalized/<job_id>/<table>.parquet` and `.json`.
- Parquet stores nested values (for example custom fields) as JSON strings to avoid schema errors on empty or mixed-shape dicts.
- Status and results endpoints read from MinIO, so no extra database column is needed.
- Datetimes are made JSON-safe (`jsonable_encoder`) before they reach the JSONB column.

## 10. API surface

| Endpoint | Purpose |
|----------|---------|
| `GET /api/health` | Liveness (public) |
| `POST /api/validate-credentials` | Verify DocuSign token and base URL |
| `POST /api/scan`, `GET /api/scan/{id}`, `POST /api/scan/{id}/resume`, `POST /api/scan/{id}/cancel` | Scan lifecycle |
| `POST /api/normalization/{id}`, `GET .../status`, `GET .../results` | Normalize and export |
| `GET /api/maintenance/jobs`, `POST .../recover-stale-jobs`, `GET .../failed-calls`, `POST .../failed-calls/{id}/resolve`, `POST .../cleanup` | Operations |
| `GET /api/audit` | Audit trail (filters: job, action, actor, time range, paging) |

Cleanup is a dry run by default and skips completed scans that were never normalized unless told otherwise, so raw data is not removed before it has been used.

## 11. Error handling and observability

- Typed exceptions for auth, rate limit, not-found and API errors.
- Structured logs; secrets are redacted.
- `audit_logs` for job-level events. `AuditService.log_event` never raises, so an audit failure cannot break real work.
- `failed_external_calls` for upstream failures.

## 12. Security

- Secrets (Integration Key, RSA key, HMAC keys, DB and MinIO credentials) come from environment variables and mounted files and are never committed.
- HMAC with a timestamp window protects against tampering (see 4.2 for the known gaps).
- The container runs as a non-root user.

## 13. Testing

179 tests; DocuSign and MinIO are faked, so the suite needs no network or Docker.

- **Unit:** auth, token caching, HMAC, retry and rate limiter, normalizers, serializers, raw storage.
- **Integration:** extraction paging and checkpoints, dead-letter handling, scan runner, maintenance, audit, MinIO client and export, normalization API.
- **Resume (`tests/test_resume.py`):** a scriptable fake DocuSign client whose failures fire once, so the same test can fail a run and then resume it. Covers every invariant in 6.1.
- **End to end (`tests/test_e2e_pipeline.py`):** real extraction service, raw files, normalizers, export and audit trail with an in-memory MinIO. Checks row counts in the stored result and inside each exported Parquet and JSON object, the audit trail, 409 guards, idempotent re-runs, and that an interrupted-and-resumed scan equals a clean scan.
- **Live checks:** the real sandbox returned `valid: true`; a live scan produced 5 envelopes, 7 recipients, 11 documents and 1 template, exported to MinIO.

## 14. Milestones

| Week | Scope | Status |
|------|-------|--------|
| 1 | Setup, sandbox, auth | Done |
| 2 | Envelope paging, rate limits, retries, scan engine | Done |
| 3 | Normalization and MinIO export | Done |
| 4 | Maintenance, DLQ, audit, resume and end-to-end tests, documentation | Done |

## 15. Risks and future work

- **Relational normalized tables:** store normalized rows in dedicated Postgres tables (upsert by DocuSign id) instead of one JSONB value per job.
- **Multi-worker safety:** replace the in-process "already running" guard with a database advisory lock or a job claim.
- **Raw storage:** move raw pages from local disk to MinIO so scans survive loss of the `data/` volume.
- **HMAC:** include the query string in the signature and add a nonce cache.
- **Queueing:** run scans on a proper worker queue (for example a task runner) instead of FastAPI background tasks.
- **Parquet schema evolution** if DocuSign adds fields.
- **Token refresh** across concurrent jobs should be serialized if scans are ever run in parallel.