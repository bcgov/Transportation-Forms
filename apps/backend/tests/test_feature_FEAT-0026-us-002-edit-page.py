"""FEAT-0026 — US-002 tests: PUT /admin/cms/pages/{id}.

Covers the update / concurrency / revision / audit contracts for editing
an existing CMS page.
"""

from __future__ import annotations

import pytest
from fastapi import status

from backend.models import (
    AuditLog,
    CmsPage,
    CmsPageRevision,
    UserRole,
)
from backend.services.cms_pages import CmsPageService


ADMIN_CMS_BASE = "/api/v1/admin/cms/pages"
CMS_PERM = "cms:manage"


def _ensure_admin_has_cms_perm(db, admin_user) -> None:
    user_role = (
        db.query(UserRole).filter(UserRole.user_id == admin_user.id).first()
    )
    role = user_role.role
    perms = list(role.permissions) if isinstance(role.permissions, list) else []
    if CMS_PERM not in perms:
        perms.append(CMS_PERM)
        role.permissions = perms
        db.flush()


@pytest.fixture(autouse=True)
def _admin_cms_perm(db, admin_user):
    _ensure_admin_has_cms_perm(db, admin_user)


def _create_page(client, admin_token_headers, **kwargs):
    """Convenience helper: create a page and return the JSON body."""
    payload = {
        "title": "Original Title",
        "slug": "original-slug",
        "body_html": "<p>Original body</p>",
        "meta_description": "Original meta.",
        "show_in_nav": True,
    }
    payload.update(kwargs)
    resp = client.post(ADMIN_CMS_BASE, json=payload, headers=admin_token_headers)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return resp.json(), resp.headers.get("ETag")


@pytest.mark.integration
class TestUS002EditPage:
    """PUT /admin/cms/pages/{id} — happy paths and validation."""

    def test_tc2_1_update_title_only_bumps_updated_at_and_returns_200(
        self, client, admin_token_headers
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc21")
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"title": "Updated Title"},
            headers={**admin_token_headers, "If-Match": etag},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert resp.json()["title"] == "Updated Title"
        # Body unchanged.
        assert resp.json()["body_html"] == "<p>Original body</p>"
        new_etag = resp.headers.get("ETag")
        assert new_etag and new_etag != etag

    def test_tc2_2_no_op_update_returns_200_without_new_revision(
        self, client, admin_token_headers, db
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc22")
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"title": "Original Title"},  # identical
            headers={**admin_token_headers, "If-Match": etag},
        )
        assert resp.status_code == status.HTTP_200_OK
        # Only the create-time revision exists.
        revs = (
            db.query(CmsPageRevision)
            .filter(CmsPageRevision.page_id == page["id"])
            .all()
        )
        assert len(revs) == 1

    def test_tc2_3_meaningful_change_inserts_a_new_revision(
        self, client, admin_token_headers, db
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc23")
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"body_html": "<p>New body</p>"},
            headers={**admin_token_headers, "If-Match": etag},
        )
        assert resp.status_code == status.HTTP_200_OK
        revs = (
            db.query(CmsPageRevision)
            .filter(CmsPageRevision.page_id == page["id"])
            .order_by(CmsPageRevision.edited_at.asc())
            .all()
        )
        assert len(revs) == 2
        assert revs[1].body_html == "<p>New body</p>"

    def test_tc2_4_missing_if_match_returns_428(
        self, client, admin_token_headers
    ):
        page, _etag = _create_page(client, admin_token_headers, slug="tc24")
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"title": "Something"},
            headers=admin_token_headers,  # no If-Match
        )
        assert resp.status_code == status.HTTP_428_PRECONDITION_REQUIRED

    def test_tc2_5_stale_if_match_returns_412(
        self, client, admin_token_headers
    ):
        page, _etag = _create_page(client, admin_token_headers, slug="tc25")
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"title": "Something"},
            headers={**admin_token_headers, "If-Match": '"stale"'},
        )
        assert resp.status_code == status.HTTP_412_PRECONDITION_FAILED

    def test_tc2_6_wildcard_if_match_accepted(
        self, client, admin_token_headers
    ):
        page, _etag = _create_page(client, admin_token_headers, slug="tc26")
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"title": "Wildcard OK"},
            headers={**admin_token_headers, "If-Match": "*"},
        )
        assert resp.status_code == status.HTTP_200_OK

    def test_tc2_7_body_html_sanitized_on_update(
        self, client, admin_token_headers, db
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc27")
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"body_html": "<p>Clean</p><script>evil()</script>"},
            headers={**admin_token_headers, "If-Match": etag},
        )
        assert resp.status_code == status.HTTP_200_OK
        # Sanitizer strips the script tag entirely.
        row = db.query(CmsPage).filter(CmsPage.id == page["id"]).one()
        assert "script" not in row.body_html.lower()

    def test_tc2_8_audit_event_records_changed_fields(
        self, client, admin_token_headers, db, admin_user
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc28")
        client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"title": "New", "meta_description": "New meta"},
            headers={**admin_token_headers, "If-Match": etag},
        )
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_id == page["id"],
                AuditLog.action == "cms_page.updated",
            )
            .all()
        )
        assert len(audits) == 1
        assert audits[0].user_id == admin_user.id
        changed = set(audits[0].new_values["changed_fields"])
        assert changed == {"title", "meta_description"}

    def test_tc2_9_show_in_nav_toggle_preserves_nav_order(
        self, client, admin_token_headers, db
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc29")
        original_order = (
            db.query(CmsPage).filter(CmsPage.id == page["id"]).one().nav_order
        )
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"show_in_nav": False},
            headers={**admin_token_headers, "If-Match": etag},
        )
        assert resp.status_code == status.HTTP_200_OK
        # US-002 AC5: toggling nav visibility MUST NOT reset nav_order.
        row = db.query(CmsPage).filter(CmsPage.id == page["id"]).one()
        assert row.nav_order == original_order
        assert row.show_in_nav is False

    def test_tc2_10_invalid_title_returns_422(
        self, client, admin_token_headers
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc210")
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"title": "  "},  # whitespace only
            headers={**admin_token_headers, "If-Match": etag},
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_tc2_11_soft_deleted_page_returns_404_on_edit(
        self, client, admin_token_headers, db
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc211")
        # Soft-delete first.
        client.delete(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            headers={**admin_token_headers, "If-Match": etag},
        )
        # Update attempt (with any ETag — page is 404).
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"title": "New"},
            headers={**admin_token_headers, "If-Match": "*"},
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
