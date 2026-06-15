"""FEAT-0005 — Public Forms Portal: published-attachment sync regression tests.

Bug F (FEAT-0005 BUGFIX 2026-06-11):
  When an admin replaces the attachment of an *already-published* form via
  ``PUT /api/v1/forms/{id}``, the new ``form_attachment_url`` is written to
  the ``forms`` table and the previous S3 object is deleted — but the
  matching row in ``form_versions`` (which backs the ``public_forms_v`` DB
  view) was left untouched.  The public-portal download endpoint then
  resolved the *old* ``s3_key`` (now deleted from S3) and the
  ``X-Accel-Redirect`` target returned 404 from S3 — surfacing as a broken
  download on the public portal.

These tests pin the corrected behaviour:

  * Replacing the attachment on a published form retires the previous
    ``FormVersion(is_current=True)`` and inserts a new current row whose
    ``s3_key`` matches the new attachment.
  * Clearing the attachment (``form_attachment_url = None``) on a published
    form retires the current ``FormVersion`` so the public download path
    cleanly returns 404 (rather than pointing at a deleted object).
  * Replacing the attachment on a *draft* form does **not** create a
    ``FormVersion`` row — version rows are only created when a form
    becomes (or remains) published.
  * Repeatedly setting the same attachment URL on a published form is a
    no-op (does not duplicate ``FormVersion`` rows).
  * Switching ``form_source`` from ``Download`` → ``URL`` on a published
    form retires the current ``FormVersion``.

Run standalone::

    pytest apps/backend/tests/test_feature_FEAT_0005_published_attachment_sync.py -v
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from backend.models import Form, FormVersion
from backend.services.forms import FormService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_published_download_form(
    db, creator_id, *, s3_key: str = "uploads/orig.pdf", filename: str = "orig.pdf"
):
    """Insert a Download-source form already in ``published`` status with a
    matching current ``FormVersion`` row.

    Bypasses the workflow service so the test exercises the
    *attachment-replacement* code path in isolation.
    """
    form = Form(
        id=uuid.uuid4(),
        title="Published Download Form",
        description="Already published; we are about to swap its attachment.",
        status="published",
        is_public=True,
        keywords=[],
        created_by_id=creator_id,
        form_source="Download",
        form_attachment_url=s3_key,
        form_attachment_filename=filename,
        file_type="pdf",
    )
    db.add(form)
    db.flush()

    fv = FormVersion(
        form_id=form.id,
        version_number=1,
        s3_key=s3_key,
        file_name=filename,
        file_size=1000,
        file_type="pdf",
        is_current=True,
        uploaded_by_id=creator_id,
    )
    db.add(fv)
    db.commit()
    db.refresh(form)
    return form


def _current_versions(db, form_id):
    return (
        db.query(FormVersion)
        .filter(
            FormVersion.form_id == form_id,
            FormVersion.is_current.is_(True),
            FormVersion.deleted_at.is_(None),
        )
        .all()
    )


def _all_active_versions(db, form_id):
    return (
        db.query(FormVersion)
        .filter(
            FormVersion.form_id == form_id,
            FormVersion.deleted_at.is_(None),
        )
        .all()
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUpdateFormReSyncsVersionWhenAttachmentChanges:
    """Bug F: replacing the attachment on a published form must re-sync the
    current ``FormVersion`` row that backs ``public_forms_v``."""

    @pytest.mark.integration
    @patch("backend.services.s3_service.delete_file")
    @patch("backend.services.s3_service.get_object_size", return_value=4242)
    def test_replacing_attachment_on_published_form_retires_and_inserts(
        self, mock_size, mock_delete, db, user_factory
    ):
        editor = user_factory(email="bugf-replace@example.com")
        form = _make_published_download_form(
            db, editor.id, s3_key="uploads/orig.pdf", filename="orig.pdf"
        )

        FormService.update_form(
            db=db,
            form_id=form.id,
            updated_by_id=editor.id,
            form_attachment_url="uploads/replacement.pdf",
            form_attachment_filename="replacement.pdf",
            file_type="pdf",
        )

        current = _current_versions(db, form.id)
        assert len(current) == 1, (
            f"Exactly one is_current row expected; got {len(current)}: "
            f"{[v.s3_key for v in current]}"
        )
        assert current[0].s3_key == "uploads/replacement.pdf"
        assert current[0].file_name == "replacement.pdf"

        # The previous row must still exist as is_current=False so audit
        # history is preserved.
        all_active = _all_active_versions(db, form.id)
        retired = [v for v in all_active if not v.is_current]
        assert any(v.s3_key == "uploads/orig.pdf" for v in retired), (
            "Original FormVersion should be retired, not deleted"
        )

        # Confirm the old S3 object was deleted.
        mock_delete.assert_called_once_with("uploads/orig.pdf")

    @pytest.mark.integration
    @patch("backend.services.s3_service.delete_file")
    @patch("backend.services.s3_service.get_object_size", return_value=0)
    def test_clearing_attachment_on_published_form_retires_current_version(
        self, mock_size, mock_delete, db, user_factory
    ):
        editor = user_factory(email="bugf-clear@example.com")
        form = _make_published_download_form(db, editor.id)

        FormService.update_form(
            db=db,
            form_id=form.id,
            updated_by_id=editor.id,
            form_attachment_url=None,
            form_attachment_filename=None,
        )

        current = _current_versions(db, form.id)
        assert current == [], (
            "No FormVersion may be is_current once the attachment is cleared "
            "— otherwise the public download path serves a stale, deleted key"
        )

    @pytest.mark.integration
    @patch("backend.services.s3_service.delete_file")
    @patch("backend.services.s3_service.get_object_size", return_value=10)
    def test_switching_form_source_away_from_download_retires_current_version(
        self, mock_size, mock_delete, db, user_factory
    ):
        editor = user_factory(email="bugf-source@example.com")
        form = _make_published_download_form(db, editor.id)

        FormService.update_form(
            db=db,
            form_id=form.id,
            updated_by_id=editor.id,
            form_source="URL",
            form_source_url="https://example.gov.bc.ca/form.pdf",
            form_attachment_url=None,
            form_attachment_filename=None,
        )

        assert _current_versions(db, form.id) == []

    @pytest.mark.integration
    @patch("backend.services.s3_service.delete_file")
    @patch("backend.services.s3_service.get_object_size", return_value=10)
    def test_same_attachment_on_published_form_is_no_op(
        self, mock_size, mock_delete, db, user_factory
    ):
        """Re-PUTting the same attachment URL must not duplicate version rows
        nor delete the still-current S3 object."""
        editor = user_factory(email="bugf-noop@example.com")
        form = _make_published_download_form(
            db, editor.id, s3_key="uploads/keep.pdf", filename="keep.pdf"
        )

        FormService.update_form(
            db=db,
            form_id=form.id,
            updated_by_id=editor.id,
            form_attachment_url="uploads/keep.pdf",
            form_attachment_filename="keep.pdf",
        )

        current = _current_versions(db, form.id)
        assert len(current) == 1
        assert current[0].s3_key == "uploads/keep.pdf"
        mock_delete.assert_not_called()


class TestUpdateFormDoesNotSyncForUnpublishedForms:
    """Sanity check: draft forms must not auto-create a FormVersion when
    the attachment changes — version rows only enter scope on publish."""

    @pytest.mark.integration
    @patch("backend.services.s3_service.delete_file")
    @patch("backend.services.s3_service.get_object_size", return_value=1)
    def test_draft_form_attachment_change_does_not_create_version(
        self, mock_size, mock_delete, db, user_factory
    ):
        editor = user_factory(email="bugf-draft@example.com")
        form = Form(
            id=uuid.uuid4(),
            title="Draft form",
            description="",
            status="draft",
            is_public=False,
            keywords=[],
            created_by_id=editor.id,
            form_source="Download",
            form_attachment_url="uploads/draft-a.pdf",
            form_attachment_filename="draft-a.pdf",
            file_type="pdf",
        )
        db.add(form)
        db.commit()

        FormService.update_form(
            db=db,
            form_id=form.id,
            updated_by_id=editor.id,
            form_attachment_url="uploads/draft-b.pdf",
            form_attachment_filename="draft-b.pdf",
        )

        assert _all_active_versions(db, form.id) == []
