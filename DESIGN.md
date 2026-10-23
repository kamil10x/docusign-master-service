# Design

## Overview
One paragraph on what the service does and who uses it.

## Architecture
Client → FastAPI → (MinIO for files, PostgreSQL for metadata) → Extraction step

## Data model
documents: id (UUID), filename, content_type, size, storage_key,
status (uploaded | processing | done | failed), created_at, updated_at

## API (planned)
- POST /documents: upload a file
- GET /documents/{id}: fetch metadata and status
- GET /documents: list documents

## Processing flow
1. Client uploads a file.
2. API validates type and size.
3. File is stored in MinIO, and a DB row is created with status `uploaded`.
4. Extraction runs and the result is saved.
5. Status moves to `done` or `failed`.

## Decisions and trade-offs
- MinIO for file storage: S3-compatible, easy to run locally.
- PostgreSQL for metadata: relational and queryable.
- Docker Compose to keep the setup reproducible.

## Open questions
(Anything the spec leaves unclear.)