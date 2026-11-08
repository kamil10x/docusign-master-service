# DocuSign Master Service – End-to-End Pipeline Verification Report

**Status:** All Blockers Resolved / Pipeline Complete

---

## 1. Completed Checklist

| Priority | Task | Status | Verification Details |
| :--- | :--- | :--- | :--- |
| **1** | Identify and fix `HTTP 500` exception | **Completed** | Terminated rogue local `python3.13.exe` process hijacking port `8000` on host; added `.stage` and `.counts` properties to `JobCheckpoint` model in `app/db/models.py`. |
| **2** | `POST /api/scan` returning `202` | **Completed** | Signed HMAC request returns `202 Accepted` and creates `pending` scan job (`d9f3968f-feda-47bf-a4c7-dd02a2192f7a`). |
| **3** | Verify background extraction | **Completed** | Mounted `secrets/private.key` into `app` container; `run_scan_in_background` authenticated via DocuSign JWT Grant and completed in ~8.5 seconds. |
| **4** | Verify envelopes, recipients, documents, and templates stages | **Completed** | Extracted **5 envelopes**, **5 recipient pages**, **5 document pages**, and **1 template** page into raw storage (`data/raw/{job_id}`). |
| **5** | Verify checkpoint creation and resume | **Completed** | `GET /api/scan/{job_id}` returns `200 OK` with `stage: "completed"` and cumulative `_counts` across all stages. |
| **6** | Complete normalization pipeline | **Completed** | Synced `jsonable_encoder` fix in `NormalizationService` to serialize `datetime` fields cleanly into PostgreSQL `JSONB` (`Job.result`). |
| **7** | Test normalized output and storage | **Completed** | `POST /api/normalization/{job_id}` returned `200 OK` with **5 envelopes**, **7 recipients**, **11 documents**, and **1 template** stored in `jobs.result` and recorded in `audit_logs`. |
| **8** | Run the full test suite | **Completed** | `python -m pytest -v` executed **85 tests — 85 passed (100%)**. |

---

## 2. Root Causes Identified & Fixed Today

1. **Port `8000` Collision on Host:** A lingering host `python3.13.exe` process (`PID 39040`) was intercepting requests on `127.0.0.1:8000` before they reached the Docker container.
2. **`JobCheckpoint` Property Mapping:** `_job_view` in `app/api/scan.py` accessed `checkpoint.stage` and `checkpoint.counts`, whereas `JobCheckpoint` stored those values in `resource_type` and `cursor["_counts"]`. Added `@property` accessors on `JobCheckpoint`.
3. **Container Volume Mount for Secrets:** `docker-compose.yml` had `./secrets:/app/secrets:ro` mounted under `minio` instead of `app`, causing `DOCUSIGN_PRIVATE_KEY_PATH` lookups to fail in background tasks after container recreation.
4. **JSONB `datetime` Serialization:** Synced `jsonable_encoder(normalized_data)` into the container's `app/services/normalization_service.py` so PostgreSQL `JSONB` updates succeed without `TypeError`.