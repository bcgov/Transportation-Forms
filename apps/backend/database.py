"""
Database configuration and session management
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import QueuePool
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
assert DATABASE_URL is not None, "DATABASE_URL environment variable is required"


def _ensure_psycopg_driver(url: str) -> str:
    """Force SQLAlchemy to use psycopg v3 instead of the legacy psycopg2.

    The default ``postgresql://`` scheme resolves to psycopg2 in SQLAlchemy.
    FEAT-0015 standardises on psycopg v3 (Python 3.14 + PostgreSQL 18
    support). DATABASE_URL values in env files remain ``postgresql://`` for
    portability; we rewrite to ``postgresql+psycopg://`` here so existing
    deployment env values keep working unchanged.
    """
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


# Connection pool settings
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
DB_POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))

# Create engine with connection pooling
engine = create_engine(
    _ensure_psycopg_driver(DATABASE_URL),
    poolclass=QueuePool,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT,
    pool_pre_ping=True,  # Test connections before use
    pool_recycle=3600,  # Recycle connections hourly
    echo=os.getenv("SQLALCHEMY_ECHO", "false").lower() == "true",
)

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

class Base(DeclarativeBase):
    """Base class for application ORM models."""

    pass


def get_db():
    """Dependency for getting database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
