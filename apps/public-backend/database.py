"""Read-only database connection for public-backend."""

import os
import sys

# Ensure the public-backend directory is importable regardless of CWD.
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import QueuePool

from config import settings


def _ensure_psycopg_driver(url: str) -> str:
    """Force SQLAlchemy to use psycopg v3 instead of legacy psycopg2.

    Mirrors the helper in apps/backend/database.py; see that module for the
    FEAT-0015 rationale.
    """
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


engine = create_engine(
    _ensure_psycopg_driver(settings.DATABASE_URL_READONLY),
    poolclass=QueuePool,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_pre_ping=True,
    pool_recycle=settings.DB_POOL_RECYCLE,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Dependency for getting a read-only database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
