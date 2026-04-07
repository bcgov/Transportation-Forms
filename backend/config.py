"""Application configuration settings."""

from pydantic_settings import BaseSettings
from pydantic import model_validator, Field
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

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

    # AWS S3 (optional until enabled)
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_S3_BUCKET: Optional[str] = None
    AWS_REGION: str = "us-west-2"

    # MinIO (S3-compatible) — S3_* env vars with Field(alias=...) for env loading
    # When loaded from environment, Field(alias=...) tells BaseSettings which env var to read
    MINIO_ENDPOINT: str = Field(default="http://minio:9000", alias="MINIO_ENDPOINT")
    MINIO_ACCESS_KEY: str = Field(default="NONE", alias="MINIO_ACCESS_KEY")
    MINIO_SECRET_KEY: str = Field(default="NONE", alias="MINIO_SECRET_KEY")
    MINIO_BUCKET: str = Field(default="form-attachments", alias="MINIO_BUCKET")
    MINIO_PUBLIC_URL: str = Field(default="http://localhost:9000", alias="MINIO_PUBLIC_URL")
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
            "MINIO_ACCESS_KEY": self.MINIO_ACCESS_KEY,
            "MINIO_SECRET_KEY": self.MINIO_SECRET_KEY,
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

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Ignore extra fields in .env


# Global settings instance  
settings = Settings()
