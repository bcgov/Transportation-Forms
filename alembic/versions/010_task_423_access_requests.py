"""TASK-423: add access requests table

Revision ID: 010_task_423_access_requests
Revises: 009_task_111_search_vector
Create Date: 2026-03-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "010_task_423_access_requests"
down_revision = "009_task_111_search_vector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "access_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("processed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["processed_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_access_request_status"),
    )

    op.create_index("ix_access_requests_user_id", "access_requests", ["user_id"])
    op.create_index("ix_access_requests_status", "access_requests", ["status"])
    op.create_index("ix_access_requests_processed_by_id", "access_requests", ["processed_by_id"])
    op.create_index("ix_access_requests_processed_at", "access_requests", ["processed_at"])
    op.create_index("ix_access_requests_deleted_at", "access_requests", ["deleted_at"])
    op.create_index("ix_access_requests_created_at", "access_requests", ["created_at"])
    op.execute(
        """
        CREATE UNIQUE INDEX ix_access_requests_pending_user
        ON access_requests (user_id)
        WHERE deleted_at IS NULL AND status = 'pending'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_access_requests_pending_user", table_name="access_requests")
    op.drop_index("ix_access_requests_created_at", table_name="access_requests")
    op.drop_index("ix_access_requests_deleted_at", table_name="access_requests")
    op.drop_index("ix_access_requests_processed_at", table_name="access_requests")
    op.drop_index("ix_access_requests_processed_by_id", table_name="access_requests")
    op.drop_index("ix_access_requests_status", table_name="access_requests")
    op.drop_index("ix_access_requests_user_id", table_name="access_requests")
    op.drop_table("access_requests")
