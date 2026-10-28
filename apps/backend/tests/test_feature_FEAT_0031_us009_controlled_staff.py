"""US-009 Staff fault injection without a live forms database."""

import asyncio
import logging
import sys
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.routes import engagement as signal_route
from backend.routes import forms as forms_route
from backend.services import engagement_cache as cache_module
from backend.services import forms as forms_service


def test_cache_recovers_and_warns_once_in_each_failed_check_streak(monkeypatch):
    cache = cache_module.StaffFormCache()
    form_id = uuid4()
    session = MagicMock()
    query = session.__enter__.return_value.query.return_value
    query.filter.return_value = query
    query.all.return_value = [(form_id, "URL", "https://example.test/form")]
    unavailable = {"value": True}

    def session_local():
        if unavailable["value"]:
            raise RuntimeError("private database failure")
        return session

    warnings = Mock()
    monkeypatch.setattr(cache_module, "SessionLocal", session_local)
    monkeypatch.setattr(cache_module.logger, "warning", warnings)

    cache.check()
    assert not cache.eligible(form_id, "detail_view")
    assert cache._failures == 1

    unavailable["value"] = False
    cache.check()
    assert cache.eligible(form_id, "link_click")
    assert cache._failures == 0

    warning_message = (
        "Cache checks have failed 20 consecutive times since %s. "
        "Engagement counts for newly eligible forms may be missing on this pod; "
        "stale forms may still be counted."
    )
    for streak in range(2):
        unavailable["value"] = True
        for attempt in range(1, 22):
            cache.check()
            assert cache._failures == attempt
            assert cache.eligible(form_id, "detail_view")
            stale_warnings = [
                call
                for call in warnings.call_args_list
                if call.args[0] == warning_message
            ]
            assert len(stale_warnings) == streak + (attempt >= 20)
            failed_checks = [
                call
                for call in warnings.call_args_list
                if call.args[0]
                == "staff_cache_check_failed reason=read_failed streak=%d"
            ]
            assert len(failed_checks) == 1 + 21 * streak + attempt
            if attempt == 20:
                assert stale_warnings[-1].args[1] == cache._first_failure.isoformat()

        unavailable["value"] = False
        cache.check()
        assert cache._failures == 0
        assert cache._first_failure is None

    assert all(
        "private database failure" not in str(call) for call in warnings.call_args_list
    )


def test_failed_cache_checks_write_fixed_identity_free_stdout(monkeypatch, capfd):
    cache = cache_module.StaffFormCache()
    monkeypatch.setattr(
        cache_module.logger, "handlers", [logging.StreamHandler(sys.stdout)]
    )
    monkeypatch.setattr(
        cache_module,
        "SessionLocal",
        Mock(side_effect=RuntimeError("private@example.test")),
    )

    for _ in range(20):
        cache.check()

    stdout, stderr = capfd.readouterr()
    assert stdout.count("staff_cache_check_failed reason=read_failed streak=") == 20
    assert stdout.count("Cache checks have failed 20 consecutive times since ") == 1
    assert "newly eligible forms may be missing on this pod" in stdout
    assert "private@example.test" not in stdout + stderr


def test_later_audit_rollback_cannot_undo_committed_cache_deletion(monkeypatch):
    cache = cache_module.StaffFormCache()
    cache._loaded = True
    form_id = uuid4()
    form = SimpleNamespace(
        id=form_id,
        deleted_at=None,
        status="published",
        form_source="URL",
        form_source_url="https://example.test/form",
    )
    cache.committed(form)
    monkeypatch.setattr(forms_service, "engagement_cache", cache)
    monkeypatch.setattr(
        forms_service.FormService, "get_form_by_id", Mock(return_value=form)
    )
    db = Mock()

    def commit():
        assert cache.eligible(form_id, "detail_view")
        assert isinstance(form.deleted_at, datetime)

    db.commit.side_effect = commit
    db.add.side_effect = RuntimeError("private audit failure")

    assert forms_service.FormService.delete_form(db, form_id, uuid4()) is True
    db.commit.assert_called_once()
    db.rollback.assert_called_once()
    assert not cache.eligible(form_id, "detail_view")
    assert not cache.eligible(form_id, "link_click")


def test_external_edit_changes_older_eligibility_without_count_change(monkeypatch):
    cache = cache_module.StaffFormCache()
    old_id, new_id, latest_id = uuid4(), uuid4(), uuid4()
    latest = (latest_id, "Download", None)
    rows = [(old_id, "URL", "https://example.test/form"), latest]
    session = MagicMock()
    query = session.__enter__.return_value.query.return_value
    query.filter.return_value = query
    query.all.return_value = rows
    sessions = Mock(return_value=session)
    monkeypatch.setattr(cache_module, "SessionLocal", sessions)

    cache.check()
    assert cache.eligible(old_id, "link_click")
    assert cache.eligible(latest_id, "detail_view")

    rows[:] = [(new_id, "URL", "https://example.test/form"), latest]
    cache.check()
    assert not cache.eligible(old_id, "detail_view")
    assert cache.eligible(new_id, "link_click")

    rows[:] = [(new_id, "URL", "javascript:alert(1)"), latest]
    cache.check()
    assert cache.eligible(new_id, "detail_view")
    assert not cache.eligible(new_id, "link_click")
    assert cache.eligible(latest_id, "detail_view")
    assert sessions.call_count == 3


def test_denied_staff_detail_does_not_block_independent_cached_signal(monkeypatch):
    form_id = uuid4()
    monkeypatch.setattr(
        forms_service.FormService,
        "get_form_with_details",
        Mock(return_value={"status": "draft"}),
    )
    monkeypatch.setattr(forms_route, "_is_staff_viewer_only", Mock(return_value=True))
    with pytest.raises(HTTPException) as denied:
        asyncio.run(
            forms_route.get_form(str(form_id), current_user=object(), db=Mock())
        )
    assert denied.value.status_code == 404

    cache = cache_module.StaffFormCache()
    cache._loaded = True
    cache.committed(
        SimpleNamespace(
            id=form_id,
            deleted_at=None,
            form_source="URL",
            form_source_url="https://example.test/form",
        )
    )
    app = FastAPI()
    app.include_router(signal_route.router, prefix="/api/v1")
    app.dependency_overrides[signal_route._authenticated_staff] = lambda: object()
    writer = Mock()
    monkeypatch.setattr(signal_route, "cache", cache)
    monkeypatch.setattr(signal_route, "record_daily_engagement", writer)
    monkeypatch.setenv("STAFF_ENGAGEMENT_ORIGIN", "http://testserver")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/engagement/signal",
            json={"form_id": str(form_id), "metric": "detail_view"},
            headers={"Origin": "http://testserver"},
        )

    assert response.status_code == 202
    assert writer.call_args.args[:3] == (form_id, "detail_view", "Staff")
    assert isinstance(writer.call_args.args[3], date)
