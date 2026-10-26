import os
import time

import httpx

from app.core.hmac_auth import compute_signature

URL = "http://127.0.0.1:8000/api/validate-credentials"

SECRET = os.environ["HMAC_SECRET_KEY_CORE"]

timestamp = str(int(time.time()))
body = b""

signature = compute_signature(
    secret=SECRET,
    timestamp=timestamp,
    method="POST",
    path="/api/validate-credentials",
    body=body,
)

headers = {
    "X-Key-Id": "core",
    "X-Timestamp": timestamp,
    "X-Signature": signature,
}

response = httpx.post(
    URL,
    headers=headers,
)

print("Status:", response.status_code)
print("Response:", response.text)