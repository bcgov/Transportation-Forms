"""FEAT-0004: Create public_forms_v database view

Revision ID: 013_feat_0004_public_forms_view
Revises: 012_feat_0002_add_file_type_column
Create Date: 2026-04-29 00:00:00.000000

Creates a read-only database view that exposes only the fields needed by the
public-backend API, filtering to only publicly visible forms (published,
is_public=True, not soft-deleted).  The view joins forms → form_number_reservations
and forms → business_areas to project form_number and business_area name.

Forms linked to inactive or deleted business areas are still returned but
with business_area = NULL.
"""

from alembic import op


revision = "013_feat_0004_public_forms_view"
down_revision = "012_feat_0002_add_file_type_column"
branch_labels = None
depends_on = None

_VIEW_SQL = """\
CREATE VIEW public_forms_v AS
SELECT
    fnr.full_form_number  AS form_number,
    f.title,
    f.description,
    ba.name               AS business_area,
    f.keywords,
    f.file_type,
    f.effective_date
FROM forms f
LEFT JOIN form_number_reservations fnr
    ON f.form_number_reservation_id = fnr.id
LEFT JOIN business_areas ba
    ON f.business_area_id = ba.id
   AND ba.deleted_at IS NULL
   AND ba.is_active = True
WHERE f.status     = 'published'
  AND f.is_public  = True
  AND f.deleted_at IS NULL;
"""


def upgrade() -> None:
    op.execute(_VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS public_forms_v;")
