"""FEAT-0007: Add form:approve-self permission to the admin role.

Revision ID: 015_feat_0007_self_approve_permission
Revises: 014_feat_0005_public_forms_view_extend
Create Date: 2026-05-04 00:00:00.000000

Appends the new ``form:approve-self`` permission string to the ``permissions``
JSON array of the ``admin`` role.  The migration is idempotent: if the
permission is already present (e.g. after a re-run) the array is left
unchanged.

Down-migration removes the element so deployments can be rolled back cleanly.
"""

from alembic import op


revision = "015_feat_0007_self_approve_permission"
down_revision = "014_feat_0005_public_forms_view_extend"
branch_labels = None
depends_on = None

_PERM = "form:approve-self"


def upgrade() -> None:
    # Append the permission only when it is not already present.
    op.execute(
        f"""
        UPDATE roles
           SET permissions = permissions || '["{ _PERM }"]'::jsonb
         WHERE name = 'admin'
           AND deleted_at IS NULL
           AND NOT (permissions @> '["{ _PERM }"]'::jsonb)
        """
    )


def downgrade() -> None:
    # Remove the element from the JSON array.
    op.execute(
        f"""
        UPDATE roles
           SET permissions = (
               SELECT jsonb_agg(elem)
                 FROM jsonb_array_elements(permissions) AS elem
                WHERE elem #>> '{{}}' != '{ _PERM }'
           )
         WHERE name = 'admin'
           AND deleted_at IS NULL
        """
    )
