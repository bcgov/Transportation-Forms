"""US-008: Staff attachment handoff qualifies one daily download increment."""

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from backend.auth.jwt_handler import TokenData
from backend.routes import forms as forms_route
from backend.services import daily_engagement
from backend.services.s3_service import S3ObjectNotFound
from fastapi import HTTPException, Request


async def _body(response):
    return [chunk async for chunk in response.body_iterator]


@pytest.fixture
def download(monkeypatch):
    form_id = uuid4()
    user_id = uuid4()
    form = SimpleNamespace(
        id=form_id,
        status="published",
        form_source="Download",
        form_attachment_url="uploads/us008.pdf",
        form_attachment_filename="us008.pdf",
        file_type="pdf",
    )
    db = MagicMock()
    user = TokenData(
        sub=str(user_id),
        email="test@example.com",
        name="Staff user",
        roles=["staff"],
        permissions=["form:read"],
    )
    monkeypatch.setattr(forms_route.FormService, "get_form_by_id", lambda *_: form)
    monkeypatch.setattr(forms_route, "_is_staff_viewer_only", lambda *_: False)
    stream = MagicMock(return_value=iter([b"first", b"second"]))
    monkeypatch.setattr(forms_route.s3_service, "stream_object", stream)
    record = MagicMock()
    monkeypatch.setattr(forms_route, "record_daily_engagement", record)
    futures = []
    original_submit = forms_route.dispatcher.submit

    def submit(*args):
        future = original_submit(*args)
        if future is not None:
            futures.append(future)
        return future

    monkeypatch.setattr(forms_route.dispatcher, "submit", submit)

    def request(method="GET", headers=None):
        raw_headers = [
            (key.lower().encode(), value.encode())
            for key, value in (headers or {}).items()
        ]
        return Request(
            {
                "type": "http",
                "method": method,
                "path": f"/api/v1/forms/{form_id}/file",
                "headers": raw_headers,
                "client": ("127.0.0.1", 55000),
            }
        )

    def handoff(method="GET", headers=None):
        return asyncio.run(
            forms_route.download_form_attachment(
                str(form_id), request(method, headers), user, db
            )
        )

    return SimpleNamespace(
        form=form,
        db=db,
        record=record,
        wait_writes=lambda: [future.result(timeout=3) for future in futures],
        stream=stream,
        handoff=handoff,
        user=user,
        request=request,
    )


def test_full_get_handoff_counts_once_and_preserves_audit(download):
    response = download.handoff(
        headers={"X-Portal-Source": "Public", "User-Agent": "AutomatedTestBot"}
    )
    download.wait_writes()

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment;")
    download.stream.assert_called_once_with("uploads/us008.pdf")
    download.db.commit.assert_called_once_with()
    audit = download.db.add.call_args.args[0]
    assert audit.action == "FORM_DOWNLOAD"
    assert audit.entity_id == str(download.form.id)
    assert audit.new_values["filename"] == "us008.pdf"
    assert audit.user_agent == "AutomatedTestBot"
    assert download.record.call_args.args[:3] == (download.form.id, "download", "Staff")
    assert isinstance(download.record.call_args.args[3], date)
    assert asyncio.run(_body(response)) == [b"first", b"second"]
    assert download.record.call_args.args[:3] == (download.form.id, "download", "Staff")


@pytest.mark.parametrize(
    ("method", "headers"),
    [
        ("GET", {"Range": "bytes=0-2"}),
        ("GET", {"rAnGe": "bytes=0-2", "X-Portal-Source": "Public"}),
        ("HEAD", {}),
    ],
)
def test_head_and_range_do_not_count_even_if_stream_opens(download, method, headers):
    response = download.handoff(method, headers)

    assert response.status_code == 200
    download.stream.assert_called_once_with("uploads/us008.pdf")
    download.db.commit.assert_called_once_with()
    download.record.assert_not_called()


def test_same_caller_full_file_retries_are_each_counted(download):
    for _ in range(3):
        response = download.handoff()
        assert response.status_code == 200
    download.wait_writes()

    assert download.record.call_count == 3
    assert download.db.commit.call_count == 3
    assert all(
        call.args[:3] == (download.form.id, "download", "Staff")
        and isinstance(call.args[3], date)
        for call in download.record.call_args_list
    )


def test_unpublished_form_denied_to_staff_viewer_before_opening_stream(
    download, monkeypatch
):
    download.form.status = "draft"
    monkeypatch.setattr(forms_route, "_is_staff_viewer_only", lambda *_: True)

    with pytest.raises(HTTPException) as caught:
        download.handoff()

    assert caught.value.status_code == 404
    download.stream.assert_not_called()
    download.db.add.assert_not_called()
    download.record.assert_not_called()


@pytest.mark.parametrize(
    "failure", ["missing_form", "missing_file", "missing_s3", "s3_error", "audit"]
)
def test_pre_handoff_failure_never_counts(download, monkeypatch, failure):
    if failure == "missing_form":
        monkeypatch.setattr(forms_route.FormService, "get_form_by_id", lambda *_: None)
        expected = 404
    elif failure == "missing_file":
        download.form.form_attachment_url = None
        expected = 404
    elif failure == "missing_s3":
        download.stream.side_effect = S3ObjectNotFound()
        expected = 404
    elif failure == "s3_error":
        download.stream.side_effect = RuntimeError("object store failure")
        expected = 502
    else:
        download.db.commit.side_effect = RuntimeError("audit unavailable")
        expected = 500

    with pytest.raises(HTTPException) as caught:
        download.handoff()
    assert caught.value.status_code == expected
    download.record.assert_not_called()
    if failure == "audit":
        download.db.rollback.assert_called_once_with()


def test_later_stream_failure_does_not_reverse_or_repeat_handoff(download):
    def interrupted():
        yield b"first"
        raise OSError("client disconnected after handoff")

    download.stream.return_value = interrupted()
    response = download.handoff()

    async def consume():
        chunks = []
        with pytest.raises(OSError, match="client disconnected"):
            async for chunk in response.body_iterator:
                chunks.append(chunk)
        return chunks

    assert asyncio.run(consume()) == [b"first"]
    download.wait_writes()
    assert download.record.call_args.args[:3] == (download.form.id, "download", "Staff")
    download.db.commit.assert_called_once_with()


def test_known_writer_drop_does_not_block_file_or_audit(download, monkeypatch):
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

    response = download.handoff()
    download.wait_writes()

    assert response.status_code == 200
    assert asyncio.run(_body(response)) == [b"first", b"second"]
    download.db.commit.assert_called_once_with()
    summary.assert_called_once_with("known_capacity")
