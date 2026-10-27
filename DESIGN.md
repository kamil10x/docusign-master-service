# DocuSign Master Service: Design

Last updated: Oct 27, 2026 (end of Week 1)

## 1. Purpose

The service extracts eSignature data from DocuSign (envelopes, recipients, documents, templates), survives rate limits and crashes, normalizes the data into relational tables, and writes Parquet files to object storage. Clients drive it through a small HMAC-protected REST API.

## 2. Goals and non-goals

**Goals**
- Authenticate to DocuSign with JWT Grant and resolve the account base URL.
- Page through large envelope sets without losing progress.
- Respect DocuSign rate limits (HTTP 429) with backoff.
- Resume interrupted scans from the last checkpoint.
- Normalize raw JSON into queryable Postgres tables.
- Export Parquet to MinIO.
- Record an audit trail and every failed external call.

**Non-goals**
- A UI.
- Writing or sending envelopes in DocuSign.
- Multi-tenant user management (HMAC keys are the only client identity).

## 3. Architecture

```
Client --HMAC--> FastAPI (app/api)
                    |
                    v
               JobService (app/services)
                 |        |         |
                 v        v         v
        DocuSign client  Postgres   MinIO
        (app/docusign)   (jobs,     (Parquet)
                         checkpoints,
                         audit, failures)
                 |
                 v
          Normalizers (app/normalizers) --> normalized tables
```

| Layer | Folder | Responsibility |
|-------|--------|----------------|
| API | `app/api` | Routers, request validation, auth dependency |
| Core | `app/core` | Settings, HMAC verification |
| DB | `app/db` | SQLAlchemy models, sessions, Alembic migrations |
| DocuSign | `app/docusign` | Auth client, userinfo, API calls, retry wrapper |
| Services | `app/services` | `JobService`: job lifecycle, checkpoints, orchestration |
| Normalizers | `app/normalizers` | Raw JSON to normalized rows |
| Utils | `app/utils` | Shared helpers |

## 4. Authentication

### 4.1 To DocuSign (implemented, Week 1)

- JWT Grant: the service signs a JWT with the RSA private key (impersonating the configured user) and exchanges it for an access token.
- The token is cached in memory and refreshed shortly before expiry.
- After obtaining a token, the userinfo call returns the account and its base URL; `validate_credentials` runs this whole path.
- `consent_required` errors are surfaced clearly so the one-time consent step can be redone.
- Tokens and keys are never logged.

### 4.2 To this service (implemented, Week 1)

HMAC request signing:
- Each request carries a signature, a timestamp, and a nonce.
- The timestamp must fall within a clock-skew window.
- Each nonce is accepted once; replays are rejected.
- Two keys are valid at the same time so keys can rotate with no downtime.
- Signatures are compared in constant time.

> Fill in the exact header names, signing string, and skew window from `app/core`.

## 5. Data model

Four tables, created by the first Alembic migration.

| Table | Purpose |
|-------|---------|
| `jobs` | One row per scan or normalization run: type, status, parameters, timestamps, error summary |
| `job_checkpoints` | Resume points per job: resource type, last position or cursor, updated time |
| `audit_logs` | Who did what and when (job created, started, failed, completed) |
| `failed_external_calls` | Every DocuSign call that exhausted retries: endpoint, status, attempts, error |

Normalized tables (Week 3) will hold envelopes, recipients, documents, and templates, keyed by DocuSign IDs so reruns are idempotent (upsert, not insert).

> Add the real column lists from your models once Week 3 begins.

## 6. Job lifecycle

1. A client creates a job through the API; `JobService` stores it as `pending`.
2. The job runs and moves to `running`.
3. After each page, the service writes the data and updates the checkpoint in the same transaction.
4. On success the job becomes `completed`; on an unrecoverable error it becomes `failed` and the failure is logged.
5. A failed or interrupted job can be resumed. It reads its checkpoint and continues from the next position instead of restarting.

## 7. Envelope paging (Week 2)

- Use the envelopes list endpoint with `from_date`, `start_position`, and `count`.
- Advance `start_position` by the number of envelopes actually returned, and stop when `totalSetSize` is reached or a page is empty.
- Treat numeric fields in responses as strings and cast them.
- Expose paging as a generator so callers process and checkpoint one page at a time.

## 8. Rate limits and retries (Week 2)

All DocuSign calls go through one request wrapper so the behavior is uniform:

- **429:** wait for `Retry-After` when present; otherwise exponential backoff with jitter. Also watch DocuSign's rate-limit response headers to slow down before hitting the limit.
- **401:** refresh the token once and retry.
- **5xx and network errors:** a small, bounded number of retries.
- **Exhausted retries:** raise a typed exception and write a `failed_external_calls` row.

## 9. Normalization and storage (Weeks 3 and 4)

- Normalizers convert raw JSON to flat rows, one module per resource type.
- Writes are upserts keyed by DocuSign IDs.
- Parquet files are uploaded to MinIO under a predictable path such as `<resource>/<job_id>/part-<n>.parquet`, so a job's output is easy to find and clean up.

## 10. API surface

| Endpoint | Purpose | Status |
|----------|---------|--------|
| `GET /api/health` | Liveness | Done |
| `POST /api/validate-credentials` | Verify token and base URL | Done |
| `/api/scan/*` | Create, inspect, and resume scan jobs | Week 2 |
| `/api/normalization/*` | Run normalization | Week 3 |
| `/api/maintenance/*` | Cleanup and housekeeping | Week 4 |

## 11. Error handling and observability

- Typed exceptions for auth, rate-limit, and API errors.
- Structured logs with a job ID on every line; secrets are redacted.
- `audit_logs` for job-level events; `failed_external_calls` for upstream failures.

## 12. Security

- Secrets (Integration Key, RSA key, HMAC keys, DB and MinIO credentials) come from environment variables and are never committed.
- HMAC with timestamp and nonce protects against tampering and replay.
- The container runs as a non-root user.

## 13. Testing

- Unit tests for token caching, JWT Grant, and HMAC (signature, timestamp window, nonce replay, key rotation).
- HTTP is mocked in unit tests; one manual check against the real sandbox confirmed `valid: true`.
- Week 2 adds tests for paging, 429 handling, and retry exhaustion.

## 14. Milestones

| Week | Scope | Status |
|------|-------|--------|
| 1 | Setup, sandbox, auth (valid token and base URL) | Done |
| 2 | Envelope paging, rate limits | Next |
| 3 | Normalization tables | Planned |
| 4 | Parquet upload, error handling, resume, tests, final write-up | Planned |

## 15. Open questions and risks

- Sandbox data volume may be too small to exercise paging; seed extra envelopes for testing.
- Token refresh during a long scan must not race across concurrent jobs.
- Parquet schema evolution if DocuSign adds fields.