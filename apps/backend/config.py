"""Application configuration settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator, Field
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    ENVIRONMENT: str = Field(default="development", validation_alias="ENVIRONMENT")

    # Database (required, no defaults)
    DATABASE_URL: str
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600

    # API (required)
    API_PREFIX: str = "/api/v1"
    SECRET_KEY: str
    CORS_ORIGINS: str = (
        "http://localhost:3000,http://localhost:8000,http://localhost:8080,"
        "http://localhost:30300,http://localhost:30800,http://127.0.0.1:3000,"
        "http://localhost,http://127.0.0.1,"
        "http://127.0.0.1:8000,http://127.0.0.1:30300,http://127.0.0.1:30800"
    )

    # KeyCloak (optional until auth disabled)
    KEYCLOAK_SERVER_URL: Optional[str] = None
    KEYCLOAK_REALM: Optional[str] = None
    KEYCLOAK_CLIENT_ID: Optional[str] = None
    KEYCLOAK_CLIENT_SECRET: Optional[str] = None
    KEYCLOAK_REDIRECT_URI: Optional[str] = None
    KEYCLOAK_VERIFY_TLS: bool = True

    # Authentication
    AUTH_DEMO_MODE: bool = False

    # Refresh-token cookie (FEAT-0020 / SEC-004)
    # Cookie name carrying the staff-portal refresh token. Marked HttpOnly so it
    # is not readable by JavaScript, Secure so it is only sent over HTTPS, and
    # SameSite=lax so legitimate OIDC top-level redirects keep working.
    # AUTH_COOKIE_SECURE may be set to False in local http-only development.
    AUTH_REFRESH_COOKIE_NAME: str = "tf_refresh_token"
    AUTH_REFRESH_COOKIE_PATH: str = "/api/v1/auth"
    AUTH_REFRESH_COOKIE_SAMESITE: str = "lax"
    AUTH_COOKIE_SECURE: bool = True

    # S3-compatible object storage (MinIO in local dev, custom S3 service in production)
    S3_ENDPOINT_URL: str = Field(alias="S3_ENDPOINT_URL")
    S3_ACCESS_KEY: str = Field(alias="S3_ACCESS_KEY")
    S3_SECRET_KEY: str = Field(alias="S3_SECRET_KEY")
    S3_BUCKET: str = Field(alias="S3_BUCKET")
    S3_VERIFY_TLS: bool = True
    # Feature Flags
    ENABLE_SEMANTIC_SEARCH: bool = True
    ENABLE_EMAIL_NOTIFICATIONS: bool = False

    # Logging
    LOG_LEVEL: str = "INFO"

    @model_validator(mode="after")
    def validate_required_secrets(self):
        """Require critical secrets in non-development environments."""
        if self.ENVIRONMENT.lower() == "development":
            return self

        required = {
            "DATABASE_URL": self.DATABASE_URL,
            "SECRET_KEY": self.SECRET_KEY,
            "S3_ACCESS_KEY": self.S3_ACCESS_KEY,
            "S3_SECRET_KEY": self.S3_SECRET_KEY,
        }

        missing = [key for key, value in required.items() if not value or value == "None"]
        if missing:
            raise ValueError(
                "Missing required secrets (set via environment or .env): "
                + ", ".join(missing)
            )

        return self

    @model_validator(mode="after")
    def validate_keycloak_config(self):
        """Require Keycloak config from environment when demo auth mode is disabled."""
        if self.AUTH_DEMO_MODE or self.ENVIRONMENT.lower() == "development":
            return self

        required = {
            "KEYCLOAK_SERVER_URL": self.KEYCLOAK_SERVER_URL,
            "KEYCLOAK_REALM": self.KEYCLOAK_REALM,
            "KEYCLOAK_CLIENT_ID": self.KEYCLOAK_CLIENT_ID,
            "KEYCLOAK_CLIENT_SECRET": self.KEYCLOAK_CLIENT_SECRET,
            "KEYCLOAK_REDIRECT_URI": self.KEYCLOAK_REDIRECT_URI,
        }

        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(
                "Missing required Keycloak configuration in .env: " + ", ".join(missing)
            )

        return self

# Global settings instance (lazy-loaded to support testing and CLI contexts)
try:
    settings = Settings()  # type: ignore[call-arg]
except ValueError:
    # Allow import in test/CLI contexts where env vars are not yet loaded
    settings = None  # type: ignore
