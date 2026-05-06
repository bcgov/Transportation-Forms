"""TASK-110C: Form Creation Enhancement - new form columns and business_area_contacts

Revision ID: 002_task_110c
Revises: 001_initial_schema
Create Date: 2026-02-19 00:00:00.000000

Adds:
  - version_number, form_source, form_source_url, form_attachment_url,
    form_attachment_filename columns to forms table
  - business_area_contacts junction table

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002_task_110c'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # Extend forms table with new columns
    # -------------------------------------------------------------------------
    op.add_column('forms', sa.Column('version_number', sa.Integer(), nullable=True, server_default='1'))
    op.add_column('forms', sa.Column('form_source', sa.String(50), nullable=True))           # 'URL' or 'Download'
    op.add_column('forms', sa.Column('form_source_url', sa.String(500), nullable=True))      # URL when source=URL
    op.add_column('forms', sa.Column('form_attachment_url', sa.String(500), nullable=True))  # MinIO URL when source=Download
    op.add_column('forms', sa.Column('form_attachment_filename', sa.String(255), nullable=True))

    # -------------------------------------------------------------------------
    # Create business_area_contacts junction table
    # Supports future contact-person management per business area (FR-ADMIN-014+)
    # -------------------------------------------------------------------------
    op.create_table(
        'business_area_contacts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('business_area_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('contact_user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['business_area_id'], ['business_areas.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contact_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_bac_business_area_id', 'business_area_contacts', ['business_area_id'])
    op.create_index('ix_bac_contact_user_id', 'business_area_contacts', ['contact_user_id'])
    op.create_index('ix_bac_created_at', 'business_area_contacts', ['created_at'])


def downgrade() -> None:
    # Drop new table
    op.drop_table('business_area_contacts')

    # Remove new columns from forms
    op.drop_column('forms', 'form_attachment_filename')
    op.drop_column('forms', 'form_attachment_url')
    op.drop_column('forms', 'form_source_url')
    op.drop_column('forms', 'form_source')
    op.drop_column('forms', 'version_number')
