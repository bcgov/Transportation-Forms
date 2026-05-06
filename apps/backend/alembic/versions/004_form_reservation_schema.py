"""TASK-403: Form Number Reservation and Approver tables

Revision ID: 004_form_reservation_schema
Revises: 003_form_number_prefixes
Create Date: 2026-02-27 00:00:00.000000

Adds:
  - form_number_reservations table for tracking reserved form numbers
  - form_reservation_approvers table for approval workflow tracking
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_form_reservation_schema'
down_revision = '003_form_number_prefixes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -----------------------------------------------------------------
    # form_number_reservations
    # -----------------------------------------------------------------
    op.create_table(
        'form_number_reservations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('prefix_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('form_number', sa.String(50), nullable=False),
        sa.Column('full_form_number', sa.String(70), nullable=False),
        sa.Column('numbering_method', sa.String(20), nullable=False),
        sa.Column('custom_number_reason', sa.Text(), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='reserved'),
        sa.Column('reserved_by_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('released_at', sa.DateTime(), nullable=True),
        sa.Column('released_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['prefix_id'], ['form_number_prefixes.id']),
        sa.ForeignKeyConstraint(['reserved_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['released_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "numbering_method IN ('auto_generated', 'custom')",
            name='ck_fnr_numbering_method',
        ),
        sa.CheckConstraint(
            "status IN ('reserved', 'pending_approval', 'approved', 'rejected', 'changes_requested', 'released', 'expired')",
            name='ck_fnr_status',
        ),
    )

    # Partial unique index: only one active (non-released, non-expired, non-deleted) reservation per form number
    op.execute(
        """
        CREATE UNIQUE INDEX ix_fnr_full_form_number_active
        ON form_number_reservations (full_form_number)
        WHERE deleted_at IS NULL AND status NOT IN ('released', 'expired')
        """
    )
    op.create_index('ix_fnr_status', 'form_number_reservations', ['status'])
    op.create_index('ix_fnr_prefix_id', 'form_number_reservations', ['prefix_id'])
    op.create_index('ix_fnr_reserved_by_id', 'form_number_reservations', ['reserved_by_id'])
    op.create_index('ix_fnr_expires_at', 'form_number_reservations', ['expires_at'])
    op.create_index('ix_fnr_deleted_at', 'form_number_reservations', ['deleted_at'])
    op.create_index('ix_fnr_created_at', 'form_number_reservations', ['created_at'])

    # -----------------------------------------------------------------
    # form_reservation_approvers
    # -----------------------------------------------------------------
    op.create_table(
        'form_reservation_approvers',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('reservation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('approver_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('decision', sa.String(30), nullable=True),
        sa.Column('decision_reason', sa.Text(), nullable=True),
        sa.Column('decision_comments', sa.Text(), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['reservation_id'], ['form_number_reservations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['approver_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('reservation_id', 'approver_id', name='uq_reservation_approver'),
    )
    op.create_index('ix_fra_reservation_id', 'form_reservation_approvers', ['reservation_id'])
    op.create_index('ix_fra_approver_id', 'form_reservation_approvers', ['approver_id'])
    op.create_index('ix_fra_deleted_at', 'form_reservation_approvers', ['deleted_at'])
    op.create_index('ix_fra_created_at', 'form_reservation_approvers', ['created_at'])


def downgrade() -> None:
    # Drop approvers table first (FK dependency)
    op.drop_index('ix_fra_created_at', table_name='form_reservation_approvers')
    op.drop_index('ix_fra_deleted_at', table_name='form_reservation_approvers')
    op.drop_index('ix_fra_approver_id', table_name='form_reservation_approvers')
    op.drop_index('ix_fra_reservation_id', table_name='form_reservation_approvers')
    op.drop_table('form_reservation_approvers')

    # Drop reservations table
    op.drop_index('ix_fnr_created_at', table_name='form_number_reservations')
    op.drop_index('ix_fnr_deleted_at', table_name='form_number_reservations')
    op.drop_index('ix_fnr_expires_at', table_name='form_number_reservations')
    op.drop_index('ix_fnr_reserved_by_id', table_name='form_number_reservations')
    op.drop_index('ix_fnr_prefix_id', table_name='form_number_reservations')
    op.drop_index('ix_fnr_status', table_name='form_number_reservations')
    op.drop_index('ix_fnr_full_form_number_active', table_name='form_number_reservations')
    op.drop_table('form_number_reservations')
