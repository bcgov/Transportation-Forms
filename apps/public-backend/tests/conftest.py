"""Self-contained test fixtures for the public-backend test suite.

Uses an SQLite in-memory database to avoid a PostgreSQL dependency.
The ``public_forms_v`` table is created via raw SQL using SQLite-compatible
types so that the ``PublicForm`` ORM model can run SELECT queries against it
without needing PostgreSQL-specific DDL types (JSONB, UUID).

Each test function gets a fresh, rolled-back session.
"""

from __future__ import annotations

import importlib
import os
import sys
import warnings
from pathlib import Path

import pytest
from pydantic.warnings import PydanticDeprecatedSince20
from sqlalchemy.exc import MovedIn20Warning
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def _enable_targeted_warning_gates() -> None:
    """Fail tests on remediated owner-code framework deprecations."""
    warnings.filterwarnings(
        "error",
        message=r".*Support for class-based `config` is deprecated.*",
        category=PydanticDeprecatedSince20,
        module=r"^(config|database|main|models|routes)(\.|$)",
    )
    warnings.filterwarnings(
        "error",
        message=r".*declarative_base\(\).*",
        category=MovedIn20Warning,
        module=r"^(config|database|main|models|routes)(\.|$)",
    )
    warnings.filterwarnings(
        "error",
        message=r".*on_event is deprecated.*",
        category=DeprecationWarning,
        module=r"^(config|database|main|models|routes)(\.|$)",
    )


_enable_targeted_warning_gates()


def pytest_configure(config: pytest.Config) -> None:
    _enable_targeted_warning_gates()


# ---------------------------------------------------------------------------
# Ensure public-backend is importable
# ---------------------------------------------------------------------------

_PUBLIC_BACKEND_DIR = str(Path(__file__).resolve().parent.parent)
if _PUBLIC_BACKEND_DIR not in sys.path:
    sys.path.insert(0, _PUBLIC_BACKEND_DIR)


# ---------------------------------------------------------------------------
# Minimal required env vars (loaded before any settings object is imported)
# ---------------------------------------------------------------------------

os.environ.setdefault("DATABASE_URL_READONLY", "sqlite:///:memory:")
os.environ.setdefault("INTERNAL_AUTH_SECRET", "")
os.environ.setdefault("CACHE_MAX_AGE", "0")
os.environ.setdefault("OG_CACHE_MAX_AGE", "0")
os.environ.setdefault("LOG_LEVEL", "WARNING")


# ---------------------------------------------------------------------------
# SQLite in-memory engine (session-scoped)
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = text("""
    CREATE TABLE IF NOT EXISTS public_forms_v (
        form_id        TEXT        PRIMARY KEY,
        form_number    TEXT,
        title          TEXT        NOT NULL DEFAULT 'Untitled',
        description    TEXT,
        business_area_id TEXT,
        business_area  TEXT,
        keywords       TEXT,
        file_type      TEXT,
        effective_date DATETIME,
        updated_at     DATETIME,
        s3_key         TEXT,
        file_name      TEXT,
        file_size      INTEGER
    )
""")

# FEAT-0026 — CMS views (mirrored as tables under SQLite for tests).
_CREATE_CMS_PAGES_SQL = text("""
    CREATE TABLE IF NOT EXISTS public_cms_pages_v (
        id               TEXT PRIMARY KEY,
        slug             TEXT NOT NULL,
        title            TEXT NOT NULL,
        meta_description TEXT,
        body_html        TEXT NOT NULL,
        show_in_nav      INTEGER NOT NULL DEFAULT 0,
        nav_order        INTEGER,
        updated_at       DATETIME
    )
""")

_CREATE_CMS_REDIRECTS_SQL = text("""
    CREATE TABLE IF NOT EXISTS public_cms_redirects_v (
        redirect_id TEXT PRIMARY KEY,
        from_slug   TEXT NOT NULL,
        to_page_id  TEXT NOT NULL,
        to_slug     TEXT NOT NULL,
        created_at  DATETIME
    )
""")


@pytest.fixture(scope="session")
def sqlite_engine():
    # StaticPool reuses one connection across all threads so in-memory data
    # is visible to the FastAPI request handler (which runs in a worker thread).
    # check_same_thread=False lets that worker thread reuse the connection.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    with engine.connect() as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_CMS_PAGES_SQL)
        conn.execute(_CREATE_CMS_REDIRECTS_SQL)
        conn.commit()
    yield engine
    engine.dispose()


@pytest.fixture()
def db(sqlite_engine):
    """Yield a Session; truncate all CMS + forms tables after each test."""
    _SessionLocal = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)
    session = _SessionLocal()
    yield session
    session.close()
    # Truncate test data so tests remain isolated.
    with sqlite_engine.connect() as conn:
        conn.execute(text("DELETE FROM public_forms_v"))
        conn.execute(text("DELETE FROM public_cms_pages_v"))
        conn.execute(text("DELETE FROM public_cms_redirects_v"))
        conn.commit()


# ---------------------------------------------------------------------------
# FastAPI TestClient wired to the SQLite session
# ---------------------------------------------------------------------------


@pytest.fixture()
def public_client(db: Session, sqlite_engine):
    """TestClient for the public-backend app with get_db overridden.

    The dependency override creates a fresh session per request bound to the
    shared StaticPool engine, so request handlers see data committed by the
    test's ``db`` session.
    """
    database_mod = importlib.import_module("database")
    main_mod = importlib.import_module("main")

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    public_app = main_mod.app
    public_get_db = database_mod.get_db

    _ReqSession = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)

    def _override_get_db():
        s = _ReqSession()
        try:
            yield s
        finally:
            s.close()

    public_app.dependency_overrides[public_get_db] = _override_get_db
    yield TestClient(public_app, raise_server_exceptions=False)
    public_app.dependency_overrides.pop(public_get_db, None)
