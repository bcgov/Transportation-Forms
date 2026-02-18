"""Application configuration settings."""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/transportation_forms"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600
    
    # API
    API_PREFIX: str = "/api/v1"
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8080"
    
    # KeyCloak
    KEYCLOAK_SERVER_URL: Optional[str] = "http://localhost:8080"
    KEYCLOAK_REALM: Optional[str] = "test-realm"
    KEYCLOAK_CLIENT_ID: Optional[str] = "test-client"
    KEYCLOAK_CLIENT_SECRET: Optional[str] = "test-secret"
    KEYCLOAK_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/callback"
    
    # AWS S3
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_S3_BUCKET: Optional[str] = None
    AWS_REGION: str = "us-west-2"
    
    # Feature Flags
    ENABLE_SEMANTIC_SEARCH: bool = True
    ENABLE_EMAIL_NOTIFICATIONS: bool = False
    
    # Logging
    LOG_LEVEL: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Ignore extra fields in .env


# Global settings instance
settings = Settings()
