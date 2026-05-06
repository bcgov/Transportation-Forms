"""TASK-413: Link Form Numbers to Form Reservations

Revision ID: 005_task_413_form_reservation_linkage
Revises: 004_form_reservation_schema
Create Date: 2026-03-11 00:00:00.000000

Adds:
  - form_number_reservation_id column to forms table (nullable FK to form_number_reservations)
  - Index on form_number_reservation_id for efficient lookups
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005_task_413_form_reservation_linkage'
down_revision = '004_form_reservation_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure alembic version identifiers fit long revision IDs used in this project.
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")

    # Add form_number_reservation_id column to forms table
    op.add_column(
        'forms',
        sa.Column('form_number_reservation_id', postgresql.UUID(as_uuid=True), nullable=True)
    )
    
    # Add FK constraint
    op.create_foreign_key(
        'fk_forms_form_number_reservation_id',
        'forms',
        'form_number_reservations',
        ['form_number_reservation_id'],
        ['id'],
        ondelete='SET NULL'
    )
    
    # Create index for efficient lookups
    op.create_index(
        'ix_forms_form_number_reservation_id',
        'forms',
        ['form_number_reservation_id']
    )


def downgrade() -> None:
    # Drop index
    op.drop_index('ix_forms_form_number_reservation_id', table_name='forms')
    
    # Drop FK constraint
    op.drop_constraint('fk_forms_form_number_reservation_id', 'forms', type_='foreignkey')
    
    # Drop column
    op.drop_column('forms', 'form_number_reservation_id')
