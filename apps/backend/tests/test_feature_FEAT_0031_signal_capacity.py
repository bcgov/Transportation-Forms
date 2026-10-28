"""Both portals reject excess signals without queuing a write."""

import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import Request

from shared.engagement_writer import CountDispatcher


@pytest.mark.parametrize("portal", ["Staff", "Public"])
def test_full_writer_budget_rejects_signal_before_submitting(
    portal, monkeypatch
):
    if portal == "Staff":
        from backend.routes import engagement as route

        monkeypatch.setenv(
            "STAFF_ENGAGEMENT_ORIGIN", "https://forms.example.org"
        )
        form_id = uuid4()
        identifier = {"form_id": str(form_id)}
        cache = Mock()
        cache.eligible.return_value = True
    else:
        monkeypatch.setenv("DATABASE_URL_READONLY", "sqlite:///:memory:")
        public_dir = str(
            Path(__file__).resolve().parents[2] / "public-backend"
        )
        sys.path.insert(0, public_dir)
        try:
            from routes import engagement as route
        finally:
            sys.path.remove(public_dir)

        monkeypatch.setattr(
            route.settings, "PUBLIC_BASE_URL", "https://forms.example.org"
        )
        form_id = uuid4()
        identifier = {"form_number": "HWY 123"}
        cache = Mock()
        cache.resolve.return_value = form_id

    summary = Mock()
    dispatcher = CountDispatcher(summary, capacity=1)
    entered, release = Event(), Event()
    writer = Mock()

    def blocked_write(*args):
        entered.set()
        assert release.wait(2)
        writer(*args)

    monkeypatch.setattr(route, "dispatcher", dispatcher)
    monkeypatch.setattr(route, "cache", cache)
    monkeypatch.setattr(route, "record_daily_engagement", blocked_write)

    def request():
        body = json.dumps({**identifier, "metric": "detail_view"}).encode()
        headers = [
            (b"origin", b"https://forms.example.org"),
            (b"content-type", b"application/json"),
        ]

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        instance = Request(
            {"type": "http", "method": "POST", "headers": headers},
            receive=receive,
        )
        if portal == "Staff":
            return asyncio.run(route.signal(instance, _user=object()))
        return asyncio.run(route.signal(instance))

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(request)
            assert entered.wait(1)
            dropped = pool.submit(request).result(timeout=1)
            assert dropped.status_code == 503
            assert json.loads(dropped.body) == {"accepted": False}
            summary.record.assert_called_once_with("known_capacity")
            writer.assert_not_called()
            release.set()
            accepted = first.result(timeout=2)
            assert accepted.status_code == 202
            writer.assert_called_once()
            assert writer.call_args.args[:3] == (
                form_id,
                "detail_view",
                portal,
            )
    finally:
        release.set()
        dispatcher._executor.shutdown(wait=True)
