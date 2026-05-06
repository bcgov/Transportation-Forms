"""TASK-414: Add personal information collection indicator to forms

Revision ID: 006_personal_info_collection_field
Revises: 005_task_413_form_reservation_linkage
Create Date: 2026-03-12 00:00:00.000000

Adds:
  - collects_personal_info column to forms table (varchar with check constraint: 'Yes' or 'No')
  - Default value: 'No' (forms do not collect personal info by default)
  - Index on collects_personal_info for efficient filtering
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '006_personal_info_collection_field'
down_revision = '005_task_413_form_reservation_linkage'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add collects_personal_info column to forms table with check constraint
    op.add_column(
        'forms',
        sa.Column(
            'collects_personal_info',
            sa.String(10),
            nullable=False,
            default='No',
            server_default='No'
        )
    )
    
    # Add check constraint to ensure only 'Yes' or 'No' values are allowed
    op.create_check_constraint(
        'check_collects_personal_info_values',
        'forms',
        "collects_personal_info IN ('Yes', 'No')"
    )
    
    # Create index for efficient filtering
    op.create_index(
        'ix_forms_collects_personal_info',
        'forms',
        ['collects_personal_info']
    )


def downgrade() -> None:
    # Drop index
    op.drop_index('ix_forms_collects_personal_info', table_name='forms')
    
    # Drop check constraint
    op.drop_constraint('check_collects_personal_info_values', 'forms', type_='check')
    
    # Drop column
    op.drop_column('forms', 'collects_personal_info')
