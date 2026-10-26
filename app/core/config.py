import os
from dataclasses import dataclass, field
from functools import lru_cache


def _read_private_key() -> str:
    """Private key can be given inline or as a file path (preferred)."""
    inline = os.getenv("DOCUSIGN_PRIVATE_KEY", "")
    if inline:
        return inline.replace("\\n", "\n")
    path = os.getenv("DOCUSIGN_PRIVATE_KEY_PATH", "")
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    return ""


@dataclass(frozen=True)
class Settings:
    docusign_integration_key: str = field(
        default_factory=lambda: os.getenv("DOCUSIGN_INTEGRATION_KEY", "")
    )
    docusign_user_id: str = field(
        default_factory=lambda: os.getenv("DOCUSIGN_USER_ID", "")
    )
    # Sandbox: account-d.docusign.com | Production: account.docusign.com
    docusign_auth_host: str = field(
        default_factory=lambda: os.getenv("DOCUSIGN_AUTH_HOST", "account-d.docusign.com")
    )
    docusign_private_key: str = field(default_factory=_read_private_key)
    hmac_secret: str = field(default_factory=lambda: os.getenv("HMAC_SECRET_KEY_CORE", ""))
    hmac_max_skew_seconds: int = field(
        default_factory=lambda: int(os.getenv("HMAC_MAX_SKEW_SECONDS", "300"))
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()