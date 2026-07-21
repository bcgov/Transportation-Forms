"""FEAT-0026: Mini-CMS schema + permissions seed.

Revision ID: 018_feat_0026_cms
Revises: 017_feat_0025_business_areas_admin
Create Date: 2026-06-04 00:00:00.000000

Adds three tables for the public Forms Portal mini-CMS:

* ``cms_pages``           — soft-deleted authoring records.
* ``cms_page_revisions``  — append-only revision history per page.
* ``cms_page_redirects``  — retired-slug → surviving-page mappings.

Also seeds the new ``cms:manage`` permission onto the ``admin`` role and
inserts a dedicated ``content_editor`` system role.  Both operations are
idempotent so the migration may be re-applied safely.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "018_feat_0026_cms"
down_revision = "017_feat_0025_business_areas_admin"
branch_labels = None
depends_on = None


_CMS_PERM = "cms:manage"
_CONTENT_EDITOR_ROLE = "content_editor"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) cms_pages
    # ------------------------------------------------------------------
    op.create_table(
        "cms_pages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("meta_description", sa.String(length=180), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column(
            "show_in_nav",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("nav_order", sa.Integer(), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cms_pages_slug", "cms_pages", ["slug"])
    op.create_index("ix_cms_pages_show_in_nav", "cms_pages", ["show_in_nav"])
    op.create_index("ix_cms_pages_deleted_at", "cms_pages", ["deleted_at"])
    op.create_index("ix_cms_pages_created_at", "cms_pages", ["created_at"])
    op.create_index("ix_cms_pages_nav", "cms_pages", ["show_in_nav", "nav_order"])
    # Partial unique index: only active (non-deleted) pages must have unique slugs.
    op.execute(
        """
        CREATE UNIQUE INDEX ix_cms_pages_slug_active
        ON cms_pages (slug)
        WHERE deleted_at IS NULL
        """
    )

    # ------------------------------------------------------------------
    # 2) cms_page_revisions
    # ------------------------------------------------------------------
    op.create_table(
        "cms_page_revisions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("meta_description", sa.String(length=180), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("edited_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "edited_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["page_id"], ["cms_pages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["edited_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cms_page_revisions_page_id", "cms_page_revisions", ["page_id"]
    )
    op.create_index(
        "ix_cms_page_revisions_edited_at", "cms_page_revisions", ["edited_at"]
    )
    op.create_index(
        "ix_cms_page_revisions_page_edited_at",
        "cms_page_revisions",
        ["page_id", "edited_at"],
    )

    # ------------------------------------------------------------------
    # 3) cms_page_redirects
    # ------------------------------------------------------------------
    op.create_table(
        "cms_page_redirects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("from_slug", sa.String(length=80), nullable=False),
        sa.Column("to_page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["to_page_id"], ["cms_pages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("from_slug", name="uq_cms_page_redirects_from_slug"),
    )
    op.create_index(
        "ix_cms_page_redirects_from_slug", "cms_page_redirects", ["from_slug"]
    )
    op.create_index(
        "ix_cms_page_redirects_to_page_id", "cms_page_redirects", ["to_page_id"]
    )

    # ------------------------------------------------------------------
    # 4) Permission seed — append cms:manage to admin role (idempotent).
    # ------------------------------------------------------------------
    op.execute(
        f"""
        UPDATE roles
           SET permissions = permissions || '["{_CMS_PERM}"]'::jsonb
         WHERE name = 'admin'
           AND deleted_at IS NULL
           AND NOT (permissions @> '["{_CMS_PERM}"]'::jsonb)
        """
    )

    # ------------------------------------------------------------------
    # 5) Seed the content_editor system role (idempotent on name).
    # ------------------------------------------------------------------
    op.execute(
        f"""
        INSERT INTO roles (id, name, description, permissions, is_system, is_active, created_at, updated_at)
        SELECT gen_random_uuid(),
               '{_CONTENT_EDITOR_ROLE}',
               'Content Editor for the public Forms Portal mini-CMS',
               '["{_CMS_PERM}"]'::jsonb,
               TRUE,
               TRUE,
               NOW(),
               NOW()
         WHERE NOT EXISTS (
               SELECT 1 FROM roles WHERE name = '{_CONTENT_EDITOR_ROLE}'
         )
        """
    )


def downgrade() -> None:
    # 1) Remove content_editor role only if no user is assigned to it.
    op.execute(
        f"""
        DELETE FROM roles
         WHERE name = '{_CONTENT_EDITOR_ROLE}'
           AND NOT EXISTS (
               SELECT 1 FROM user_roles ur WHERE ur.role_id = roles.id
           )
        """
    )

    # 2) Remove cms:manage from admin role.
    op.execute(
        f"""
        UPDATE roles
           SET permissions = (
               SELECT COALESCE(jsonb_agg(elem), '[]'::jsonb)
                 FROM jsonb_array_elements(permissions) AS elem
                WHERE elem #>> '{{}}' != '{_CMS_PERM}'
           )
         WHERE name = 'admin'
           AND deleted_at IS NULL
        """
    )

    # 3) Drop tables in reverse FK order.
    op.drop_index(
        "ix_cms_page_redirects_to_page_id", table_name="cms_page_redirects"
    )
    op.drop_index(
        "ix_cms_page_redirects_from_slug", table_name="cms_page_redirects"
    )
    op.drop_table("cms_page_redirects")

    op.drop_index(
        "ix_cms_page_revisions_page_edited_at", table_name="cms_page_revisions"
    )
    op.drop_index(
        "ix_cms_page_revisions_edited_at", table_name="cms_page_revisions"
    )
    op.drop_index(
        "ix_cms_page_revisions_page_id", table_name="cms_page_revisions"
    )
    op.drop_table("cms_page_revisions")

    op.execute("DROP INDEX IF EXISTS ix_cms_pages_slug_active")
    op.drop_index("ix_cms_pages_nav", table_name="cms_pages")
    op.drop_index("ix_cms_pages_created_at", table_name="cms_pages")
    op.drop_index("ix_cms_pages_deleted_at", table_name="cms_pages")
    op.drop_index("ix_cms_pages_show_in_nav", table_name="cms_pages")
    op.drop_index("ix_cms_pages_slug", table_name="cms_pages")
    op.drop_table("cms_pages")
