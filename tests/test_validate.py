import os
import time

from fastapi.testclient import TestClient

from app.core.hmac_auth import compute_signature
from app.main import app


client = TestClient(app)


def test_validate_credentials_with_valid_hmac():
    timestamp = str(int(time.time()))
    body = b""

    secret = os.environ["HMAC_SECRET_KEY_CORE"]

    signature = compute_signature(
        secret=secret,
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

    response = client.post(
        "/api/validate-credentials",
        headers=headers,
    )

    print("Status:", response.status_code)
    print("Response:", response.text)

    # Authentication should succeed.
    # The endpoint itself may return another status depending
    # on the current DocuSign sandbox/configuration.
    assert response.status_code != 401