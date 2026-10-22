from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_ENV: str = "dev"
    LOG_LEVEL: str = "INFO"
    DATABASE_URL: str = "postgresql://ds:ds@localhost:5432/docusign"
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "docusign-data"
    DOCUSIGN_AUTH_SERVER: str = "account-d.docusign.com"
    DOCUSIGN_DEFAULT_PAGE_SIZE: int = 100
    class Config:
        env_file = ".env"

settings = Settings()