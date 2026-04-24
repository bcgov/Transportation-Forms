"""FEAT-0001: Revise form workflow states — migrate approved → published

Revision ID: 011_feat_0001_revise_workflow_states
Revises: 010_task_423_access_requests
Create Date: 2026-04-23 00:00:00.000000

Removes the intermediate 'approved' state from the form lifecycle.
Any form currently in 'approved' is forward-migrated to 'published' (BR-005).
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "011_feat_0001_revise_workflow_states"
down_revision = "010_task_423_access_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # BR-005: Migrate existing forms in the deprecated 'approved' state to 'published'.
    # This is a one-way, safe data migration — 'approved' rows are rare/zero in practice
    # but must be handled before the application enforces the new state machine.
    op.execute(
        """
        UPDATE forms
           SET status = 'published'
         WHERE status = 'approved'
           AND deleted_at IS NULL
        """
    )

    # Also update any form_workflow audit entries that reference the removed state
    # so historical records remain internally consistent.
    op.execute(
        """
        UPDATE form_workflow
           SET to_status = 'published'
         WHERE to_status = 'approved'
           AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    # One-way migration: reversing this would arbitrarily move published→approved
    # which is not safe without knowing original intent. Left as no-op per ADR-004.
    pass
