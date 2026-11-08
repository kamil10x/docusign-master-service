"""Signed calls to the normalization endpoints (HMAC, like scripts/sign_demo.py).

Run from the repo root, with the stack up (docker compose up -d):

    python -m scripts.call_normalization <job_id>            # run normalization
    python -m scripts.call_normalization <job_id> status
    python -m scripts.call_normalization <job_id> results
"""
import json
import sys
import time

import httpx

from app.config import settings
from app.core.hmac_auth import compute_signature

BASE_URL = "http://localhost:8000"


def _signed_headers(method: str, path: str) -> dict[str, str]:
    ts = str(int(time.time()))
    signature = compute_signature(settings.HMAC_SECRET_KEY_CORE, ts, method, path, b"")
    return {"X-Key-Id": "core", "X-Timestamp": ts, "X-Signature": signature}


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)

    job_id = sys.argv[1]
    action = sys.argv[2] if len(sys.argv) > 2 else "run"
    routes = {
        "run": ("POST", f"/api/normalization/{job_id}"),
        "status": ("GET", f"/api/normalization/{job_id}/status"),
        "results": ("GET", f"/api/normalization/{job_id}/results"),
    }
    if action not in routes:
        sys.exit(f"Unknown action '{action}'. Use: {', '.join(routes)}")

    method, path = routes[action]
    response = httpx.request(
        method, BASE_URL + path, headers=_signed_headers(method, path), timeout=300
    )
    print(response.status_code)
    try:
        print(json.dumps(response.json(), indent=2))
    except ValueError:
        print(response.text)


if __name__ == "__main__":
    main()