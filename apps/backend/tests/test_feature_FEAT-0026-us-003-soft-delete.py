"""FEAT-0026 — US-003 tests: DELETE + restore for CMS pages.

Covers soft delete, restore with/without alternate slug, and public
visibility gating (nav_order cleared, active list excludes deleted).
"""

from __future__ import annotations

import pytest
from fastapi import status

from backend.models import AuditLog, CmsPage, UserRole


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
    payload = {
        "title": "T",
        "slug": "delete-me",
        "body_html": "<p>x</p>",
        "meta_description": None,
        "show_in_nav": True,
    }
    payload.update(kwargs)
    resp = client.post(ADMIN_CMS_BASE, json=payload, headers=admin_token_headers)
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return resp.json(), resp.headers.get("ETag")


@pytest.mark.integration
class TestUS003SoftDelete:
    def test_tc3_1_delete_marks_deleted_at_and_clears_nav_order(
        self, client, admin_token_headers, db
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc31")
        resp = client.delete(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            headers={**admin_token_headers, "If-Match": etag},
        )
        assert resp.status_code == status.HTTP_200_OK
        row = db.query(CmsPage).filter(CmsPage.id == page["id"]).one()
        assert row.deleted_at is not None
        assert row.nav_order is None

    def test_tc3_2_missing_if_match_returns_428(
        self, client, admin_token_headers
    ):
        page, _etag = _create_page(client, admin_token_headers, slug="tc32")
        resp = client.delete(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_428_PRECONDITION_REQUIRED

    def test_tc3_3_stale_if_match_returns_412(
        self, client, admin_token_headers
    ):
        page, _etag = _create_page(client, admin_token_headers, slug="tc33")
        resp = client.delete(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            headers={**admin_token_headers, "If-Match": '"stale"'},
        )
        assert resp.status_code == status.HTTP_412_PRECONDITION_FAILED

    def test_tc3_4_audit_row_written_on_delete(
        self, client, admin_token_headers, db, admin_user
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc34")
        client.delete(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            headers={**admin_token_headers, "If-Match": etag},
        )
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_id == page["id"],
                AuditLog.action == "cms_page.deleted",
            )
            .all()
        )
        assert len(audits) == 1
        assert audits[0].user_id == admin_user.id

    def test_tc3_5_deleted_page_not_in_list(
        self, client, admin_token_headers
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc35")
        client.delete(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            headers={**admin_token_headers, "If-Match": etag},
        )
        resp = client.get(ADMIN_CMS_BASE, headers=admin_token_headers)
        assert resp.status_code == status.HTTP_200_OK
        slugs = {p["slug"] for p in resp.json()["pages"]}
        assert "tc35" not in slugs

    def test_tc3_6_deleted_page_visible_with_include_deleted(
        self, client, admin_token_headers
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc36")
        client.delete(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            headers={**admin_token_headers, "If-Match": etag},
        )
        resp = client.get(
            f"{ADMIN_CMS_BASE}?include_deleted=true",
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        slugs = {p["slug"] for p in resp.json()["pages"]}
        assert "tc36" in slugs

    def test_tc3_7_deleted_page_get_returns_404_by_default(
        self, client, admin_token_headers
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc37")
        client.delete(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            headers={**admin_token_headers, "If-Match": etag},
        )
        resp = client.get(
            f"{ADMIN_CMS_BASE}/{page['id']}", headers=admin_token_headers
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestUS003Restore:
    def test_tc3r_1_restore_clears_deleted_at_and_reassigns_nav_order(
        self, client, admin_token_headers, db
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc3r1")
        client.delete(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            headers={**admin_token_headers, "If-Match": etag},
        )
        # ETag after delete must be re-read.
        detail = client.get(
            f"{ADMIN_CMS_BASE}/{page['id']}?include_deleted=true",
            headers=admin_token_headers,
        )
        del_etag = detail.headers.get("ETag")
        resp = client.post(
            f"{ADMIN_CMS_BASE}/{page['id']}/restore",
            headers={**admin_token_headers, "If-Match": del_etag},
        )
        assert resp.status_code == status.HTTP_200_OK
        row = db.query(CmsPage).filter(CmsPage.id == page["id"]).one()
        assert row.deleted_at is None
        assert row.nav_order is not None and row.nav_order >= 1

    def test_tc3r_2_active_page_restore_returns_409(
        self, client, admin_token_headers
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc3r2")
        resp = client.post(
            f"{ADMIN_CMS_BASE}/{page['id']}/restore",
            headers={**admin_token_headers, "If-Match": etag},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_tc3r_3_restore_with_slug_collision_requires_alternate(
        self, client, admin_token_headers
    ):
        # Create page A, delete it, create page B with same slug.
        a, a_etag = _create_page(
            client, admin_token_headers, slug="collide-slug"
        )
        client.delete(
            f"{ADMIN_CMS_BASE}/{a['id']}",
            headers={**admin_token_headers, "If-Match": a_etag},
        )
        _b, _b_etag = _create_page(
            client, admin_token_headers, slug="collide-slug"
        )
        # Now restore A → 409 without alt slug.
        detail = client.get(
            f"{ADMIN_CMS_BASE}/{a['id']}?include_deleted=true",
            headers=admin_token_headers,
        )
        resp = client.post(
            f"{ADMIN_CMS_BASE}/{a['id']}/restore",
            headers={**admin_token_headers, "If-Match": detail.headers.get("ETag")},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_tc3r_4_restore_with_alternate_slug_succeeds(
        self, client, admin_token_headers, db
    ):
        a, a_etag = _create_page(client, admin_token_headers, slug="dup-slug")
        client.delete(
            f"{ADMIN_CMS_BASE}/{a['id']}",
            headers={**admin_token_headers, "If-Match": a_etag},
        )
        # Second page reusing the slug.
        _b, _b_etag = _create_page(
            client, admin_token_headers, slug="dup-slug"
        )
        detail = client.get(
            f"{ADMIN_CMS_BASE}/{a['id']}?include_deleted=true",
            headers=admin_token_headers,
        )
        resp = client.post(
            f"{ADMIN_CMS_BASE}/{a['id']}/restore",
            json={"alternate_slug": "dup-slug-restored"},
            headers={**admin_token_headers, "If-Match": detail.headers.get("ETag")},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        row = db.query(CmsPage).filter(CmsPage.id == a["id"]).one()
        assert row.slug == "dup-slug-restored"

    def test_tc3r_5_restore_audit_row_written(
        self, client, admin_token_headers, db, admin_user
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc3r5")
        client.delete(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            headers={**admin_token_headers, "If-Match": etag},
        )
        detail = client.get(
            f"{ADMIN_CMS_BASE}/{page['id']}?include_deleted=true",
            headers=admin_token_headers,
        )
        client.post(
            f"{ADMIN_CMS_BASE}/{page['id']}/restore",
            headers={**admin_token_headers, "If-Match": detail.headers.get("ETag")},
        )
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_id == page["id"],
                AuditLog.action == "cms_page.restored",
            )
            .all()
        )
        assert len(audits) == 1
        assert audits[0].user_id == admin_user.id
