
import time
import json
import urllib.request
import urllib.error

from dotenv import load_dotenv

load_dotenv()

from app.core.config import get_settings
from app.core.hmac_auth import compute_signature
from app.config import settings as app_settings


# Get the same secret used by the application
secret = get_settings().hmac_secret
dependency_secret = app_settings.HMAC_SECRET_KEY_CORE

if not secret:
    raise RuntimeError("HMAC secret is not configured.")

if secret != dependency_secret:
    raise RuntimeError("HMAC secrets differ between middleware and dependency.")

# Prepare request
url = "http://127.0.0.1:8000/api/scan"
path = "/api/scan"
method = "POST"

body = json.dumps(
    {"from_date": "2024-01-01"},
    separators=(",", ":")
).encode("utf-8")

timestamp = str(int(time.time()))

# Generate HMAC signature
signature = compute_signature(
    secret,
    timestamp,
    method,
    path,
    body
)
print("Timestamp:", timestamp)
print("Method:", method)
print("Path:", path)
print("Body:", body.decode("utf-8"))
print("Signature:", signature)
print("Key ID:", "core")

headers = {
    "Content-Type": "application/json",
    "X-Key-Id": "core",
    "X-Timestamp": timestamp,
    "X-Signature": signature,
}

request = urllib.request.Request(
    url,
    data=body,
    headers=headers,
    method=method,
)

try:
    with urllib.request.urlopen(request) as response:
        print("HTTP Status:", response.status)
        print("Response:", response.read().decode("utf-8"))

except urllib.error.HTTPError as error:
    print("HTTP Error:", error.code)
    print(error.read().decode("utf-8"))

except urllib.error.URLError as error:
    print("Connection Error:", error.reason)

