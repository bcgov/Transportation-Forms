"""TASK-417: Remove category field from forms table

Revision ID: 007_remove_category_field
Revises: 006_personal_info_collection_field
Create Date: 2026-03-12 00:00:00.000000

Removes:
  - category column from forms table
  - idx_forms_category index
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '007_remove_category_field'
down_revision = '006_personal_info_collection_field'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the index first, then the column.
    # if_exists=True guards against the index already being absent.
    op.drop_index('ix_forms_category', table_name='forms', if_exists=True)
    op.drop_column('forms', 'category')


def downgrade() -> None:
    # Restore the column and index
    op.add_column(
        'forms',
        sa.Column('category', sa.String(100), nullable=False, server_default='other')
    )
    op.create_index('ix_forms_category', 'forms', ['category'])
