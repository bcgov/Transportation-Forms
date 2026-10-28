"""US-008: Public file-API handoffs, not edge delivery, qualify downloads."""

from datetime import date, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import daily_engagement
import pytest
from routes import forms as forms_route
from sqlalchemy import text


@pytest.fixture
def download(db, public_client, monkeypatch):
    form_id = uuid4()
    form_number = "US008-" + uuid4().hex[:10]
    db.execute(
        text(
            "INSERT INTO public_forms_v "
            "(form_id, form_number, title, s3_key, file_name, file_type, "
            "effective_date, updated_at, keywords) "
            "VALUES (:form_id, :form_number, :title, :s3_key, :file_name, "
            ":file_type, :effective_date, :updated_at, :keywords)"
        ),
        {
            "form_id": str(form_id),
            "form_number": form_number,
            "title": "US-008 download",
            "s3_key": "uploads/us008.pdf",
            "file_name": "us008.pdf",
            "file_type": "pdf",
            "effective_date": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 1, 1),
            "keywords": "[]",
        },
    )
    db.commit()
    record = MagicMock()
    audit = MagicMock()
    monkeypatch.setattr(forms_route, "record_daily_engagement", record)
    monkeypatch.setattr(forms_route, "log_form_download", audit)
    futures = []
    original_submit = forms_route.dispatcher.submit

    def submit(*args):
        future = original_submit(*args)
        if future is not None:
            futures.append(future)
        return future

    monkeypatch.setattr(forms_route.dispatcher, "submit", submit)
    return {
        "form_id": form_id,
        "form_number": form_number,
        "path": f"/api/public/v1/forms/{form_number}/file",
        "client": public_client,
        "db": db,
        "record": record,
        "audit": audit,
        "futures": futures,
        "wait_writes": lambda: [future.result(timeout=3) for future in futures],
    }


def test_full_get_handoff_counts_once_from_serving_api_and_preserves_audit(download):
    response = download["client"].get(
        download["path"],
        headers={"X-Portal-Source": "Staff", "User-Agent": "AutomatedTestBot"},
    )
    download["wait_writes"]()

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["x-accel-redirect"] == "/internal-s3/uploads/us008.pdf"
    download["record"].assert_called_once()
    assert download["record"].call_args.args[:3] == (
        download["form_id"], "download", "Public"
    )
    assert isinstance(download["record"].call_args.args[3], date)
    download["audit"].assert_called_once()
    args, kwargs = download["audit"].call_args
    assert args[0].headers["user-agent"] == "AutomatedTestBot"
    assert kwargs == {
        "form_number": download["form_number"],
        "filename": "us008.pdf",
    }


@pytest.mark.parametrize(
    ("method", "headers"),
    [
        ("GET", {"Range": "bytes=0-2"}),
        ("GET", {"rAnGe": "bytes=500-"}),
        ("HEAD", {}),
    ],
)
def test_head_and_range_are_excluded_even_when_range_is_ignored(
    download, method, headers
):
    response = download["client"].request(method, download["path"], headers=headers)

    if method == "HEAD":
        assert response.status_code in (200, 405)
    else:
        assert response.status_code == 200
    download["record"].assert_not_called()
    assert not download["futures"]
    if response.status_code == 200:
        assert response.headers["x-accel-redirect"].startswith("/internal-s3/")
        download["audit"].assert_called_once()
    else:
        download["audit"].assert_not_called()


def test_repeated_full_get_retries_count_per_handoff_without_session_dedup(download):
    for _ in range(4):
        assert download["client"].get(download["path"]).status_code == 200
    download["wait_writes"]()

    assert download["record"].call_count == 4
    assert download["audit"].call_count == 4
    assert all(
        call.args[:3] == (download["form_id"], "download", "Public")
        and isinstance(call.args[3], date)
        for call in download["record"].call_args_list
    )


@pytest.mark.parametrize(
    "failure",
    ["unknown", "no_file", "future", "audit", "response"],
)
def test_pre_handoff_failure_does_not_count(download, monkeypatch, failure):
    path = download["path"]
    if failure == "unknown":
        path = "/api/public/v1/forms/UNKNOWN-US008/file"
    elif failure == "no_file":
        download["db"].execute(
            text(
                "UPDATE public_forms_v SET s3_key = NULL "
                "WHERE form_number = :form_number"
            ),
            {"form_number": download["form_number"]},
        )
        download["db"].commit()
    elif failure == "future":
        download["db"].execute(
            text(
                "UPDATE public_forms_v SET effective_date = :future "
                "WHERE form_number = :form_number"
            ),
            {"future": datetime(2999, 1, 1), "form_number": download["form_number"]},
        )
        download["db"].commit()
    elif failure == "audit":
        download["audit"].side_effect = RuntimeError("audit unavailable")
    else:
        monkeypatch.setattr(
            forms_route,
            "_content_disposition",
            MagicMock(side_effect=RuntimeError("response construction failed")),
        )

    response = download["client"].get(path)

    assert response.status_code == (
        404 if failure in ("unknown", "no_file", "future") else 500
    )
    assert "x-accel-redirect" not in response.headers
    download["record"].assert_not_called()
    assert not download["futures"]
    if failure in ("audit", "response"):
        download["audit"].assert_called_once()
    else:
        download["audit"].assert_not_called()


def test_api_handoff_count_is_not_reversed_or_repeated_by_later_edge_fetch(download):
    response = download["client"].get(download["path"])
    download["wait_writes"]()
    assert response.status_code == 200
    assert response.headers["x-accel-redirect"]
    # The API returns a redirect header; TestClient does not fetch the edge
    # object, and observing the response must not trigger a second increment.
    assert response.content == b""
    download["record"].assert_called_once()
    assert download["record"].call_args.args[:3] == (
        download["form_id"], "download", "Public"
    )
    assert isinstance(download["record"].call_args.args[3], date)


def test_known_writer_drop_leaves_response_and_audit_intact(download, monkeypatch):
    monkeypatch.setattr(
        forms_route, "record_daily_engagement", daily_engagement.record_daily_engagement
    )
    monkeypatch.setattr(
        daily_engagement,
        "get_writer",
        MagicMock(side_effect=daily_engagement.WriterInitializing),
    )
    summary = MagicMock()
    monkeypatch.setattr(daily_engagement.summary, "record", summary)

    response = download["client"].get(download["path"])
    download["wait_writes"]()

    assert response.status_code == 200
    assert response.headers["x-accel-redirect"].startswith("/internal-s3/")
    download["audit"].assert_called_once()
    summary.assert_called_once_with("known_capacity")
