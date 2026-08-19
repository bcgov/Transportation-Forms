"""SQLAlchemy model mapping to the public_*_v database views."""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from database import Base


class PublicForm(Base):
    """Read-only model backed by the ``public_forms_v`` database view.

    The view (FEAT-0004 + FEAT-0005) projects publicly visible
    (``status='published'`` AND ``is_public=true`` AND not soft-deleted)
    forms with file metadata pulled from the current
    ``form_versions`` row.

    Column visibility:

    * ``form_id``, ``business_area_id``, ``s3_key`` are *internal* — they
      MUST NOT be returned in any public API response.  They are present
      in the model only because routes use them server-side
      (FK-style joins, ``X-Accel-Redirect`` composition).
    * Everything else may be projected to clients via Pydantic schemas
      that explicitly opt-in.
    """

    __tablename__ = "public_forms_v"
    __table_args__ = {"info": {"is_view": True}}

    # Form id is unique per row in the view → suitable as a stable PK
    # for SQLAlchemy ORM identity.  Never returned in API responses.
    form_id = Column(UUID(as_uuid=True), primary_key=True)

    form_number = Column(String(70), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    business_area_id = Column(UUID(as_uuid=True), nullable=True)
    business_area = Column(String(255), nullable=True)

    keywords = Column(JSONB, nullable=True)
    file_type = Column(String(20), nullable=True)

    # FEAT-0029 — hyperlink (link-source) forms.  ``form_source`` is 'URL'
    # or 'Download' (or NULL for legacy rows); ``form_source_url`` holds the
    # destination for link-source forms.  The destination is emitted to
    # clients only after a scheme guard in the route layer.
    form_source = Column(String(50), nullable=True)
    form_source_url = Column(String(500), nullable=True)

    effective_date = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)

    # ------------------------------------------------------------------
    # File metadata — server-side only (X-Accel-Redirect target).
    # ``s3_key`` MUST NOT be serialised into any response body.
    # ------------------------------------------------------------------
    s3_key = Column(String(500), nullable=True)
    file_name = Column(String(255), nullable=True)
    file_size = Column(BigInteger, nullable=True)


# ---------------------------------------------------------------------------
# FEAT-0026 — CMS view-backed models
# ---------------------------------------------------------------------------


class PublicCmsPage(Base):
    """Read-only model backed by the ``public_cms_pages_v`` view.

    Projects only non-deleted rows from ``cms_pages`` so that soft-deleted
    pages disappear from the public API automatically (US-011 AC7).
    """

    __tablename__ = "public_cms_pages_v"
    __table_args__ = {"info": {"is_view": True}}

    id = Column(UUID(as_uuid=True), primary_key=True)
    slug = Column(String(80), nullable=False)
    title = Column(String(120), nullable=False)
    meta_description = Column(String(180), nullable=True)
    body_html = Column(Text, nullable=False)
    show_in_nav = Column(Boolean, nullable=False, default=False)
    nav_order = Column(Integer, nullable=True)
    updated_at = Column(DateTime, nullable=True)


class PublicCmsRedirect(Base):
    """Read-only model backed by the ``public_cms_redirects_v`` view.

    The view joins to ``cms_pages`` and filters out redirects whose target
    is soft-deleted so the resolver reliably returns 404 for stale rows
    (US-013 AC3).
    """

    __tablename__ = "public_cms_redirects_v"
    __table_args__ = {"info": {"is_view": True}}

    # The view exposes redirect_id as PK because ``id`` is used elsewhere.
    redirect_id = Column(UUID(as_uuid=True), primary_key=True)
    from_slug = Column(String(80), nullable=False)
    to_page_id = Column(UUID(as_uuid=True), nullable=False)
    to_slug = Column(String(80), nullable=False)
    created_at = Column(DateTime, nullable=True)
