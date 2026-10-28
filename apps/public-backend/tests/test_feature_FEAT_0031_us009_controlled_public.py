"""US-009 Public eligibility tests on isolated in-memory form views."""

import logging
import sys
from datetime import datetime
from unittest.mock import MagicMock, Mock
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

import engagement_cache as cache_module
from routes import engagement as signal_route


def test_numberless_public_form_is_listable_but_cannot_signal(
    db, sqlite_engine, public_client, monkeypatch
):
    form_id = uuid4()
    db.execute(
        text(
            "INSERT INTO public_forms_v "
            "(form_id, form_number, title, form_source, form_source_url, keywords) "
            "VALUES (:form_id, NULL, 'Numberless published form', "
            "'URL', :url, :keywords)"
        ),
        {"form_id": str(form_id), "url": "https://example.test/form", "keywords": "[]"},
    )
    db.commit()

    cache = cache_module.PublicFormCache()
    monkeypatch.setattr(cache_module, "SessionLocal", sessionmaker(bind=sqlite_engine))
    cache.check()
    assert cache._loaded
    assert cache._forms == {}

    writer = Mock()
    monkeypatch.setattr(signal_route, "cache", cache)
    monkeypatch.setattr(signal_route, "record_daily_engagement", writer)
    monkeypatch.setattr(signal_route.settings, "PUBLIC_BASE_URL", "http://testserver")
    listing = public_client.get("/api/public/v1/forms?limit=25")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["form_number"] is None
    assert str(form_id) not in listing.text

    for number, expected in ((None, 400), (str(form_id), 400), ("NOTREAL", 404)):
        response = public_client.post(
            "/api/public/v1/engagement/signal",
            json={"form_number": number, "metric": "detail_view"},
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == expected
        assert str(form_id) not in response.text
    writer.assert_not_called()


def test_public_cache_recovers_and_warns_once_per_failure_streak(monkeypatch):
    cache = cache_module.PublicFormCache()
    form_id = uuid4()
    session = MagicMock()
    query = session.__enter__.return_value.query.return_value
    query.filter.return_value = query
    query.all.return_value = [("HWY0001", form_id, "URL", "https://example.test/form")]
    unavailable = {"value": True}

    def session_local():
        if unavailable["value"]:
            raise RuntimeError("private database failure")
        return session

    warnings = Mock()
    monkeypatch.setattr(cache_module, "SessionLocal", session_local)
    monkeypatch.setattr(cache_module.logger, "warning", warnings)

    cache.check()
    assert cache.resolve("HWY0001", "detail_view") is None
    unavailable["value"] = False
    cache.check()
    assert cache.resolve("HWY0001", "link_click") == form_id
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
            assert cache.resolve("HWY0001", "detail_view") == form_id
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
                == "public_cache_check_failed reason=read_failed streak=%d"
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


def test_failed_public_checks_write_fixed_identity_free_stdout(monkeypatch, capfd):
    cache = cache_module.PublicFormCache()
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
    assert stdout.count("public_cache_check_failed reason=read_failed streak=") == 20
    assert stdout.count("Cache checks have failed 20 consecutive times since ") == 1
    assert "newly eligible forms may be missing on this pod" in stdout
    assert "private@example.test" not in stdout + stderr


def test_external_sql_change_to_older_public_form_is_detected(
    db, sqlite_engine, monkeypatch
):
    old_id, latest_id = uuid4(), uuid4()
    for form_id, number, source, url, updated in (
        (old_id, "OLD", "URL", "https://example.test/form", datetime(2024, 1, 1)),
        (latest_id, "LATEST", "Download", None, datetime(2025, 1, 1)),
    ):
        db.execute(
            text(
                "INSERT INTO public_forms_v "
                "(form_id, form_number, title, form_source, "
                "form_source_url, updated_at) "
                "VALUES (:form_id, :number, 'Fixture', :source, :url, :updated)"
            ),
            {
                "form_id": str(form_id),
                "number": number,
                "source": source,
                "url": url,
                "updated": updated,
            },
        )
    db.commit()
    session_factory = Mock(side_effect=sessionmaker(bind=sqlite_engine))
    monkeypatch.setattr(cache_module, "SessionLocal", session_factory)
    cache = cache_module.PublicFormCache()

    cache.check()
    assert cache.resolve("OLD", "link_click") == old_id
    newest_before = db.execute(
        text("SELECT MAX(updated_at) FROM public_forms_v")
    ).scalar()

    db.execute(
        text("UPDATE public_forms_v SET form_source_url = :url WHERE form_id = :id"),
        {"url": "javascript:alert(1)", "id": str(old_id)},
    )
    db.commit()
    cache.check()
    assert cache.resolve("OLD", "detail_view") == old_id
    assert cache.resolve("OLD", "link_click") is None

    db.execute(
        text("UPDATE public_forms_v SET form_number = :number WHERE form_id = :id"),
        {"number": "NEW", "id": str(old_id)},
    )
    db.commit()
    cache.check()
    assert cache.resolve("OLD", "detail_view") is None
    assert cache.resolve("NEW", "detail_view") == old_id
    assert cache.resolve("LATEST", "detail_view") == latest_id
    assert db.execute(text("SELECT COUNT(*) FROM public_forms_v")).scalar() == 2
    assert (
        db.execute(text("SELECT MAX(updated_at) FROM public_forms_v")).scalar()
        == newest_before
    )
    assert session_factory.call_count == 3
