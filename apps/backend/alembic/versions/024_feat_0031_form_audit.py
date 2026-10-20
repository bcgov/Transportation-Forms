"""FEAT-0031 US-006: grant form:audit to the existing system admin role.

Revision ID: 024_feat_0031_form_audit
Revises: 023_feat_0030_forms_sort_options
Create Date: 2026-10-20 00:00:00.000000

New admin roles receive this permission through DEFAULT_ROLES. Existing
roles need this migration because the default-role seed does not update them.
"""

from alembic import op

revision = "024_feat_0031_form_audit"
down_revision = "023_feat_0030_forms_sort_options"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE roles
           SET permissions = permissions || '["form:audit"]'::jsonb
         WHERE name = 'admin'
           AND is_system IS TRUE
           AND deleted_at IS NULL
           AND jsonb_typeof(permissions) = 'array'
           AND NOT (permissions @> '["form:audit"]'::jsonb)
        """)


def downgrade() -> None:
    op.execute("""
        UPDATE roles
           SET permissions = permissions - 'form:audit'
         WHERE name = 'admin'
           AND is_system IS TRUE
           AND jsonb_typeof(permissions) = 'array'
           AND permissions @> '["form:audit"]'::jsonb
        """)
