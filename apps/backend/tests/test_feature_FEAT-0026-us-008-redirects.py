"""FEAT-0026 — US-008 tests: redirect admin API."""

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


def _create_page_with_redirect(client, admin_token_headers):
    """Create a page, then rename it — leaving a redirect row behind."""
    resp = client.post(
        ADMIN_CMS_BASE,
        json={
            "title": "T",
            "slug": "orig-slug",
            "body_html": "<p>x</p>",
            "meta_description": None,
            "show_in_nav": True,
        },
        headers=admin_token_headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED
    page = resp.json()
    etag = resp.headers.get("ETag")
    # Rename → redirect written.
    rn = client.put(
        f"{ADMIN_CMS_BASE}/{page['id']}",
        json={"slug": "new-slug"},
        headers={**admin_token_headers, "If-Match": etag},
    )
    assert rn.status_code == status.HTTP_200_OK, rn.text
    return page


@pytest.mark.integration
class TestUS008RedirectList:
    def test_tc8_1_list_returns_redirects_with_target_slug(
        self, client, admin_token_headers
    ):
        _create_page_with_redirect(client, admin_token_headers)
        resp = client.get(REDIRECTS_URL, headers=admin_token_headers)
        assert resp.status_code == status.HTTP_200_OK
        rows = resp.json()
        assert any(
            r["from_slug"] == "orig-slug" and r["to_slug"] == "new-slug"
            for r in rows
        )


@pytest.mark.integration
class TestUS008RedirectDelete:
    def test_tc8_2_delete_removes_redirect(
        self, client, admin_token_headers, db
    ):
        _create_page_with_redirect(client, admin_token_headers)
        resp = client.get(REDIRECTS_URL, headers=admin_token_headers)
        redirect_id = resp.json()[0]["id"]
        del_resp = client.delete(
            f"{REDIRECTS_URL}/{redirect_id}", headers=admin_token_headers
        )
        assert del_resp.status_code == status.HTTP_204_NO_CONTENT
        assert (
            db.query(CmsPageRedirect)
            .filter(CmsPageRedirect.from_slug == "orig-slug")
            .one_or_none()
            is None
        )

    def test_tc8_3_delete_writes_audit_row(
        self, client, admin_token_headers, db, admin_user
    ):
        _create_page_with_redirect(client, admin_token_headers)
        resp = client.get(REDIRECTS_URL, headers=admin_token_headers)
        redirect_id = resp.json()[0]["id"]
        client.delete(
            f"{REDIRECTS_URL}/{redirect_id}", headers=admin_token_headers
        )
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "cms_redirect.deleted",
                AuditLog.entity_id == redirect_id,
            )
            .all()
        )
        assert audits
        assert audits[-1].user_id == admin_user.id

    def test_tc8_4_delete_unknown_returns_404(
        self, client, admin_token_headers
    ):
        resp = client.delete(
            f"{REDIRECTS_URL}/00000000-0000-0000-0000-000000000000",
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND
