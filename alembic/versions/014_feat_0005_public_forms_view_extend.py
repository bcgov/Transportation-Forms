"""FEAT-0005: Extend public_forms_v with file metadata + updated_at.

Revision ID: 014_feat_0005_public_forms_view_extend
Revises: 013_feat_0004_public_forms_view
Create Date: 2026-04-30 00:00:00.000000

Re-creates the ``public_forms_v`` view to add fields required by the public
forms portal (FEAT-0005):

* ``form_id``            — UUID of the underlying form (used as the ORM PK;
                           never returned to clients in API responses).
* ``business_area_id``   — UUID of the business area (used by the
                           ``GET /api/public/v1/business-areas`` endpoint).
* ``updated_at``         — supports ``s=updated_at`` sorting and the
                           "recently updated" home-page feed.
* ``s3_key``             — server-side only (used solely to compose the
                           ``X-Accel-Redirect`` URL); MUST NOT be returned
                           to clients.
* ``file_name`` / ``file_size`` — surfaced in the detail endpoint as
                           ``filename`` / ``size`` for the active download
                           UI.

File metadata is sourced from the **current** ``form_versions`` row
(``is_current = true AND deleted_at IS NULL``) joined to each form.  When
a form has no current version (no attached file yet) those columns are
``NULL`` and the ``/file`` endpoint will return 404.
"""

from alembic import op


revision = "014_feat_0005_public_forms_view_extend"
down_revision = "013_feat_0004_public_forms_view"
branch_labels = None
depends_on = None


_DROP_SQL = "DROP VIEW IF EXISTS public_forms_v;"


_VIEW_V2_SQL = """\
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
   AND ba.is_active = True
LEFT JOIN form_versions fv
    ON fv.form_id = f.id
   AND fv.is_current = True
   AND fv.deleted_at IS NULL
WHERE f.status     = 'published'
  AND f.is_public  = True
  AND f.deleted_at IS NULL;
"""


_VIEW_V1_SQL = """\
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
    op.execute(_DROP_SQL)
    op.execute(_VIEW_V2_SQL)


def downgrade() -> None:
    op.execute(_DROP_SQL)
    op.execute(_VIEW_V1_SQL)
