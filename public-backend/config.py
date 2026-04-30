"""Public-backend configuration settings."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Read-only public API settings loaded from environment variables."""

    ENVIRONMENT: str = Field(default="development", validation_alias="ENVIRONMENT")

    # Read-only database connection (required — no fallback to admin credentials)
    DATABASE_URL_READONLY: str

    # Connection pool
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600

    # CORS — comma-separated allowlisted origins (no wildcard)
    PUBLIC_CORS_ORIGINS: str = ""

    # Caching
    CACHE_MAX_AGE: int = 300

    # Logging
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()  # type: ignore[call-arg]
