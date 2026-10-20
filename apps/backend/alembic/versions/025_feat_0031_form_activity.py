"""Add durable, actor-snapshotted form activity history (launch-forward only).

Revision ID: 025_feat_0031_form_activity
Revises: 024_feat_0031_form_audit
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "025_feat_0031_form_activity"
down_revision = "024_feat_0031_form_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "form_activity_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "form_id",
            UUID(as_uuid=True),
            sa.ForeignKey("forms.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_name", sa.String(50), nullable=False),
        sa.Column("actor_label", sa.String(255), nullable=False),
        sa.Column("changed_fields", JSONB, nullable=False),
        sa.Column("old_values", JSONB, nullable=False),
        sa.Column("new_values", JSONB, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_form_activity_page",
        "form_activity_events",
        ["form_id", "occurred_at", "id"],
    )
    op.create_index(
        "ix_form_activity_events_form_id",
        "form_activity_events",
        ["form_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_form_activity_events_form_id",
        table_name="form_activity_events",
    )
    op.drop_index("idx_form_activity_page", table_name="form_activity_events")
    op.drop_table("form_activity_events")
