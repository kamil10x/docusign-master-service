# DocuSign Master Service

Pulls envelope data (Envelopes, Recipients, Documents, Templates) out of a
DocuSign account on demand, respects DocuSign rate limits, checkpoints
progress so runs can resume, normalizes the data into tables, and uploads
the result to MinIO. Called by a Coordinator service over signed HTTP.

## Stack
Python · FastAPI · PostgreSQL · MinIO · Docker

## Setup
1. Clone the repo and create a virtualenv: `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in the values.
4. Start dependencies: `docker compose up -d`
5. Run the API: `uvicorn app.main:app --reload`

## Configuration
| Variable | Purpose |
|---|---|
| DOCUSIGN_INTEGRATION_KEY | DocuSign app integration key |
| DOCUSIGN_USER_ID | API user GUID |
| DOCUSIGN_PRIVATE_KEY_PATH | Path to RSA private key (JWT Grant) |
| DOCUSIGN_AUTH_SERVER | account-d.docusign.com (sandbox) |
| MINIO_ENDPOINT / MINIO_ROOT_USER / MINIO_ROOT_PASSWORD / MINIO_BUCKET | Object storage |
| DATABASE_URL | PostgreSQL connection string |

## Running tests
`pytest`

## API
See DESIGN.md for the full endpoint list. Interactive docs at /docs.

## Status
(Updated as milestones complete.)