"""US-009 Public signal validation and per-pod cache contracts."""

import json
from threading import Event
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import engagement_cache as cache_module
from routes import engagement as signal_route


@pytest.fixture()
def signal_client(monkeypatch):
    app = FastAPI()
    app.include_router(signal_route.router)
    cache = cache_module.PublicFormCache()
    cache._loaded = True
    writer = Mock()
    monkeypatch.setattr(signal_route, "cache", cache)
    monkeypatch.setattr(signal_route, "record_daily_engagement", writer)
    monkeypatch.setattr(
        signal_route.settings, "PUBLIC_BASE_URL", "https://forms.example.org"
    )
    with TestClient(app) as client:
        yield client, cache, writer


def _post(client, body, *, headers=None):
    return client.post(
        "/api/public/v1/engagement/signal",
        content=body,
        headers={
            "origin": "https://forms.example.org",
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


def test_public_signals_resolve_number_and_write_once_per_request(signal_client):
    client, cache, writer = signal_client
    form_id = uuid4()
    cache._forms["H 123"] = (form_id, True)

    for metric in ("detail_view", "link_click", "detail_view"):
        response = _post(client, json.dumps({"form_number": "H 123", "metric": metric}))
        assert response.status_code == 202
        assert response.json() == {"accepted": True}
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"

    assert [call.args for call in writer.call_args_list] == [
        (form_id, "detail_view", "Public"),
        (form_id, "link_click", "Public"),
        (form_id, "detail_view", "Public"),
    ]
    assert str(form_id) not in str(response.json())


def test_escaped_unicode_public_form_number_fits_signal_limit(signal_client):
    client, cache, writer = signal_client
    form_id = uuid4()
    number = "\U00010400" * 70
    cache._forms[number] = (form_id, False)
    body = json.dumps({"form_number": number, "metric": "detail_view"})
    assert len(body.encode("utf-8")) > 192

    response = _post(client, body)

    assert response.status_code == 202
    writer.assert_called_once_with(form_id, "detail_view", "Public")


@pytest.mark.parametrize(
    ("body", "headers", "status"),
    [
        ('{"form_number":"H-123","metric":"detail_view"}', {}, 400),
        ('{"form_number":" H123","metric":"detail_view"}', {}, 400),
        ('{"form_number":"H123\\n","metric":"detail_view"}', {}, 400),
        ('{"form_number":"x","metric":"detail_view","portal":"Staff"}', {}, 400),
        ('{"form_number":"x","form_number":"y","metric":"detail_view"}', {}, 400),
        ('{"form_number":"x","metric":"download"}', {}, 400),
        ('{"form_number":1,"metric":"detail_view"}', {}, 400),
        ("not json", {}, 400),
        (
            '{"form_number":"x","metric":"detail_view"}',
            {"content-type": "text/plain"},
            415,
        ),
        ("x" * 1025, {}, 413),
        (
            '{"form_number":"x","metric":"detail_view"}',
            {"origin": "https://other.example.org"},
            403,
        ),
        ('{"form_number":"x","metric":"detail_view"}', {"origin": ""}, 403),
    ],
)
def test_invalid_public_signals_never_reach_writer(
    signal_client, body, headers, status
):
    client, _, writer = signal_client
    response = _post(client, body, headers=headers)

    assert response.status_code == status
    assert response.json() == {"accepted": False}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    writer.assert_not_called()


def test_public_referrer_fallback_and_cache_rejects_unknown_or_disabled_link(
    signal_client,
):
    client, cache, writer = signal_client
    form_id = uuid4()
    cache._forms["H123"] = (form_id, False)
    body = json.dumps({"form_number": "H123", "metric": "detail_view"})

    assert (
        _post(
            client,
            body,
            headers={"origin": "", "referer": "https://forms.example.org/forms"},
        ).status_code
        == 403
    )
    response = client.post(
        "/api/public/v1/engagement/signal",
        content=body,
        headers={
            "referer": "https://forms.example.org/forms",
            "content-type": "application/json",
        },
    )
    assert response.status_code == 202
    assert (
        _post(
            client, json.dumps({"form_number": "H123", "metric": "link_click"})
        ).status_code
        == 404
    )
    assert (
        _post(
            client, json.dumps({"form_number": "MISSING", "metric": "detail_view"})
        ).status_code
        == 404
    )
    writer.assert_called_once_with(form_id, "detail_view", "Public")


def test_public_cache_fails_closed_then_keeps_last_good_and_warns_once(monkeypatch):
    cache = cache_module.PublicFormCache()
    form_id = uuid4()
    monkeypatch.setattr(
        cache_module, "SessionLocal", Mock(side_effect=RuntimeError("private data"))
    )
    warning = Mock()
    monkeypatch.setattr(cache_module.logger, "warning", warning)

    cache.check()
    assert cache.resolve("H123", "detail_view") is None
    assert cache._failures == 1

    monkeypatch.setattr(
        cache_module,
        "SessionLocal",
        Mock(
            return_value=_session_with_rows(
                [
                    ("H123", form_id, "URL", "https://example.org/form"),
                ]
            )
        ),
    )
    cache.check()
    assert cache.resolve("H123", "detail_view") == form_id
    assert cache.resolve("H123", "link_click") == form_id
    assert cache._failures == 0

    monkeypatch.setattr(
        cache_module, "SessionLocal", Mock(side_effect=RuntimeError("private data"))
    )
    warning.reset_mock()
    for _ in range(21):
        cache.check()
    assert cache.resolve("H123", "detail_view") == form_id
    assert cache._failures == 21
    assert len(warning.call_args_list) == 22
    assert [call.args[0] for call in warning.call_args_list].count(
        "Cache checks have failed 20 consecutive times since %s. "
        "Engagement counts for newly eligible forms may be missing on this pod; "
        "stale forms may still be counted."
    ) == 1
    assert warning.call_args_list[20].args[1] == cache._first_failure.isoformat()
    assert all("private data" not in str(call) for call in warning.call_args_list)


def test_public_startup_cache_failure_keeps_application_available(monkeypatch):
    from main import app as public_app

    cache = cache_module.PublicFormCache()
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
    warning = Mock()
    monkeypatch.setattr(cache_module.logger, "warning", warning)

    with TestClient(public_app) as client:
        assert checked.wait(timeout=3)
        assert client.get("/healthz").status_code == 200
        assert cache.resolve("H123", "detail_view") is None

    assert cache._failures == 1
    warning.assert_called_once_with(
        "public_cache_check_failed reason=read_failed streak=%d", 1
    )


def test_public_check_detects_link_and_membership_changes_without_unneeded_reload(
    monkeypatch,
):
    cache = cache_module.PublicFormCache()
    form_id = uuid4()
    numberless_id = uuid4()
    rows = [
        ("H123", form_id, "URL", "javascript:alert(1)"),
        (None, numberless_id, "URL", "https://example.org/"),
    ]
    monkeypatch.setattr(
        cache_module, "SessionLocal", Mock(return_value=_session_with_rows(rows))
    )

    cache.check()
    snapshot = cache._forms
    assert cache.resolve("H123", "detail_view") == form_id
    assert cache.resolve("H123", "link_click") is None
    assert len(snapshot) == 1
    cache.check()
    assert cache._forms is snapshot

    rows[:] = [("H123", form_id, "URL", "https://example.org/form")]
    cache.check()
    assert cache.resolve("H123", "link_click") == form_id
    rows.clear()
    cache.check()
    assert cache.resolve("H123", "detail_view") is None


def test_public_cache_omits_future_effective_forms(db, sqlite_engine, monkeypatch):
    from datetime import datetime, timedelta
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    from routes.forms import _today_vancouver

    future_id, current_id = uuid4(), uuid4()
    for form_id, number, effective_date in (
        (future_id, "FUTURE", _today_vancouver() + timedelta(days=1)),
        (current_id, "CURRENT", _today_vancouver()),
    ):
        db.execute(
            text(
                "INSERT INTO public_forms_v "
                "(form_id, form_number, title, effective_date, "
                "form_source, form_source_url) "
                "VALUES (:id, :number, 'Test', :effective, "
                "'URL', 'https://example.org/form')"
            ),
            {
                "id": str(form_id),
                "number": number,
                "effective": datetime.combine(effective_date, datetime.min.time()),
            },
        )
    db.commit()
    monkeypatch.setattr(cache_module, "SessionLocal", sessionmaker(bind=sqlite_engine))

    cache = cache_module.PublicFormCache()
    cache.check()

    assert cache.resolve("FUTURE", "detail_view") is None
    assert cache.resolve("CURRENT", "detail_view") == current_id


def test_public_cache_rejects_malformed_http_destination(monkeypatch):
    cache = cache_module.PublicFormCache()
    form_id = uuid4()
    monkeypatch.setattr(
        cache_module,
        "SessionLocal",
        Mock(
            return_value=_session_with_rows(
                [
                    ("H123", form_id, "URL", "https://bad host/form"),
                ]
            )
        ),
    )
    cache.check()
    assert cache.resolve("H123", "detail_view") == form_id
    assert cache.resolve("H123", "link_click") is None


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
def test_public_interval_fallback(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("PUBLIC_ENGAGEMENT_CACHE_CHECK_MINUTES", raising=False)
    else:
        monkeypatch.setenv("PUBLIC_ENGAGEMENT_CACHE_CHECK_MINUTES", value)
    assert cache_module.check_interval_seconds() == expected
