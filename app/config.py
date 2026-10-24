from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_ENV: str
    LOG_LEVEL: str
    DEBUG: bool

    # Database
    DATABASE_URL: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    DB_POOL_SIZE: int

    # MinIO
    MINIO_ENDPOINT: str
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_BUCKET: str
    MINIO_SECURE: bool
    MINIO_ROOT_USER: str
    MINIO_ROOT_PASSWORD: str

    # DocuSign
    DOCUSIGN_SECRET_KEY: str
    DOCUSIGN_INTEGRATION_KEY: str
    DOCUSIGN_USER_ID: str
    DOCUSIGN_ACCOUNT_ID: str
    DOCUSIGN_AUTH_SERVER: str
    DOCUSIGN_BASE_URL: str
    DOCUSIGN_PRIVATE_KEY_PATH: str
    DOCUSIGN_REQUEST_TIMEOUT: int
    DOCUSIGN_MAX_RETRIES_ON_429: int
    DOCUSIGN_DEFAULT_RETRY_AFTER_SECONDS: int
    DOCUSIGN_DEFAULT_PAGE_SIZE: int

    # External call resilience
    EXTERNAL_CALL_MAX_RETRIES: int
    EXTERNAL_CALL_RETRY_DELAYS: str
    EXTERNAL_CALL_JITTER: float
    DLQ_PAYLOAD_MAX_BYTES: int

    # HMAC
    HMAC_ENABLED: bool
    HMAC_SECRET_KEY_CORE: str
    HMAC_SECRET_KEY_ENGINEER: str
    HMAC_SIGNATURE_MAX_AGE: int

    # Job tracking
    JOB_HEARTBEAT_INTERVAL_SECONDS: int
    JOB_CRASH_TIMEOUT_MINUTES: int

    # Encryption
    ENCRYPTION_KEY: str

    # RSA
    RSA_KEYPAIR_ID: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()