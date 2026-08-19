"""FEAT-0029: Expose link-source destination URL in public_forms_v.

Revision ID: 021_feat_0029_public_forms_view_link_url
Revises: 020_feat_0026_drop_cms_media
Create Date: 2026-08-18 00:00:00.000000

Re-creates the ``public_forms_v`` view to additionally project
``form_source`` and ``form_source_url`` from the underlying ``forms`` row so
the public API can advertise hyperlink (link-source) forms and their
destination URL (FEAT-0029 US-001).

The change is purely additive: every column present in the FEAT-0025 (V3)
view is retained; only ``form_source`` and ``form_source_url`` are added.
No filtering semantics change — the view still exposes only published,
public, non-deleted forms.
"""

from alembic import op


revision = "021_feat_0029_public_forms_view_link_url"
down_revision = "020_feat_0026_drop_cms_media"
branch_labels = None
depends_on = None

_DROP_SQL = "DROP VIEW IF EXISTS public_forms_v;"

# V4 — adds form_source + form_source_url to the FEAT-0025 (V3) projection.
_VIEW_V4_SQL = """\
CREATE VIEW public_forms_v AS
SELECT
    f.id                  AS form_id,
    fnr.full_form_number  AS form_number,
    f.title,
    f.description,
    ba.id                 AS business_area_id,
    ba.name               AS business_area,
    f.keywords,
    f.file_type,
    f.form_source,
    f.form_source_url,
    f.effective_date,
    f.updated_at,
    fv.s3_key             AS s3_key,
    fv.file_name          AS file_name,
    fv.file_size          AS file_size
FROM forms f
LEFT JOIN form_number_reservations fnr
    ON f.form_number_reservation_id = fnr.id
LEFT JOIN business_areas ba
    ON f.business_area_id = ba.id
   AND ba.deleted_at IS NULL
LEFT JOIN form_versions fv
    ON fv.form_id = f.id
   AND fv.is_current = True
   AND fv.deleted_at IS NULL
WHERE f.status     = 'published'
  AND f.is_public  = True
  AND f.deleted_at IS NULL;
"""

# V3 — the FEAT-0025 view (no form_source columns), used for downgrade.
_VIEW_V3_SQL = """\
CREATE VIEW public_forms_v AS
SELECT
    f.id                  AS form_id,
    fnr.full_form_number  AS form_number,
    f.title,
    f.description,
    ba.id                 AS business_area_id,
    ba.name               AS business_area,
    f.keywords,
    f.file_type,
    f.effective_date,
    f.updated_at,
    fv.s3_key             AS s3_key,
    fv.file_name          AS file_name,
    fv.file_size          AS file_size
FROM forms f
LEFT JOIN form_number_reservations fnr
    ON f.form_number_reservation_id = fnr.id
LEFT JOIN business_areas ba
    ON f.business_area_id = ba.id
   AND ba.deleted_at IS NULL
LEFT JOIN form_versions fv
    ON fv.form_id = f.id
   AND fv.is_current = True
   AND fv.deleted_at IS NULL
WHERE f.status     = 'published'
  AND f.is_public  = True
  AND f.deleted_at IS NULL;
"""


def upgrade() -> None:
    op.execute(_DROP_SQL)
    op.execute(_VIEW_V4_SQL)


def downgrade() -> None:
    op.execute(_DROP_SQL)
    op.execute(_VIEW_V3_SQL)
