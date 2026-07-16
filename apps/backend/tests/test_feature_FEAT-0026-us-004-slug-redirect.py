"""FEAT-0026 — US-004 tests: slug change + redirect side effects."""

from __future__ import annotations

import pytest
from fastapi import status

from backend.models import AuditLog, CmsPageRedirect, UserRole


ADMIN_CMS_BASE = "/api/v1/admin/cms/pages"
REDIRECTS_URL = "/api/v1/admin/cms/redirects"
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


def _create_page(client, admin_token_headers, slug="original"):
    resp = client.post(
        ADMIN_CMS_BASE,
        json={
            "title": "T",
            "slug": slug,
            "body_html": "<p>x</p>",
            "meta_description": None,
            "show_in_nav": True,
        },
        headers=admin_token_headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return resp.json(), resp.headers.get("ETag")


@pytest.mark.integration
class TestUS004SlugChange:
    def test_tc4_1_slug_change_creates_redirect(
        self, client, admin_token_headers, db
    ):
        page, etag = _create_page(client, admin_token_headers, slug="old-a")
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"slug": "new-a"},
            headers={**admin_token_headers, "If-Match": etag},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        # A redirect from old-a → this page was written.
        redirect = (
            db.query(CmsPageRedirect)
            .filter(CmsPageRedirect.from_slug == "old-a")
            .one_or_none()
        )
        assert redirect is not None
        assert str(redirect.to_page_id) == page["id"]

    def test_tc4_2_slug_change_audit_events(
        self, client, admin_token_headers, db, admin_user
    ):
        page, etag = _create_page(client, admin_token_headers, slug="old-b")
        client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"slug": "new-b"},
            headers={**admin_token_headers, "If-Match": etag},
        )
        actions = {
            a.action
            for a in db.query(AuditLog)
            .filter(AuditLog.entity_id == page["id"])
            .all()
        }
        assert "cms_page.updated" in actions
        assert "cms_page.slug_changed" in actions

    def test_tc4_3_rename_back_deletes_self_redirect(
        self, client, admin_token_headers, db
    ):
        page, etag = _create_page(client, admin_token_headers, slug="ping")
        # ping → pong (creates redirect ping → page).
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"slug": "pong"},
            headers={**admin_token_headers, "If-Match": etag},
        )
        etag2 = resp.headers.get("ETag")
        # Rename back: pong → ping — the redirect from ping → page must
        # be removed to avoid a self-redirect.
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{page['id']}",
            json={"slug": "ping"},
            headers={**admin_token_headers, "If-Match": etag2},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        assert (
            db.query(CmsPageRedirect)
            .filter(CmsPageRedirect.from_slug == "ping")
            .one_or_none()
            is None
        )

    def test_tc4_4_slug_change_conflicting_with_active_page_returns_409(
        self, client, admin_token_headers
    ):
        _a, _a_etag = _create_page(
            client, admin_token_headers, slug="taken-slug"
        )
        b, b_etag = _create_page(
            client, admin_token_headers, slug="original-b"
        )
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{b['id']}",
            json={"slug": "taken-slug"},
            headers={**admin_token_headers, "If-Match": b_etag},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_tc4_5_slug_change_conflicting_with_redirect_returns_409(
        self, client, admin_token_headers
    ):
        # Create A with slug 'origin-a', rename it → creates redirect
        # origin-a → A.  Then create B and try to rename B → origin-a.
        a, a_etag = _create_page(
            client, admin_token_headers, slug="origin-a"
        )
        client.put(
            f"{ADMIN_CMS_BASE}/{a['id']}",
            json={"slug": "moved-a"},
            headers={**admin_token_headers, "If-Match": a_etag},
        )
        b, b_etag = _create_page(
            client, admin_token_headers, slug="other"
        )
        resp = client.put(
            f"{ADMIN_CMS_BASE}/{b['id']}",
            json={"slug": "origin-a"},  # collides with redirect
            headers={**admin_token_headers, "If-Match": b_etag},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_tc4_6_case_insensitive_uniqueness(
        self, client, admin_token_headers
    ):
        # Slugs are normalized to lowercase — try to create ORIGINAL vs original.
        _a, _ = _create_page(client, admin_token_headers, slug="one")
        resp = client.post(
            ADMIN_CMS_BASE,
            json={
                "title": "X",
                "slug": "ONE",  # normalized to 'one'
                "body_html": "<p>x</p>",
                "meta_description": None,
                "show_in_nav": True,
            },
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
