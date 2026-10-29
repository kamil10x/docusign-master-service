# DocuSign Test Envelope Results

## 1. Overview

This document records verification results for DocuSign sandbox envelope listing, retrieval, pagination, draft status filtering, rate limiting, retry handling, recipients, documents, and templates.

- **Project:** `docusign-master-service`
- **Environment:** DocuSign Sandbox
- **Roadmap coverage:** Day 8, Day 9, and subsequent endpoint implementation and verification

## 2. Test Envelope Seeding

**Script:** `scripts/seed_envelopes.py`

Six test envelopes were created in the DocuSign sandbox.

| # | Envelope ID | Status | Description |
|---|---|---|---|
| 1 | `a69b2fc7-e174-8732-8198-7695aea41bda` | sent | Test envelope 1 |
| 2 | `45d72d11-439d-8fd4-81de-cc8741af1b3d` | sent | Test envelope 2 |
| 3 | `eba92921-8c70-865f-800e-8107ebaa1b5e` | sent | Test envelope 3 |
| 4 | `a7dd2959-06ab-8528-8007-5fb5caa81b8e` | sent | Test envelope 4 |
| 5 | `77042f80-d085-86de-8041-e3e654ad1b93` | sent | Test envelope 5 (two documents) |
| 6 | `d2d22486-427d-820e-8137-5eb591ad1bf0` | created | Test envelope 6 (draft) |

**Result:** Six test envelopes were created successfully.

## 3. Individual Envelope Retrieval

**Verification script:** `scripts/verify_envelopes.py`

Each of the six envelopes was retrieved individually using its envelope ID.

| Test | Result |
|---|---|
| Retrieve envelope 1 | PASS |
| Retrieve envelope 2 | PASS |
| Retrieve envelope 3 | PASS |
| Retrieve envelope 4 | PASS |
| Retrieve envelope 5 | PASS |
| Retrieve envelope 6 (draft) | PASS |
| Total envelopes verified | 6/6 |

The five sent envelopes and the draft envelope were confirmed through individual retrieval.

## 4. Date-Range and Pagination Verification

**Verification script:** `scripts/verify_envelope_pagination.py`

**Command:** `python -m scripts.verify_envelope_pagination`

| Test | Result |
|---|---|
| Date-range listing | PASS |
| Sent envelopes returned | 5 |
| Pagination page size | 2 |
| Pages fetched | 3 |
| Page distribution | 2 + 2 + 1 |
| Unique envelopes retrieved | 5 |
| Duplicate results | 0 |
| Expected sent envelopes found | 5/5 |
| Draft envelope in unfiltered listing | Not returned |

Offset-based pagination using `start_position` was verified across three pages. All five expected sent test envelopes were retrieved without duplicates.

## 5. Draft Status Verification

**Verification script:** `scripts/verify_draft_listing.py`

**Command:** `python -m scripts.verify_draft_listing`

| Query | Total Reported | Draft Found |
|---|---:|---|
| Status = `created` | 1 | Yes |
| No status filter | 5 | No |

The draft envelope was successfully retrieved through the status-filtered listing:

`d2d22486-427d-820e-8137-5eb591ad1bf0`

In the tested sandbox configuration, the unfiltered listing returned the five sent envelopes, while the `created` status query returned the draft.

## 6. Rate Limiting and Retry Verification

**Modules:**
- `app/utils/rate_limiter.py`
- `app/utils/retry.py`

| Test | Result |
|---|---|
| Retry and eventual success | PASS |
| Honor `Retry-After` | PASS |
| Non-retryable error fails immediately | PASS |
| Stop after maximum retry attempts | PASS |
| Retryable HTTP status codes (500, 503) | PASS |
| Non-retryable HTTP status codes (400, 401, 404) | PASS |
| Backoff bounds | PASS |
| Parse `Retry-After` | PASS |
| Mocked 429 response followed by success | PASS |
| Mocked 503 response followed by success | PASS |

The tests verify retry behavior, retry limits, backoff bounds, and handling of `Retry-After`. The 429 and 503 endpoint retry scenarios use mocked HTTP responses rather than live sandbox failures.

## 7. Full Automated Test Suite

**Command:** `python -m pytest -v`

| Result | Count |
|---|---:|
| Tests collected | 41 |
| Tests passed | 41 |
| Tests failed | 0 |
| Warnings | 1 |

All 41 tests passed, covering authentication, HMAC verification, retry handling, credential validation, endpoint helpers, and template pagination.

One Starlette deprecation warning was reported for the `httpx` integration with `TestClient`. It did not cause test failures.

**Separate storage verification:** The standalone MinIO connection check was successful, and the `docusign-documents` bucket was created. This is recorded separately from envelope and endpoint testing.

## 8. Recipients and Documents Sandbox Verification

**Verification script:** `scripts/verify_new_endpoints.py`

