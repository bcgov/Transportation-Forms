"""TASK-420: remove user-facing forms.version_number field

Revision ID: 008_task_420_remove_form_user_version_field
Revises: 007_remove_category_field
Create Date: 2026-03-13 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '008_task_420_remove_form_user_version_field'
down_revision = '007_remove_category_field'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('forms', 'version_number')


def downgrade() -> None:
    op.add_column('forms', sa.Column('version_number', sa.Integer(), nullable=True, server_default='1'))
