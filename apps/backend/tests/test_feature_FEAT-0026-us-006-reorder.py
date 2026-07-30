"""FEAT-0026 — US-006 tests: reorder nav pages."""

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


def _create_page(client, admin_token_headers, slug):
    resp = client.post(
        ADMIN_CMS_BASE,
        json={
            "title": slug.title(),
            "slug": slug,
            "body_html": "<p>x</p>",
            "meta_description": None,
            "show_in_nav": True,
        },
        headers=admin_token_headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    return resp.json()


@pytest.mark.integration
class TestUS006Reorder:
    def test_tc6_1_reorder_persists_new_nav_order(
        self, client, admin_token_headers, db
    ):
        a = _create_page(client, admin_token_headers, "tc61-a")
        b = _create_page(client, admin_token_headers, "tc61-b")
        c = _create_page(client, admin_token_headers, "tc61-c")
        list_resp = client.get(ADMIN_CMS_BASE, headers=admin_token_headers)
        list_etag = list_resp.headers.get("ETag")
        resp = client.post(
            f"{ADMIN_CMS_BASE}/reorder",
            json={"ordered_ids": [c["id"], a["id"], b["id"]]},
            headers={**admin_token_headers, "If-Match": list_etag},
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        # DB nav_order values match the new sequence.
        rows = {str(r.id): r.nav_order for r in db.query(CmsPage).all()}
        assert rows[c["id"]] == 1
        assert rows[a["id"]] == 2
        assert rows[b["id"]] == 3

    def test_tc6_2_reorder_requires_if_match(
        self, client, admin_token_headers
    ):
        a = _create_page(client, admin_token_headers, "tc62-a")
        resp = client.post(
            f"{ADMIN_CMS_BASE}/reorder",
            json={"ordered_ids": [a["id"]]},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_428_PRECONDITION_REQUIRED

    def test_tc6_3_reorder_stale_if_match_returns_412(
        self, client, admin_token_headers
    ):
        a = _create_page(client, admin_token_headers, "tc63-a")
        resp = client.post(
            f"{ADMIN_CMS_BASE}/reorder",
            json={"ordered_ids": [a["id"]]},
            headers={**admin_token_headers, "If-Match": '"stale"'},
        )
        assert resp.status_code == status.HTTP_412_PRECONDITION_FAILED

    def test_tc6_4_reorder_partial_list_returns_422(
        self, client, admin_token_headers
    ):
        _a = _create_page(client, admin_token_headers, "tc64-a")
        b = _create_page(client, admin_token_headers, "tc64-b")
        list_resp = client.get(ADMIN_CMS_BASE, headers=admin_token_headers)
        list_etag = list_resp.headers.get("ETag")
        resp = client.post(
            f"{ADMIN_CMS_BASE}/reorder",
            json={"ordered_ids": [b["id"]]},  # missing A
            headers={**admin_token_headers, "If-Match": list_etag},
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_tc6_5_reorder_duplicate_id_returns_422(
        self, client, admin_token_headers
    ):
        a = _create_page(client, admin_token_headers, "tc65-a")
        list_resp = client.get(ADMIN_CMS_BASE, headers=admin_token_headers)
        list_etag = list_resp.headers.get("ETag")
        resp = client.post(
            f"{ADMIN_CMS_BASE}/reorder",
            json={"ordered_ids": [a["id"], a["id"]]},
            headers={**admin_token_headers, "If-Match": list_etag},
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_tc6_6_reorder_audit_row(
        self, client, admin_token_headers, db, admin_user
    ):
        a = _create_page(client, admin_token_headers, "tc66-a")
        b = _create_page(client, admin_token_headers, "tc66-b")
        list_resp = client.get(ADMIN_CMS_BASE, headers=admin_token_headers)
        list_etag = list_resp.headers.get("ETag")
        client.post(
            f"{ADMIN_CMS_BASE}/reorder",
            json={"ordered_ids": [b["id"], a["id"]]},
            headers={**admin_token_headers, "If-Match": list_etag},
        )
        audits = (
            db.query(AuditLog)
            .filter(AuditLog.action == "cms_page.reordered")
            .all()
        )
        assert audits
        latest = audits[-1]
        assert latest.user_id == admin_user.id
        assert latest.new_values["after"] == [b["id"], a["id"]]
