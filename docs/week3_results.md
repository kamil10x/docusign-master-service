# Week 3 Results: Normalization and MinIO Export

**Date:** 2026-11-08 (Days 18-21)
**Status:** Week 3 complete. All tests pass and the full pipeline was verified end to end.

---

## 1. What was built

| Day | Deliverable | Where |
|---|---|---|
| 18 | NormalizationService (read raw pages, run normalizers, store result), `datetime` JSONB bug fixed | `app/services/normalization_service.py` |
| 19 | MinIO object helpers: upload, download, exists, list, path convention | `app/services/minio_client.py` |
| 19 | JSON and Parquet serializers (datetime, Decimal, UUID, nested custom fields) | `app/utils/serializers.py` |
| 19 | Export of every normalized table to MinIO as Parquet + JSON | `app/services/normalization_export.py` |
| 20 | Normalization endpoints: run, status, results | `app/api/normalization.py` |
| 20 | Helper for signed API calls | `scripts/call_normalization.py` |
| 21 | Tests for serializers, MinIO client, export, service and API | `tests/test_*.py` |
| 21 | Guard: a completed job with no raw files returns 409 instead of a `200` with zeros | service + API |

MinIO object layout: `normalized/<job_id>/<table>.parquet` and `normalized/<job_id>/<table>.json`.

---

## 2. Test results

| Point in time | Result |
|---|---|
| Start of Week 3 work (Day 18) | 85 passed |
| After Day 19-21 code | 129 passed |
| After adding the export test file | 134 passed |
| After the raw-data guard | **136 passed** |

---

## 3. End-to-end verification

A new scan (`from_date` 2024-01-01) was started, then normalized.

| Item | Value |
|---|---|
| Job id | `9c62fe55-9316-4d2b-bb96-43df5f32b987` |
| Raw pages written | envelopes 1, recipients 5, documents 5, templates 1 |
| Normalized records | envelopes **5**, recipients **7**, documents **11**, templates **1** |
| Files in MinIO | 8 (a `.parquet` and a `.json` for each of the 4 tables) |
| Status endpoint | `normalized: true`, `exports_ready: true` |
| Results endpoint | bucket `docusign-documents`, all 4 tables with both formats |
| Parquet read-back | `envelopes.parquet` read from MinIO: 5 rows, 14 columns, `custom_fields` stored as JSON text |
| Re-run on the same job | `200`, same counts, files overwritten (safe to repeat) |

Error-path checks:

| Request | Result |
|---|---|
| Unknown job id (`0000...`) | `404 Job not found` |
| Job still `pending` | `409 Normalization can only run after extraction is completed.` |
| Completed job with no raw files (`d9f3968f...`) | `409 No raw extraction data found for job ...` |
| Request without a valid HMAC signature | `401` (covered by an automated test) |

---

## 4. Problems found and how they were fixed

| Problem | Cause | Fix |
|---|---|---|
| Two MinIO clients in the repo | A second client was created next to the existing `app/services/minio_client.py` | Kept one client, extended it, deleted the duplicate |
| Wrong config import in the new client | Settings live in `app/config.py`, not `app/core/config.py` | New code uses `app.config.settings` |
| Normalization returned all zeros with `200` | Old completed jobs had lost their raw files (container recreated before `./data` was mounted) | Added the raw-data guard; verified with a fresh scan |
| `Server disconnected` on one call | Request sent while the app container was still restarting | Waited for startup, call succeeded |
| Placeholder path in the Parquet read command | `<job_id>` / `C:\path\...` were not replaced | Used the real job id and read from MinIO directly |
| `S3Error` test failures | Constructor argument order differs between minio versions | Tests now use keyword arguments |

---

## 5. Design decisions

- **Export after the DB commit.** A MinIO failure never loses normalized data; it is audited and raised, and a re-run overwrites the same objects.
- **Export every table the normalizers return**, not a fixed list. Empty tables are skipped.
- **Parquet stores nested values as JSON strings** to avoid pyarrow errors on empty or mixed-shape dicts.
- **Status and results are read from MinIO**, so no new database column or migration was needed.
- **Endpoint returns counts and paths by default**; `?include_data=true` returns the full rows.

---

## 6. Known limitations

- The "already running" guard is per process (needs a database lock for multiple workers).
- Normalized rows are stored in `Job.result`, replacing the scan job's earlier result value.
- Raw pages depend on the mounted `./data` folder.

---

## 7. Next: Week 4

| Day | Task |
|---|---|
| 22 | `/api/maintenance`: stuck-job detection, cleanup of old raw and normalized files |
| 23 | Error handling: failed DocuSign and MinIO calls to the dead-letter table, with retries |
| 24 | Resume tests: interrupted scan continues from its checkpoint |
| 25 | `/api/audit` and `/api/validate-credentials` polish, final test pass |
| 26 | End-to-end test: scan, normalize, export (mocked DocuSign) |
| 27 | README and DESIGN.md update |
| 28 | Write-up and final submission checklist |