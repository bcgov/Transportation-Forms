"""FEAT-0025: Business area admin management.

Revision ID: 017_feat_0025_business_areas_admin
Revises: 016_feat_0012_prefix_updated_by
Create Date: 2026-06-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "017_feat_0025_business_areas_admin"
down_revision = "016_feat_0012_prefix_updated_by"
branch_labels = None
depends_on = None

_DROP_SQL = "DROP VIEW IF EXISTS public_forms_v;"

# We recreate the exact same view as in 014 but remove `AND ba.is_active = True`.
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

# V2 contains `AND ba.is_active = True`, used for downgrades.
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


def upgrade() -> None:
    # 1. Drop public_forms_v view before dropping columns
    op.execute(_DROP_SQL)

    # 2. Modify business_areas
    with op.batch_alter_table("business_areas", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mailbox", sa.String(length=75), nullable=True))
        batch_op.drop_column("description")
        batch_op.drop_column("sort_order")
        # Ensure we drop index before dropping column, we can do it via dropping the column 
        # (SQLAlchemy/Alembic drops indices on columns when columns drop natively usually, but wait, is_active has an index)
        batch_op.drop_index("ix_business_areas_is_active")
        batch_op.drop_column("is_active")

    # 3. Recreate public_forms_v
    op.execute(_VIEW_V3_SQL)

    # 4. Modify business_area_contacts
    with op.batch_alter_table("business_area_contacts", schema=None) as batch_op:
        batch_op.alter_column("contact_user_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
        batch_op.add_column(sa.Column("name", sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column("email", sa.String(length=75), nullable=True))
        batch_op.create_unique_constraint("uq_ba_contact_user", ["business_area_id", "contact_user_id"])
        batch_op.create_unique_constraint("uq_ba_contact_email", ["business_area_id", "email"])
        batch_op.create_check_constraint(
            "check_hybrid_contact_exclusive",
            "(contact_user_id IS NOT NULL AND name IS NULL AND email IS NULL) OR (contact_user_id IS NULL AND name IS NOT NULL AND email IS NOT NULL)"
        )


def downgrade() -> None:
    # 1. Drop view
    op.execute(_DROP_SQL)

    # 2. Revert business_area_contacts
    with op.batch_alter_table("business_area_contacts", schema=None) as batch_op:
        batch_op.drop_constraint("check_hybrid_contact_exclusive", type_="check")
        batch_op.drop_constraint("uq_ba_contact_email", type_="unique")
        batch_op.drop_constraint("uq_ba_contact_user", type_="unique")
        batch_op.drop_column("email")
        batch_op.drop_column("name")
        # Removing rows that don't satisfy the NOT NULL constraint to avoid crash before altering column back.
        # But this is a downgrade script, data loss is acceptable for non-matching rows.
        # So we delete rows where contact_user_id is None.
    op.execute("DELETE FROM business_area_contacts WHERE contact_user_id IS NULL")
    
    with op.batch_alter_table("business_area_contacts", schema=None) as batch_op:
        batch_op.alter_column("contact_user_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)

    # 3. Revert business_areas
    with op.batch_alter_table("business_areas", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_active", sa.Boolean(), server_default='true', nullable=False))
        batch_op.create_index("ix_business_areas_is_active", ["is_active"], unique=False)
        batch_op.add_column(sa.Column("sort_order", sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch_op.drop_column("mailbox")

    # 4. Recreate V2 view
    op.execute(_VIEW_V2_SQL)
