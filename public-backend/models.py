"""SQLAlchemy model mapping to the public_forms_v database view."""

from sqlalchemy import BigInteger, Column, DateTime, String, Text
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
    effective_date = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)

    # ------------------------------------------------------------------
    # File metadata — server-side only (X-Accel-Redirect target).
    # ``s3_key`` MUST NOT be serialised into any response body.
    # ------------------------------------------------------------------
    s3_key = Column(String(500), nullable=True)
    file_name = Column(String(255), nullable=True)
    file_size = Column(BigInteger, nullable=True)
