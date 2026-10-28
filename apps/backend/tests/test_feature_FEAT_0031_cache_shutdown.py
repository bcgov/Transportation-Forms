"""Shutdown must preserve cancellation of the parent task."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest


async def assert_parent_cancellation_survives(
    lifespan, app, monkeypatch, cache_owner
):
    cleanup_started = asyncio.Event()
    cleanup_release = asyncio.Event()

    async def checks():
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await cleanup_release.wait()

    monkeypatch.setattr(cache_owner, "run_engagement_checks", checks)

    async def serve():
        async with lifespan(app):
            await asyncio.sleep(0)

    task = asyncio.create_task(serve())
    try:
        await asyncio.wait_for(cleanup_started.wait(), timeout=2)
        task.cancel()
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        cleanup_release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def test_staff_lifespan_propagates_parent_cancellation(monkeypatch):
    from backend import main
    from backend import database
    from backend.seeds import default_roles
    from backend.services import s3_service

    monkeypatch.setattr(database, "SessionLocal", lambda: Mock())
    monkeypatch.setattr(
        default_roles, "seed_default_roles", lambda _db: {"failed": False}
    )
    monkeypatch.setattr(s3_service, "ensure_bucket_exists", lambda: None)
    asyncio.run(
        assert_parent_cancellation_survives(
            main.lifespan, main.app, monkeypatch, main
        )
    )


def test_public_lifespan_propagates_parent_cancellation(monkeypatch):
    monkeypatch.setenv("DATABASE_URL_READONLY", "sqlite:///:memory:")
    public_dir = str(Path(__file__).resolve().parents[2] / "public-backend")
    sys.path.insert(0, public_dir)
    try:
        import main
    finally:
        sys.path.remove(public_dir)
    asyncio.run(
        assert_parent_cancellation_survives(
            main.lifespan, main.app, monkeypatch, main
        )
    )
