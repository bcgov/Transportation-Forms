"""FEAT-0012: Add updated_by_id column and prefix permissions to admin role.

Revision ID: 016_feat_0012_prefix_updated_by
Revises: 015_feat_0007_self_approve_permission
Create Date: 2026-05-14 00:00:00.000000

Adds a nullable ``updated_by_id`` UUID column (FK → users.id) to
``form_number_prefixes`` to support the Updated By metadata requirement.

Also appends the five new ``form_number_prefix:*`` permission strings to
the ``admin`` role.  Both operations are idempotent.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "016_feat_0012_prefix_updated_by"
down_revision = "015_feat_0007_self_approve_permission"
branch_labels = None
depends_on = None

_NEW_PERMS = [
    "form_number_prefix:create",
    "form_number_prefix:read",
    "form_number_prefix:update",
    "form_number_prefix:delete",
    "form_number_prefix:archive",
]


def upgrade() -> None:
    # 1. Add updated_by_id column
    op.add_column(
        "form_number_prefixes",
        sa.Column(
            "updated_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )

    # 2. Append prefix permissions to the admin role (idempotent)
    for perm in _NEW_PERMS:
        op.execute(
            f"""
            UPDATE roles
               SET permissions = permissions || '["{perm}"]'::jsonb
             WHERE name = 'admin'
               AND deleted_at IS NULL
               AND NOT (permissions @> '["{perm}"]'::jsonb)
            """
        )


def downgrade() -> None:
    # 1. Remove prefix permissions from admin role
    for perm in _NEW_PERMS:
        op.execute(
            f"""
            UPDATE roles
               SET permissions = (
                   SELECT jsonb_agg(elem)
                     FROM jsonb_array_elements(permissions) AS elem
                    WHERE elem #>> '{{}}' != '{perm}'
               )
             WHERE name = 'admin'
               AND deleted_at IS NULL
            """
        )

    # 2. Drop updated_by_id column
    op.drop_column("form_number_prefixes", "updated_by_id")
