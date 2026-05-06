"""TASK-401: Form Number Prefix Configuration table

Revision ID: 003_form_number_prefixes
Revises: 002_task_110c
Create Date: 2026-02-27 00:00:00.000000

Adds:
  - form_number_prefixes table for admin-configurable prefix definitions
    with independent sequence counters, padding, and validation settings.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003_form_number_prefixes'
down_revision = '002_task_110c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'form_number_prefixes',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('prefix', sa.String(10), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('current_sequence', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('padding_length', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('max_number_length', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('is_case_sensitive', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('prefix', name='uq_form_number_prefixes_prefix'),
    )
    op.create_index('ix_fnp_prefix', 'form_number_prefixes', ['prefix'], unique=True)
    op.create_index('ix_fnp_is_active', 'form_number_prefixes', ['is_active'])
    op.create_index('ix_fnp_deleted_at', 'form_number_prefixes', ['deleted_at'])
    op.create_index('ix_fnp_created_at', 'form_number_prefixes', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_fnp_created_at', table_name='form_number_prefixes')
    op.drop_index('ix_fnp_deleted_at', table_name='form_number_prefixes')
    op.drop_index('ix_fnp_is_active', table_name='form_number_prefixes')
    op.drop_index('ix_fnp_prefix', table_name='form_number_prefixes')
    op.drop_table('form_number_prefixes')
