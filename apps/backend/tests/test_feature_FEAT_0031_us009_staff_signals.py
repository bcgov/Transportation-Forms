"""US-009 Staff signal validation and per-pod cache contracts."""

import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import engagement as signal_route
from backend.services import engagement_cache as cache_module
from backend.services import forms as forms_service


@pytest.fixture()
def signal_client(monkeypatch):
    monkeypatch.setenv("STAFF_ENGAGEMENT_ORIGIN", "http://testserver")
    app = FastAPI()
    app.include_router(signal_route.router, prefix="/api/v1")
    app.dependency_overrides[signal_route._authenticated_staff] = lambda: object()
    cache = cache_module.StaffFormCache()
    cache._loaded = True
    writer = Mock()
    monkeypatch.setattr(signal_route, "cache", cache)
    monkeypatch.setattr(signal_route, "record_daily_engagement", writer)
    with TestClient(app) as client:
        yield client, cache, writer


def _post(client, body, *, headers=None):
    return client.post(
        "/api/v1/engagement/signal",
        content=body,
        headers={
            "origin": "http://testserver",
            "content-type": "application/json",
            **(headers or {}),
        },
    )


def _session_with_rows(rows):
    session = MagicMock()
    query = session.__enter__.return_value.query.return_value
    query.filter.return_value = query
    query.all.return_value = rows
    return session


def test_accepted_signals_write_once_per_request_from_staff(signal_client):
    client, cache, writer = signal_client
    form_id = uuid4()
    cache.committed(
        SimpleNamespace(
            id=form_id,
            deleted_at=None,
            form_source="URL",
            form_source_url="https://example.org/form",
        )
    )

    for metric in ("detail_view", "link_click", "detail_view"):
        response = _post(
            client, json.dumps({"form_id": str(form_id), "metric": metric})
        )
        assert response.status_code == 202
        assert response.json() == {"accepted": True}
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"

    assert writer.call_count == 3
    assert [call.args for call in writer.call_args_list] == [
        (form_id, "detail_view", "Staff"),
        (form_id, "link_click", "Staff"),
        (form_id, "detail_view", "Staff"),
    ]


def test_staff_cache_rejects_whitespace_host_link(signal_client):
    client, cache, writer = signal_client
    form_id = uuid4()
    cache.committed(
        SimpleNamespace(
            id=form_id,
            deleted_at=None,
            form_source="URL",
            form_source_url="https://bad host/form",
        )
    )
    response = _post(
        client, json.dumps({"form_id": str(form_id), "metric": "link_click"})
    )

    assert response.status_code == 404
    writer.assert_not_called()


@pytest.mark.parametrize(
    ("body", "headers", "status"),
    [
        ('{"form_id":"x","metric":"detail_view"}', {}, 400),
        ('{"form_id":"x","metric":"detail_view","source":"Public"}', {}, 400),
        ('{"form_id":"x","form_id":"y","metric":"detail_view"}', {}, 400),
        ('{"form_id":"x","metric":"download"}', {}, 400),
        ('{"form_id":null,"metric":"detail_view"}', {}, 400),
        ("not json", {}, 400),
        ('{"form_id":"x","metric":"detail_view"}', {"content-type": "text/plain"}, 415),
        ("x" * 1025, {}, 413),
        (
            '{"form_id":"x","metric":"detail_view"}',
            {"origin": "https://elsewhere.test"},
            403,
        ),
        ('{"form_id":"x","metric":"detail_view"}', {"origin": ""}, 403),
    ],
)
def test_invalid_staff_signals_never_reach_writer(signal_client, body, headers, status):
    client, _, writer = signal_client
    response = _post(client, body, headers=headers)

    assert response.status_code == status
    assert response.json() == {"accepted": False}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    writer.assert_not_called()


def test_staff_requires_authentication(monkeypatch):
    monkeypatch.setenv("STAFF_ENGAGEMENT_ORIGIN", "http://testserver")
    app = FastAPI()
    app.include_router(signal_route.router, prefix="/api/v1")
    writer = Mock()
    monkeypatch.setattr(signal_route, "record_daily_engagement", writer)

    with TestClient(app) as client:
        response = _post(
            client, json.dumps({"form_id": str(uuid4()), "metric": "detail_view"})
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    writer.assert_not_called()


def test_staff_referrer_fallback_and_cache_rejects_unknown_or_disabled_link(
    signal_client,
):
    client, cache, writer = signal_client
    form_id = uuid4()
    cache.committed(
        SimpleNamespace(
            id=form_id,
            deleted_at=None,
            form_source="URL",
            form_source_url="javascript:alert(1)",
        )
    )
    body = json.dumps({"form_id": str(form_id), "metric": "detail_view"})

    assert (
        _post(
            client, body, headers={"origin": "", "referer": "http://testserver/forms"}
        ).status_code
        == 403
    )
    assert (
        _post(
            client, body, headers={"origin": "", "referer": "https://other.test/forms"}
        ).status_code
        == 403
    )
    response = client.post(
        "/api/v1/engagement/signal",
        content=body,
        headers={
            "referer": "http://testserver/forms",
            "content-type": "application/json",
        },
    )
    assert response.status_code == 202
    assert (
        _post(
            client, json.dumps({"form_id": str(form_id), "metric": "link_click"})
        ).status_code
        == 404
    )
    assert (
        _post(
            client, json.dumps({"form_id": str(uuid4()), "metric": "detail_view"})
        ).status_code
        == 404
    )
    writer.assert_called_once_with(form_id, "detail_view", "Staff")


def test_staff_cache_fail_closed_then_keeps_last_good_and_warns_once(monkeypatch):
    cache = cache_module.StaffFormCache()
    form_id = uuid4()
    monkeypatch.setattr(
        cache_module, "SessionLocal", Mock(side_effect=RuntimeError("private data"))
    )
    warning = Mock()
    monkeypatch.setattr(cache_module.logger, "warning", warning)

    cache.check()
    assert not cache.eligible(form_id, "detail_view")
    assert cache._failures == 1

    monkeypatch.setattr(
        cache_module,
        "SessionLocal",
        Mock(
            return_value=_session_with_rows(
                [
                    (form_id, "URL", "https://example.org/form"),
                ]
            )
        ),
    )
    cache.check()
    assert cache.eligible(form_id, "detail_view")
    assert cache.eligible(form_id, "link_click")
    assert cache._failures == 0

    monkeypatch.setattr(
        cache_module, "SessionLocal", Mock(side_effect=RuntimeError("private data"))
    )
    warning.reset_mock()
    for _ in range(21):
        cache.check()
    assert cache.eligible(form_id, "detail_view")
    assert cache._failures == 21
    assert len(warning.call_args_list) == 22
    assert [call.args[0] for call in warning.call_args_list].count(
        "Cache checks have failed 20 consecutive times since %s. "
        "Engagement counts for newly eligible forms may be missing on this pod; "
        "stale forms may still be counted."
    ) == 1
    assert warning.call_args_list[20].args[1] == cache._first_failure.isoformat()
    assert all("private data" not in str(call) for call in warning.call_args_list)


def test_staff_startup_cache_failure_keeps_application_available(monkeypatch):
    from backend import database
    from backend.main import app as staff_app
    from backend.seeds import default_roles
    from backend.services import s3_service

    cache = cache_module.StaffFormCache()
    checked = Event()
    original_check = cache.check

    def failed_check():
        original_check()
        checked.set()

    monkeypatch.setattr(cache, "check", failed_check)
    monkeypatch.setattr(cache_module, "cache", cache)
    monkeypatch.setattr(signal_route, "cache", cache)
    monkeypatch.setattr(
        cache_module, "SessionLocal", Mock(side_effect=RuntimeError("private data"))
    )
    monkeypatch.setattr(cache_module, "check_interval_seconds", lambda: 3600)
    monkeypatch.setattr(database, "SessionLocal", Mock(return_value=Mock()))
    monkeypatch.setattr(
        default_roles, "seed_default_roles", Mock(return_value={"failed": False})
    )
    monkeypatch.setattr(s3_service, "ensure_bucket_exists", Mock())
    warning = Mock()
    monkeypatch.setattr(cache_module.logger, "warning", warning)

    with TestClient(staff_app) as client:
        assert checked.wait(timeout=3)
        assert client.get("/health").status_code == 200
        assert not cache.eligible(uuid4(), "detail_view")

    assert cache._failures == 1
    warning.assert_called_once_with(
        "staff_cache_check_failed reason=read_failed streak=%d", 1
    )


def test_staff_check_detects_deletion_and_link_change_and_preserves_local_commit(
    monkeypatch,
):
    cache = cache_module.StaffFormCache()
    form_id = uuid4()
    rows = [(form_id, "File", None)]
    session = _session_with_rows(rows)
    monkeypatch.setattr(cache_module, "SessionLocal", Mock(return_value=session))

    cache.check()
    assert cache.eligible(form_id, "detail_view")
    assert not cache.eligible(form_id, "link_click")

    rows[:] = [(form_id, "URL", "https://example.org/form")]
    cache.check()
    assert cache.eligible(form_id, "link_click")

    cache.committed(SimpleNamespace(id=form_id, deleted_at=object()))
    assert not cache.eligible(form_id, "detail_view")
    cache.check()
    assert cache.eligible(form_id, "detail_view")
    rows.clear()
    cache.check()
    assert not cache.eligible(form_id, "detail_view")


def test_staff_check_does_not_replace_unchanged_snapshot(monkeypatch):
    cache = cache_module.StaffFormCache()
    form_id = uuid4()
    monkeypatch.setattr(
        cache_module,
        "SessionLocal",
        Mock(
            return_value=_session_with_rows(
                [
                    (form_id, "URL", "https://example.org/form"),
                ]
            )
        ),
    )

    cache.check()
    snapshot = cache._forms
    cache.check()

    assert cache._forms is snapshot


def test_staff_delete_updates_cache_only_after_commit(monkeypatch):
    cache = cache_module.StaffFormCache()
    cache._loaded = True
    form_id = uuid4()
    form = SimpleNamespace(
        id=form_id,
        deleted_at=None,
        status="published",
        form_source="URL",
        form_source_url="https://example.org/form",
    )
    cache.committed(form)
    monkeypatch.setattr(forms_service, "engagement_cache", cache)
    monkeypatch.setattr(
        forms_service.FormService, "get_form_by_id", Mock(return_value=form)
    )
    monkeypatch.setattr(forms_service.FormService, "_audit_log", Mock())
    db = Mock()

    def commit():
        assert cache.eligible(form_id, "detail_view")

    db.commit.side_effect = commit
    assert forms_service.FormService.delete_form(db, form_id, uuid4()) is True
    db.commit.assert_called_once_with()
    assert db.refresh.call_count == 2
    db.refresh.assert_called_with(form)
    assert not cache.eligible(form_id, "detail_view")


def test_out_of_order_commit_callbacks_keep_latest_staff_form_state():
    cache = cache_module.StaffFormCache()
    cache._loaded = True
    form_id = uuid4()
    newer = SimpleNamespace(
        id=form_id,
        deleted_at=None,
        form_source="URL",
        form_source_url=None,
    )
    older = SimpleNamespace(
        id=form_id,
        deleted_at=None,
        form_source="URL",
        form_source_url="https://example.org/form",
    )
    cache.committed(newer)
    db = Mock()
    db.refresh.side_effect = lambda form: setattr(form, "form_source_url", None)

    cache.committed(older, db)

    assert cache.eligible(form_id, "detail_view")
    assert not cache.eligible(form_id, "link_click")
    db.refresh.assert_called_once_with(older)


def test_staff_failed_delete_commit_does_not_update_cache(monkeypatch):
    cache = cache_module.StaffFormCache()
    cache._loaded = True
    form_id = uuid4()
    form = SimpleNamespace(
        id=form_id,
        deleted_at=None,
        status="published",
        form_source="URL",
        form_source_url="https://example.org/form",
    )
    cache.committed(form)
    monkeypatch.setattr(forms_service, "engagement_cache", cache)
    monkeypatch.setattr(
        forms_service.FormService, "get_form_by_id", Mock(return_value=form)
    )
    db = Mock()
    db.commit.side_effect = RuntimeError("commit failed")

    with pytest.raises(RuntimeError, match="commit failed"):
        forms_service.FormService.delete_form(db, form_id, uuid4())

    db.refresh.assert_not_called()
    assert cache.eligible(form_id, "detail_view")


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 300),
        ("", 300),
        ("invalid", 300),
        ("0", 300),
        ("-1", 300),
        ("nan", 300),
        ("inf", 300),
        ("2.5", 150),
    ],
)
def test_staff_interval_fallback(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("STAFF_ENGAGEMENT_CACHE_CHECK_MINUTES", raising=False)
    else:
        monkeypatch.setenv("STAFF_ENGAGEMENT_CACHE_CHECK_MINUTES", value)
    assert cache_module.check_interval_seconds() == expected
