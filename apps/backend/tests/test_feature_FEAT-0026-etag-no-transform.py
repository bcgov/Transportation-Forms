"""FEAT-0026 regression tests for strong ETags behind transforming proxies."""

from __future__ import annotations

import pytest
from fastapi import status

from backend.models import UserRole


ADMIN_CMS_BASE = "/api/v1/admin/cms/pages"
CMS_PERM = "cms:manage"


def _ensure_admin_has_cms_perm(db, admin_user) -> None:
    user_role = (
        db.query(UserRole).filter(UserRole.user_id == admin_user.id).first()
    )
    role = user_role.role
    permissions = (
        list(role.permissions) if isinstance(role.permissions, list) else []
    )
    if CMS_PERM not in permissions:
        permissions.append(CMS_PERM)
        role.permissions = permissions
        db.flush()


@pytest.fixture(autouse=True)
def _admin_cms_perm(db, admin_user):
    _ensure_admin_has_cms_perm(db, admin_user)


def _assert_protected_strong_etag(response) -> str:
    etag = response.headers.get("ETag")
    assert etag
    assert etag.startswith('"') and etag.endswith('"')
    assert not etag.startswith("W/")

    directives = {
        directive.strip().lower()
        for directive in response.headers["Cache-Control"].split(",")
    }
    assert {"private", "no-store", "no-transform"} <= directives
    return etag


@pytest.mark.integration
class TestCmsEtagNoTransform:
    def test_etag_responses_are_not_transformable_and_remain_reusable(
        self, client, admin_token_headers
    ):
        created = client.post(
            ADMIN_CMS_BASE,
            json={
                "title": "ETag proxy regression",
                "slug": "etag-proxy-regression",
                "body_html": "<p>Original body</p>",
                "meta_description": "Regression coverage.",
                "show_in_nav": True,
            },
            headers=admin_token_headers,
        )
        assert created.status_code == status.HTTP_201_CREATED, created.text
        page_id = created.json()["id"]
        _assert_protected_strong_etag(created)

        detail = client.get(
            f"{ADMIN_CMS_BASE}/{page_id}?include_deleted=true",
            headers=admin_token_headers,
        )
        assert detail.status_code == status.HTTP_200_OK
        detail_etag = _assert_protected_strong_etag(detail)

        updated = client.put(
            f"{ADMIN_CMS_BASE}/{page_id}",
            json={"title": "ETag proxy regression updated"},
            headers={**admin_token_headers, "If-Match": detail_etag},
        )
        assert updated.status_code == status.HTTP_200_OK, updated.text
        updated_etag = _assert_protected_strong_etag(updated)

        revisions = client.get(
            f"{ADMIN_CMS_BASE}/{page_id}/revisions",
            headers=admin_token_headers,
        )
        assert revisions.status_code == status.HTTP_200_OK
        original_revision_id = revisions.json()[-1]["id"]

        revision_restore_url = (
            f"{ADMIN_CMS_BASE}/{page_id}/revisions/"
            f"{original_revision_id}/restore"
        )
        revision_restore = client.post(
            revision_restore_url,
            headers={**admin_token_headers, "If-Match": updated_etag},
        )
        assert revision_restore.status_code == status.HTTP_200_OK
        restored_revision_etag = _assert_protected_strong_etag(
            revision_restore
        )

        deleted = client.delete(
            f"{ADMIN_CMS_BASE}/{page_id}",
            headers={
                **admin_token_headers,
                "If-Match": restored_revision_etag,
            },
        )
        assert deleted.status_code == status.HTTP_200_OK
        _assert_protected_strong_etag(deleted)

        deleted_detail = client.get(
            f"{ADMIN_CMS_BASE}/{page_id}?include_deleted=true",
            headers=admin_token_headers,
        )
        assert deleted_detail.status_code == status.HTTP_200_OK
        deleted_etag = _assert_protected_strong_etag(deleted_detail)

        restored = client.post(
            f"{ADMIN_CMS_BASE}/{page_id}/restore",
            json={},
            headers={**admin_token_headers, "If-Match": deleted_etag},
        )
        assert restored.status_code == status.HTTP_200_OK, restored.text
        _assert_protected_strong_etag(restored)

        listed = client.get(ADMIN_CMS_BASE, headers=admin_token_headers)
        assert listed.status_code == status.HTTP_200_OK
        list_etag = _assert_protected_strong_etag(listed)
        ordered_ids = [page["id"] for page in listed.json()["pages"]]

        reordered = client.post(
            f"{ADMIN_CMS_BASE}/reorder",
            json={"ordered_ids": ordered_ids},
            headers={**admin_token_headers, "If-Match": list_etag},
        )
        assert reordered.status_code == status.HTTP_200_OK, reordered.text
        _assert_protected_strong_etag(reordered)

    def test_weak_if_match_remains_rejected(self, client, admin_token_headers):
        created = client.post(
            ADMIN_CMS_BASE,
            json={
                "title": "Weak validator guard",
                "slug": "weak-validator-guard",
                "body_html": "<p>Original body</p>",
                "show_in_nav": False,
            },
            headers=admin_token_headers,
        )
        assert created.status_code == status.HTTP_201_CREATED
        page_id = created.json()["id"]
        strong_etag = _assert_protected_strong_etag(created)

        rejected = client.put(
            f"{ADMIN_CMS_BASE}/{page_id}",
            json={"title": "Must not be saved"},
            headers={**admin_token_headers, "If-Match": f"W/{strong_etag}"},
        )
        assert rejected.status_code == status.HTTP_412_PRECONDITION_FAILED

        detail = client.get(
            f"{ADMIN_CMS_BASE}/{page_id}",
            headers=admin_token_headers,
        )
        assert detail.status_code == status.HTTP_200_OK
        assert detail.json()["title"] == "Weak validator guard"

    def test_reserved_slugs_keep_public_cache_policy_with_no_transform(
        self, client, admin_token_headers
    ):
        first = client.get(
            f"{ADMIN_CMS_BASE}/reserved-slugs",
            headers=admin_token_headers,
        )
        assert first.status_code == status.HTTP_200_OK
        etag = first.headers["ETag"]

        directives = {
            directive.strip().lower()
            for directive in first.headers["Cache-Control"].split(",")
        }
        assert {
            "public",
            "max-age=300",
            "must-revalidate",
            "no-transform",
        } <= directives

        cached = client.get(
            f"{ADMIN_CMS_BASE}/reserved-slugs",
            headers={**admin_token_headers, "If-None-Match": etag},
        )
        assert cached.status_code == status.HTTP_304_NOT_MODIFIED
        assert cached.content == b""
        assert cached.headers["ETag"] == etag
        cached_directives = {
            directive.strip().lower()
            for directive in cached.headers["Cache-Control"].split(",")
        }
        assert {
            "public",
            "max-age=300",
            "must-revalidate",
            "no-transform",
        } <= cached_directives
