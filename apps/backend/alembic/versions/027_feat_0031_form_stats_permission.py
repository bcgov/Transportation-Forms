"""Grant form:stats to existing system admin roles.

Revision ID: 027_feat_0031_form_stats_permission
Revises: 026_feat_0031_daily_engagement_counts
"""

from alembic import op

revision = "027_feat_0031_form_stats_permission"
down_revision = "026_feat_0031_daily_engagement_counts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE roles
           SET permissions = permissions || '["form:stats"]'::jsonb
         WHERE name = 'admin'
           AND is_system IS TRUE
           AND deleted_at IS NULL
           AND jsonb_typeof(permissions) = 'array'
           AND NOT (permissions @> '["form:stats"]'::jsonb)
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE roles
           SET permissions = permissions - 'form:stats'
         WHERE name = 'admin'
           AND is_system IS TRUE
           AND jsonb_typeof(permissions) = 'array'
           AND permissions @> '["form:stats"]'::jsonb
    """)
