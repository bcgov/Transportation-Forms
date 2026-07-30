"""FEAT-0026: Mini-CMS media table + public projection view.

Revision ID: 019_feat_0026_cms_media_and_view
Revises: 018_feat_0026_cms
Create Date: 2026-07-03 00:00:00.000000

Adds the ``cms_media`` table for image assets uploaded via SunEditor
(FEAT-0026 US-009) and creates ``public_cms_pages_v`` — the read-only
projection view used by the public-backend to expose non-deleted pages.

Both objects are dropped cleanly in the downgrade.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "019_feat_0026_cms_media_and_view"
down_revision = "018_feat_0026_cms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) cms_media — soft-deleted image gallery for CMS body embedding.
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 2) public_cms_pages_v — the sole surface the public-backend reads.
    #    Excludes soft-deleted rows and internal columns.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE VIEW public_cms_pages_v AS
        SELECT id,
               slug,
               title,
               meta_description,
               body_html,
               show_in_nav,
               nav_order,
               updated_at,
               created_at
          FROM cms_pages
         WHERE deleted_at IS NULL
        """
    )

    # ------------------------------------------------------------------
    # 3) public_cms_media_v — media projection excluding soft-deleted.
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 4) public_cms_redirects_v — redirects join surviving pages so the
    #    public resolver returns the current active slug in one query.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE VIEW public_cms_redirects_v AS
        SELECT r.id           AS redirect_id,
               r.from_slug    AS from_slug,
               p.id           AS to_page_id,
               p.slug         AS to_slug,
               r.created_at   AS created_at
          FROM cms_page_redirects r
          JOIN cms_pages p ON p.id = r.to_page_id
         WHERE p.deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS public_cms_redirects_v")
    op.execute("DROP VIEW IF EXISTS public_cms_media_v")
    op.execute("DROP VIEW IF EXISTS public_cms_pages_v")

    op.drop_index("ix_cms_media_created_by", table_name="cms_media")
    op.drop_index("ix_cms_media_deleted_at", table_name="cms_media")
    op.drop_index("ix_cms_media_created_at", table_name="cms_media")
    op.drop_table("cms_media")
