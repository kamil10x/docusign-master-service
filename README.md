# DocuSign Master Service

A FastAPI service that pulls eSignature data from DocuSign (envelopes, recipients, documents, templates), handles rate limits and resumable scans, normalizes the data into PostgreSQL tables, and stores Parquet output in MinIO.

Design details live in [DESIGN.md](DESIGN.md).

## Status

| Week | Milestone | Status |
|------|-----------|--------|
| 1 | Setup, sandbox, auth (valid token + base URL) | Done |
| 2 | Envelope paging + rate-limit handling | Next |
| 3 | Normalization tables | Planned |
| 4 | Parquet upload, error handling, resume, tests, submission | Planned |

### Week 1 milestone

The service can authenticate against the DocuSign developer sandbox using the JWT Grant flow, cache the access token, and resolve the account's base URL through the userinfo call. `POST /api/validate-credentials` confirms this end to end and returns `valid: true` against the real sandbox.

## Tech stack

Python, FastAPI, PostgreSQL (SQLAlchemy + Alembic), MinIO, Docker.

## Project layout

```
app/
  api/          # routers: health, validate-credentials, scan, normalization, maintenance
  core/         # settings, HMAC auth
  db/           # SQLAlchemy models, session
  docusign/     # DocuSignAuthClient (JWT Grant, token cache), userinfo
  normalizers/  # (Week 3)
  services/     # JobService
  utils/
tests/
```

## Setup

### 1. Prerequisites

- Python 3.11+ (adjust to your version)
- Docker and Docker Compose
- A DocuSign developer sandbox account with an Integration Key, an RSA keypair, and one-time user consent granted

### 2. Configure environment

Copy the example file and fill it in:

```
cp .env.example .env
```

| Variable | Purpose |
|----------|---------|
| `DOCUSIGN_INTEGRATION_KEY` | Integration Key (client ID) of your sandbox app |
| `DOCUSIGN_USER_ID` | API username (GUID) of the impersonated user |
| `DOCUSIGN_ACCOUNT_ID` | Sandbox account ID |
| `DOCUSIGN_AUTH_SERVER` | `account-d.docusign.com` for the sandbox |
| `DOCUSIGN_PRIVATE_KEY_PATH` | Path to the RSA private key (never commit this file) |
| `HMAC_KEYS` | Active HMAC signing keys (two supported, for rotation) |
| `DATABASE_URL` | PostgreSQL connection string |
| `MINIO_*` | MinIO endpoint, access key, secret key, bucket |

> Verify these names against your own `.env.example` and `app/core/config.py`; edit this table to match.

### 3. Run

```
docker compose up --build
```

Apply migrations:

```
alembic upgrade head
```

The API is then available at `http://localhost:8000` (interactive docs at `/docs`).

## Authentication

### DocuSign

`DocuSignAuthClient.get_access_token()` signs a JWT with the RSA private key and exchanges it for an access token using the JWT Grant flow. The token is cached in memory and refreshed shortly before it expires. Tokens are never logged.

### Calling this service (HMAC)

Requests to protected endpoints must be signed. Each request carries a signature, a timestamp, and a nonce:

- The timestamp must be within the allowed clock-skew window.
- A nonce can be used only once; replays are rejected.
- Two keys are accepted at the same time so keys can be rotated without downtime.

See `app/core` for the exact header names and signing string.

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Liveness check |
| `POST /api/validate-credentials` | Authenticates to DocuSign and returns whether the credentials are valid (token + base URL resolved) |
| `/api/scan/*` | Scan jobs (Week 2+) |
| `/api/normalization/*` | Normalization jobs (Week 3) |
| `/api/maintenance/*` | Maintenance operations (Week 4) |

## Database

Tables: `jobs`, `job_checkpoints`, `audit_logs`, `failed_external_calls`. Migrations are managed with Alembic.

## Tests

```
pytest
```

Auth, token caching, and HMAC behavior are covered by unit tests (24 passing as of Oct 26).

## Security notes

- Never commit `.env` or the RSA private key.
- Access tokens and HMAC keys are not written to logs.