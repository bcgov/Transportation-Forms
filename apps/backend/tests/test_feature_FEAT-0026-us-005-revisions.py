"""FEAT-0026 — US-005 tests: revision history + restore-revision."""

from __future__ import annotations

import pytest
from fastapi import status

from backend.models import AuditLog, CmsPage, CmsPageRevision, UserRole


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


def _create_page(client, admin_token_headers, slug="rev-page"):
    resp = client.post(
        ADMIN_CMS_BASE,
        json={
            "title": "First",
            "slug": slug,
            "body_html": "<p>Body v1</p>",
            "meta_description": None,
            "show_in_nav": True,
        },
        headers=admin_token_headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return resp.json(), resp.headers.get("ETag")


def _edit(client, admin_token_headers, page_id, etag, **fields):
    resp = client.put(
        f"{ADMIN_CMS_BASE}/{page_id}",
        json=fields,
        headers={**admin_token_headers, "If-Match": etag},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    return resp.json(), resp.headers.get("ETag")


@pytest.mark.integration
class TestUS005ListRevisions:
    def test_tc5_1_list_revisions_returns_newest_first(
        self, client, admin_token_headers
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc51")
        _, etag2 = _edit(client, admin_token_headers, page["id"], etag, title="Second")
        _edit(client, admin_token_headers, page["id"], etag2, title="Third")
        resp = client.get(
            f"{ADMIN_CMS_BASE}/{page['id']}/revisions",
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        titles = [r["title"] for r in resp.json()]
        assert titles[0] == "Third"
        assert titles[-1] == "First"

    def test_tc5_2_revisions_for_unknown_page_returns_404(
        self, client, admin_token_headers
    ):
        resp = client.get(
            f"{ADMIN_CMS_BASE}/00000000-0000-0000-0000-000000000000/revisions",
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.integration
class TestUS005RestoreRevision:
    def test_tc5r_1_restore_revision_updates_body_and_inserts_new_rev(
        self, client, admin_token_headers, db
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc5r1")
        # Edit to v2.
        _, etag2 = _edit(
            client,
            admin_token_headers,
            page["id"],
            etag,
            body_html="<p>Body v2</p>",
        )
        # Fetch revisions — the first (oldest) is v1.
        revs = client.get(
            f"{ADMIN_CMS_BASE}/{page['id']}/revisions",
            headers=admin_token_headers,
        ).json()
        v1_id = revs[-1]["id"]
        # Restore v1.
        resp = client.post(
            f"{ADMIN_CMS_BASE}/{page['id']}/revisions/{v1_id}/restore",
            headers={**admin_token_headers, "If-Match": etag2},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        row = db.query(CmsPage).filter(CmsPage.id == page["id"]).one()
        assert row.body_html == "<p>Body v1</p>"
        # A new revision snapshot is appended.
        rev_count = (
            db.query(CmsPageRevision)
            .filter(CmsPageRevision.page_id == page["id"])
            .count()
        )
        assert rev_count == 3

    def test_tc5r_2_restore_missing_if_match_returns_428(
        self, client, admin_token_headers
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc5r2")
        _edit(
            client,
            admin_token_headers,
            page["id"],
            etag,
            body_html="<p>Body v2</p>",
        )
        revs = client.get(
            f"{ADMIN_CMS_BASE}/{page['id']}/revisions",
            headers=admin_token_headers,
        ).json()
        v1_id = revs[-1]["id"]
        resp = client.post(
            f"{ADMIN_CMS_BASE}/{page['id']}/revisions/{v1_id}/restore",
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_428_PRECONDITION_REQUIRED

    def test_tc5r_3_restore_soft_deleted_undeletes_page(
        self, client, admin_token_headers, db
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc5r3")
        # Delete it.
        client.delete(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            headers={**admin_token_headers, "If-Match": etag},
        )
        # Fetch revisions.
        revs = client.get(
            f"{ADMIN_CMS_BASE}/{page['id']}/revisions",
            headers=admin_token_headers,
        ).json()
        v1_id = revs[-1]["id"]
        # Get ETag after delete.
        detail = client.get(
            f"{ADMIN_CMS_BASE}/{page['id']}?include_deleted=true",
            headers=admin_token_headers,
        )
        # Restore v1 onto soft-deleted page.
        resp = client.post(
            f"{ADMIN_CMS_BASE}/{page['id']}/revisions/{v1_id}/restore",
            headers={
                **admin_token_headers,
                "If-Match": detail.headers.get("ETag"),
            },
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        row = db.query(CmsPage).filter(CmsPage.id == page["id"]).one()
        assert row.deleted_at is None

    def test_tc5r_4_restore_audit_events(
        self, client, admin_token_headers, db, admin_user
    ):
        page, etag = _create_page(client, admin_token_headers, slug="tc5r4")
        _, etag2 = _edit(
            client,
            admin_token_headers,
            page["id"],
            etag,
            body_html="<p>v2</p>",
        )
        revs = client.get(
            f"{ADMIN_CMS_BASE}/{page['id']}/revisions",
            headers=admin_token_headers,
        ).json()
        v1_id = revs[-1]["id"]
        client.post(
            f"{ADMIN_CMS_BASE}/{page['id']}/revisions/{v1_id}/restore",
            headers={**admin_token_headers, "If-Match": etag2},
        )
        actions = {
            a.action
            for a in db.query(AuditLog)
            .filter(AuditLog.entity_id == page["id"])
            .all()
        }
        assert "cms_page.revision_restored" in actions
