"""Usage: python scripts/call_api.py GET /api/maintenance/jobs status=failed
          python scripts/call_api.py POST /api/scan/<job_id>/resume
          python scripts/call_api.py POST /api/scan '{"from_date":"2024-01-01"}'
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv()

from app.core.config import get_settings
from app.core.hmac_auth import compute_signature

BASE = "http://127.0.0.1:8000"


def main() -> None:
    method, path, *rest = sys.argv[1:]
    method = method.upper()
    path, _, raw_query = path.partition("?")  # sign the path only, like the server
    body = b""
    query = dict(urllib.parse.parse_qsl(raw_query))
    for arg in rest:
        if arg.startswith("{"):
            body = json.dumps(json.loads(arg), separators=(",", ":")).encode()
        else:
            k, _, v = arg.partition("=")
            query[k] = v

    timestamp = str(int(time.time()))
    # signs the path only (no query string), same as call_scan.py
    signature = compute_signature(get_settings().hmac_secret, timestamp, method, path, body)

    url = BASE + path + (("?" + urllib.parse.urlencode(query)) if query else "")
    req = urllib.request.Request(
        url,
        data=body or None,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Key-Id": "core",
            "X-Timestamp": timestamp,
            "X-Signature": signature,
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(resp.status)
            print(json.dumps(json.loads(resp.read()), indent=2, default=str))
    except urllib.error.HTTPError as e:
        print("HTTP", e.code)
        print(e.read().decode())


if __name__ == "__main__":
    main()