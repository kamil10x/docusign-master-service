# DocuSign Master Service: Project Write-up

## 1. The problem

Build a service that pulls eSignature data out of DocuSign (envelopes, recipients, documents, templates) reliably enough to run against large accounts. Three things make that hard: DocuSign rate-limits callers with HTTP 429, a long extraction will eventually be interrupted, and the raw JSON is nested and inconsistent (numbers as strings, many recipient types). The service therefore has to extract in pages, back off when told to, resume without losing or repeating work, and turn the raw data into flat tables that can be exported as Parquet.

## 2. What was built

A FastAPI service backed by PostgreSQL and MinIO, run with Docker Compose.

1. **Extraction.** `POST /api/scan` starts a background scan that walks four stages (envelopes, recipients, documents, templates), writes each raw page to disk and saves a checkpoint.
2. **Normalization and export.** `POST /api/normalization/{job_id}` converts the raw pages with four normalizers, stores the result, and exports every table to MinIO as Parquet and JSON.
3. **Operations.** Maintenance endpoints find and recover stuck jobs, review and resolve failed external calls, and clean up old raw data. An audit endpoint records what happened to each job.
4. **Security.** All routes except health require an HMAC signature; two keys can be live at once for rotation.

## 3. Key design decisions

| Decision | Why | Trade-off |
|----------|-----|-----------|
| Write the raw page first, checkpoint second | A crash can only cause a page to be written again (overwritten), never skipped or duplicated | A tiny amount of repeated work after a crash |
| Per-envelope stages read ids from files on disk | Resume does not depend on in-memory state or on re-running earlier stages | Requires the raw folder to survive |
| Dead-letter queue for non-systemic failures, fail the job for systemic ones | One corrupt envelope should not stop a scan of thousands, but a bad token would fail every call | Operators must review the dead-letter table |
| `jobs.updated_at` as the heartbeat | No extra table or service; stale `running` jobs are easy to find | Relies on the worker refreshing it |
| Commit normalized data before exporting | A MinIO outage never loses work; a re-run overwrites fixed paths | Normalized rows sit in one JSONB value per job |
| Deterministic export paths | Idempotent re-runs, easy lookup and cleanup, status read straight from MinIO | None significant |
| One shared MinIO client | Avoids two diverging implementations | None |
| Guards return 409 instead of `200` with zeros | An empty result must never look like a successful one | Extra checks in the service |

## 4. Reliability story

The system is designed around the question "what happens if it dies right here?"

- **Mid-page:** the page was not written and the checkpoint was not advanced; resume refetches that one page.
- **After the page write, before the checkpoint:** the page file exists, the checkpoint is old; resume rewrites the same page number over it.
- **Mid-recipients or mid-documents:** the checkpoint index points at the next envelope; resume calls only the remaining ones.
- **Worker killed while `running`:** the heartbeat goes stale; the recovery endpoint marks the job `failed` and names the resume endpoint.
- **Rate limited:** the call waits for `Retry-After` (or backs off with jitter) and retries, within a bounded budget.
- **Upstream outage on one envelope:** the failure is recorded, counted and skipped; the scan finishes and the failures can be reviewed later.
- **MinIO down during export:** data is already committed, the failure is audited, and re-running is safe.

Each of these has an automated test.

## 5. Testing approach

179 tests run without network, Docker or credentials: DocuSign is replaced by fakes (respx mocks for HTTP-level tests, a scripted client for service-level tests) and MinIO by an in-memory implementation that inherits the real path helpers, so object paths in tests are the real ones.

Two suites carry most of the confidence:

- **Resume tests (7).** A fake client whose failures fire once, so one test can fail a run and resume it. They assert on observable effects: which positions were fetched (`[0, 2, 2, 4]`), which envelopes were called, how many raw pages exist, how many dead-letter rows exist, and which audit events were written.
- **End-to-end tests (7).** The real extraction service, raw storage, normalizers, export and audit trail run together. They validate row counts in the stored result and inside each exported Parquet and JSON object, and prove that an interrupted-and-resumed scan produces the same output as a clean one.

Live checks complement the mocks: the real sandbox returned `valid: true` for credentials, and a live scan of the sandbox account produced 5 envelopes, 7 recipients, 11 documents and 1 template, exported to MinIO and read back from Parquet.

## 6. Results

| Measure | Result |
|---------|--------|
| Automated tests | 179 passed |
| Live scan (sandbox) | 5 envelopes, 7 recipients, 11 documents, 1 template |
| Exported objects per job | 8 (Parquet and JSON for each of 4 tables) |
| Live scan duration | about 8.5 seconds |
| Resume correctness | No refetched pages, no duplicate pages, identical output to a clean run |

## 7. Problems met and what they taught

- **A local process answering on port 8000** produced confusing `500` responses that looked like an application bug. Lesson: check what is actually bound to the port before debugging code.
- **The RSA key mounted into the wrong container** broke background authentication only after a container was recreated. Lesson: verify mounts per service, and test from a clean `docker compose up`.
- **Silent success with empty data.** Normalization returned `200` with zeros after raw files were lost. This led to the raw-data guard and the rule that empty must never look like success.
- **Datetimes in JSONB.** Fixed by encoding with `jsonable_encoder` before the commit, and covered by tests.
- **Duplicate modules.** A second MinIO client appeared next to the original. Lesson: search for an existing implementation before adding one.

## 8. Limitations and future work

- Normalized rows are stored in `jobs.result` and MinIO, not in relational tables. A natural next step is dedicated tables with upserts keyed by DocuSign id.
- The "already running" guard is per process; multiple workers need a database lock or job claim.
- Raw pages are on local disk; moving them to MinIO would remove the dependency on the `data/` volume.
- The HMAC signature excludes the query string and there is no nonce cache.
- Scans use FastAPI background tasks; a worker queue would give better isolation and scaling.

## 9. How to verify

```bash
pytest -q                                          # 179 passed
docker compose up -d --build
docker compose exec app alembic upgrade head
curl http://localhost:8000/api/health
python call_scan.py                                # start a scan, note the job_id
python -m scripts.call_normalization <job_id>      # normalize and export
python -m scripts.call_normalization <job_id> results
```

See `README.md` for configuration and the full API, `DESIGN.md` for the design, and `docs/PROGRESS.md` for the day-by-day record.