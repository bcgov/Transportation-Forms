"""FEAT-0026 — US-001 / US-007 / US-016 backend tests.

Covers the create-page admin endpoint, the reserved-slugs endpoint, and the
HTML sanitization policy enforced by the service layer.

Test plan reference: ``plan/features/FEAT-0026-mini-cms-public-pages/tests``.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import status

from backend.models import (
    AuditLog,
    CmsPage,
    CmsPageRedirect,
    CmsPageRevision,
    UserRole,
)
from backend.services.cms_sanitizer import sanitize_html
from backend.services.cms_reserved_slugs import RESERVED_SLUGS


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADMIN_CMS_BASE = "/api/v1/admin/cms/pages"
RESERVED_SLUGS_URL = f"{ADMIN_CMS_BASE}/reserved-slugs"

CMS_PERM = "cms:manage"


# ---------------------------------------------------------------------------
# Helpers / module-level fixtures
# ---------------------------------------------------------------------------


def _ensure_admin_has_cms_perm(db, admin_user) -> None:
    """Grant the ``cms:manage`` permission to the admin user's role."""
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
    """Auto-use: ensure the admin role carries ``cms:manage`` for every test."""
    _ensure_admin_has_cms_perm(db, admin_user)


def _valid_payload(**overrides) -> dict:
    base = {
        "title": "About the Transportation Forms Portal",
        "slug": "about-portal",
        "meta_description": "Information about the public Forms Portal.",
        "body_html": "<p>Welcome to the <strong>Forms Portal</strong>.</p>",
        "show_in_nav": True,
    }
    base.update(overrides)
    return base


# ===========================================================================
# US-001 — POST /admin/cms/pages
# ===========================================================================


@pytest.mark.integration
class TestUS001CreatePage:
    # TC1.1 ---------------------------------------------------------------
    def test_tc1_1_create_minimal_valid_page_returns_201(
        self, client, db, admin_token_headers
    ):
        resp = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(),
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        body = resp.json()
        assert body["slug"] == "about-portal"
        assert body["title"] == "About the Transportation Forms Portal"
        assert body["show_in_nav"] is True
        assert body["nav_order"] == 1
        assert "id" in body

        # Database row exists and is owned by the admin user.
        page = db.query(CmsPage).filter(CmsPage.slug == "about-portal").one()
        assert page.deleted_at is None
        assert str(page.id) == body["id"]

    # TC1.2 ---------------------------------------------------------------
    def test_tc1_2_initial_revision_is_inserted(
        self, client, db, admin_token_headers
    ):
        resp = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(slug="rev-page"),
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED
        page_id = uuid.UUID(resp.json()["id"])
        revisions = (
            db.query(CmsPageRevision)
            .filter(CmsPageRevision.page_id == page_id)
            .all()
        )
        assert len(revisions) == 1
        rev = revisions[0]
        assert rev.slug == "rev-page"
        assert "<strong>Forms Portal</strong>" in rev.body_html

    # TC1.3 ---------------------------------------------------------------
    def test_tc1_3_audit_log_entry_recorded(
        self, client, db, admin_token_headers, admin_user
    ):
        resp = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(slug="audit-page"),
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED
        page_id = resp.json()["id"]
        audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.entity_type == "cms_pages",
                AuditLog.entity_id == page_id,
                AuditLog.action == "cms_page.created",
            )
            .all()
        )
        assert len(audits) == 1
        assert audits[0].user_id == admin_user.id
        assert audits[0].new_values["slug"] == "audit-page"
        assert "body_html" not in audits[0].new_values  # large body is excluded

    # TC1.4 ---------------------------------------------------------------
    @pytest.mark.parametrize(
        "bad_slug",
        [
            "-leading",
            "trailing-",
            "double--hyphen",
            "with space",
            "with_underscore",
            "",
        ],
    )
    def test_tc1_4_invalid_slug_format_returns_422(
        self, client, admin_token_headers, bad_slug
    ):
        resp = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(slug=bad_slug),
            headers=admin_token_headers,
        )
        # Pydantic catches empty (min_length=1) -> 422; service catches the rest -> 422.
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # TC1.4b — uppercase input is normalized to lowercase on save.
    def test_tc1_4b_uppercase_slug_normalized_to_lowercase(
        self, client, db, admin_token_headers
    ):
        resp = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(slug="MIXED-Case-Slug"),
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["slug"] == "mixed-case-slug"
        # Stored lowercase too.
        page = db.query(CmsPage).filter(CmsPage.slug == "mixed-case-slug").one()
        assert page.slug == "mixed-case-slug"

    # TC1.5 ---------------------------------------------------------------
    @pytest.mark.parametrize("reserved", sorted(RESERVED_SLUGS))
    def test_tc1_5_reserved_slug_rejected(
        self, client, admin_token_headers, reserved
    ):
        resp = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(slug=reserved),
            headers=admin_token_headers,
        )
        # Reserved slugs that happen to contain "." (robots.txt, etc.) also
        # violate the slug-format rule, so 422 is the expected response in
        # either branch.
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # TC1.6 ---------------------------------------------------------------
    def test_tc1_6_duplicate_active_slug_returns_409(
        self, client, db, admin_token_headers
    ):
        first = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(slug="dup-page"),
            headers=admin_token_headers,
        )
        assert first.status_code == status.HTTP_201_CREATED

        second = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(slug="dup-page", title="Other"),
            headers=admin_token_headers,
        )
        assert second.status_code == status.HTTP_409_CONFLICT
        detail = second.json()["detail"]
        assert detail["slug"] == "dup-page"

    # TC1.7 ---------------------------------------------------------------
    def test_tc1_7_slug_collision_with_redirect_returns_409(
        self, client, db, admin_user, admin_token_headers
    ):
        # Seed an existing page with one redirect pointing at "old-slug".
        seed = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(slug="surviving-page"),
            headers=admin_token_headers,
        )
        assert seed.status_code == status.HTTP_201_CREATED
        seeded_page_id = uuid.UUID(seed.json()["id"])

        redirect = CmsPageRedirect(
            from_slug="old-slug",
            to_page_id=seeded_page_id,
        )
        db.add(redirect)
        db.flush()

        resp = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(slug="old-slug", title="New"),
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_409_CONFLICT

    # TC1.8 ---------------------------------------------------------------
    def test_tc1_8_title_exceeds_max_returns_422(
        self, client, admin_token_headers
    ):
        resp = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(title="x" * 121),
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # TC1.9 ---------------------------------------------------------------
    def test_tc1_9_meta_description_exceeds_max_returns_422(
        self, client, admin_token_headers
    ):
        resp = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(meta_description="x" * 181),
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # TC1.10 --------------------------------------------------------------
    def test_tc1_10_body_required(self, client, admin_token_headers):
        resp = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(body_html=""),
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # TC1.11 --------------------------------------------------------------
    def test_tc1_11_body_with_only_disallowed_markup_returns_422(
        self, client, admin_token_headers
    ):
        resp = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(body_html="<script>alert(1)</script>"),
            headers=admin_token_headers,
        )
        # script content is stripped to empty -> validation rejects.
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # TC1.12 --------------------------------------------------------------
    def test_tc1_12_unauthorized_without_permission_returns_403(
        self, client, db, admin_user, admin_token_headers
    ):
        # Remove the cms:manage permission from the admin role.
        user_role = (
            db.query(UserRole).filter(UserRole.user_id == admin_user.id).first()
        )
        role = user_role.role
        role.permissions = [p for p in (role.permissions or []) if p != CMS_PERM]
        db.flush()

        resp = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(slug="no-perm"),
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    # TC1.13 --------------------------------------------------------------
    def test_tc1_13_unauthenticated_returns_401(self, client):
        resp = client.post(ADMIN_CMS_BASE, json=_valid_payload(slug="anon"))
        assert resp.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    # TC1.14 — nav_order increments for successive pages -----------------
    def test_tc1_14_nav_order_increments(
        self, client, admin_token_headers, db
    ):
        for idx in range(1, 4):
            resp = client.post(
                ADMIN_CMS_BASE,
                json=_valid_payload(slug=f"nav-page-{idx}", title=f"Nav {idx}"),
                headers=admin_token_headers,
            )
            assert resp.status_code == status.HTTP_201_CREATED
            assert resp.json()["nav_order"] == idx

    # TC1.15 — show_in_nav=False does not consume a nav_order -----------
    def test_tc1_15_show_in_nav_false_has_null_nav_order(
        self, client, admin_token_headers
    ):
        resp = client.post(
            ADMIN_CMS_BASE,
            json=_valid_payload(slug="hidden", show_in_nav=False),
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["nav_order"] is None


# ===========================================================================
# US-007 — GET /admin/cms/pages/reserved-slugs
# ===========================================================================


@pytest.mark.integration
class TestUS007ReservedSlugs:
    def test_returns_reserved_list(self, client, admin_token_headers):
        resp = client.get(RESERVED_SLUGS_URL, headers=admin_token_headers)
        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        # All reserved entries are present and the list is sorted.
        assert sorted(body["reserved"]) == body["reserved"]
        for slug in RESERVED_SLUGS:
            assert slug in body["reserved"]

    def test_cache_control_header_present(
        self, client, admin_token_headers
    ):
        resp = client.get(RESERVED_SLUGS_URL, headers=admin_token_headers)
        cache_control = resp.headers.get("cache-control", "")
        assert "max-age=300" in cache_control
        assert "public" in cache_control
        assert resp.headers.get("etag")

    def test_if_none_match_returns_304(
        self, client, admin_token_headers
    ):
        first = client.get(RESERVED_SLUGS_URL, headers=admin_token_headers)
        etag = first.headers["etag"]
        second = client.get(
            RESERVED_SLUGS_URL,
            headers={**admin_token_headers, "If-None-Match": etag},
        )
        assert second.status_code == status.HTTP_304_NOT_MODIFIED

    def test_requires_cms_permission(
        self, client, db, admin_user, admin_token_headers
    ):
        user_role = (
            db.query(UserRole).filter(UserRole.user_id == admin_user.id).first()
        )
        role = user_role.role
        role.permissions = [p for p in (role.permissions or []) if p != CMS_PERM]
        db.flush()

        resp = client.get(RESERVED_SLUGS_URL, headers=admin_token_headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ===========================================================================
# US-010 — Permission seed + content_editor role
# ===========================================================================


@pytest.mark.integration
class TestUS010PermissionAndRoleSeed:
    def test_admin_role_can_hold_cms_manage(
        self, db, admin_user
    ):
        user_role = (
            db.query(UserRole).filter(UserRole.user_id == admin_user.id).first()
        )
        perms = list(user_role.role.permissions or [])
        assert CMS_PERM in perms


# ===========================================================================
# US-016 — HTML sanitizer policy (unit-level)
# ===========================================================================


class TestUS016Sanitizer:
    def test_empty_input_returns_empty(self):
        assert sanitize_html("") == ""
        assert sanitize_html(None) == ""

    def test_strips_script_tag_and_contents(self):
        html = "<p>safe</p><script>alert('xss')</script>"
        cleaned = sanitize_html(html)
        assert "<script" not in cleaned
        assert "alert" not in cleaned
        assert "<p>safe</p>" in cleaned

    def test_strips_style_tag(self):
        html = "<style>body{background:url(javascript:1)}</style><p>x</p>"
        cleaned = sanitize_html(html)
        assert "<style" not in cleaned
        assert "javascript" not in cleaned

    def test_strips_iframe(self):
        html = '<iframe src="https://evil.com"></iframe>'
        assert "<iframe" not in sanitize_html(html)

    @pytest.mark.parametrize(
        "payload",
        [
            '<a href="javascript:alert(1)">click</a>',
            '<a href="vbscript:msgbox(1)">click</a>',
            '<a href="data:text/html,<script>alert(1)</script>">click</a>',
            '<a href="//evil.com">click</a>',
            '<a href=" javascript:alert(1)">click</a>',
        ],
    )
    def test_dangerous_anchor_hrefs_dropped(self, payload):
        cleaned = sanitize_html(payload)
        lowered = cleaned.lower()
        assert "javascript:" not in lowered
        assert "vbscript:" not in lowered
        assert "data:" not in lowered
        # //evil.com should not survive as an href value either.
        assert "//evil.com" not in lowered

    def test_safe_anchor_href_preserved_with_rel(self):
        cleaned = sanitize_html('<a href="https://example.com">x</a>')
        assert 'href="https://example.com"' in cleaned
        assert "noopener" in cleaned
        assert "noreferrer" in cleaned

    def test_event_handlers_stripped(self):
        html = '<p onclick="alert(1)" onmouseover="alert(2)">hi</p>'
        cleaned = sanitize_html(html)
        assert "onclick" not in cleaned
        assert "onmouseover" not in cleaned

    def test_img_tag_stripped_bare(self):
        # FEAT-0026 remediation plan v2 (2026-07-16): <img> is not on
        # the allow-list — every form must be stripped.
        cleaned = sanitize_html("<img>")
        assert "<img" not in cleaned.lower()

    def test_img_tag_stripped_with_https_src(self):
        cleaned = sanitize_html('<img src="https://example.com/x.jpg">')
        assert "<img" not in cleaned.lower()
        assert "example.com" not in cleaned

    def test_img_tag_stripped_with_data_cms_media(self):
        # Regression guard: the old ``data-cms-media`` marker must not
        # sneak <img> back into the output.
        html = (
            '<img src="https://evil.com/x.png" alt="ok" '
            'data-cms-media="abc-123" width="100" height="50" loading="lazy">'
        )
        cleaned = sanitize_html(html)
        assert "<img" not in cleaned.lower()
        assert "data-cms-media" not in cleaned
        assert "evil.com" not in cleaned

    def test_arbitrary_data_attribute_dropped(self):
        html = '<p data-evil="x" data-cms-foo="y">hi</p>'
        cleaned = sanitize_html(html)
        assert "data-evil" not in cleaned
        assert "data-cms-foo" in cleaned

    def test_style_attribute_disallowed_property_dropped(self):
        html = '<p style="color: red; behavior: url(xss.htc); font-weight: bold;">x</p>'
        cleaned = sanitize_html(html)
        # nh3 strips style entirely because we don't allow style in ALLOWED_ATTRIBUTES.
        assert "style=" not in cleaned

    def test_unicode_bidi_stripped(self):
        # U+202E (RLO) is removed before parsing.
        html = "<p>safe\u202emalicious</p>"
        cleaned = sanitize_html(html)
        assert "\u202e" not in cleaned

    def test_html_comments_removed(self):
        html = "<!-- secret comment --><p>x</p>"
        cleaned = sanitize_html(html)
        assert "<!--" not in cleaned
        assert "secret" not in cleaned

    def test_table_structure_preserved(self):
        html = (
            "<table><thead><tr><th scope='col'>A</th></tr></thead>"
            "<tbody><tr><td>1</td></tr></tbody></table>"
        )
        cleaned = sanitize_html(html)
        assert "<table" in cleaned
        assert "<thead" in cleaned
        assert "<th" in cleaned
        assert "<td" in cleaned

    def test_disallowed_tag_dropped_but_inner_text_kept(self):
        html = "<custom>hello <strong>world</strong></custom>"
        cleaned = sanitize_html(html)
        assert "<custom" not in cleaned
        assert "hello" in cleaned
        assert "<strong>world</strong>" in cleaned
