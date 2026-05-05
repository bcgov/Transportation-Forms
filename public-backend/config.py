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

    # FEAT-0005: shared-secret enforced by middleware; injected by NGINX
    # (public-frontend edge).  Must be set in every non-test environment.
    INTERNAL_AUTH_SECRET: str = Field(
        default="",
        validation_alias="INTERNAL_AUTH_SECRET",
    )

    # FEAT-0005: prefix used for the X-Accel-Redirect header pointing at
    # the NGINX `internal;` /internal-s3/ location.  S3 object key from
    # the database is appended to this prefix.  Must end with `/`.
    INTERNAL_S3_REDIRECT_PREFIX: str = "/internal-s3/"

    # FEAT-0005: canonical public origin used when the OG endpoint and
    # sitemap need absolute URLs (e.g. ``https://forms-public-prod.apps...``).
    # Empty string falls back to the request URL's scheme+host.
    PUBLIC_BASE_URL: str = ""

    # Caching (per-endpoint TTLs)
    CACHE_MAX_AGE: int = 300                  # list / detail
    BUSINESS_AREAS_CACHE_MAX_AGE: int = 600   # /business-areas
    SITEMAP_CACHE_MAX_AGE: int = 3600         # /sitemap.xml
    OG_CACHE_MAX_AGE: int = 600               # /forms/{n}/og

    # Pagination clamps
    DEFAULT_LIMIT: int = 25
    MAX_LIMIT: int = 500

    # Logging
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()  # type: ignore[call-arg]
