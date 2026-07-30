"""FEAT-0026 remediation plan v2: drop cms_media, drop public_cms_media_v, wipe CMS data.

Revision ID: 020_feat_0026_drop_cms_media
Revises: 019_feat_0026_cms_media_and_view
Create Date: 2026-07-16 00:00:00.000000

Per FEAT-0026 remediation plan v2 (Product Owner decision 2026-07-16):

* SunEditor and CMS Media are withdrawn from FEAT-0026 scope.
* All existing CMS data (pages, revisions, redirects) is wiped so we
  restart from an empty catalogue.
* The ``cms_media`` table and ``public_cms_media_v`` projection view
  are dropped.

The downgrade recreates the table and view shape defined in migration
``019_feat_0026_cms_media_and_view`` for schema-symmetry. Downgrade does
NOT restore any wiped rows in ``cms_pages``, ``cms_page_revisions``, or
``cms_page_redirects`` — that trade-off was accepted by the PO on the
same date.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "020_feat_0026_drop_cms_media"
down_revision = "019_feat_0026_cms_media_and_view"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) Wipe CMS content (order matters — revisions and redirects
    #    reference pages).  CASCADE is defensive against future FKs.
    # ------------------------------------------------------------------
    op.execute("TRUNCATE cms_page_revisions RESTART IDENTITY CASCADE")
    op.execute("TRUNCATE cms_page_redirects RESTART IDENTITY CASCADE")
    op.execute("TRUNCATE cms_pages RESTART IDENTITY CASCADE")

    # ------------------------------------------------------------------
    # 2) Drop the media projection view before its backing table.
    # ------------------------------------------------------------------
    op.execute("DROP VIEW IF EXISTS public_cms_media_v CASCADE")

    # ------------------------------------------------------------------
    # 3) Drop the cms_media table and its indexes.
    # ------------------------------------------------------------------
    op.execute("DROP TABLE IF EXISTS cms_media CASCADE")


def downgrade() -> None:
    # Recreate the cms_media table with the exact shape from migration
    # 019 so that a rollback leaves the schema symmetrical.  Rows are
    # NOT restored (PO decision 2026-07-16).
    op.create_table(
        "cms_media",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("s3_key", sa.String(length=500), nullable=False),
        sa.Column("mime", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("sanitized_filename", sa.String(length=255), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cms_media_created_at", "cms_media", ["created_at"])
    op.create_index("ix_cms_media_deleted_at", "cms_media", ["deleted_at"])
    op.create_index("ix_cms_media_created_by", "cms_media", ["created_by_id"])

    op.execute(
        """
        CREATE OR REPLACE VIEW public_cms_media_v AS
        SELECT id,
               s3_key,
               mime,
               byte_size,
               created_at
          FROM cms_media
         WHERE deleted_at IS NULL
        """
    )
