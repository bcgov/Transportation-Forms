"""Initial schema - all 10 core tables

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-02-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create extension for UUID type
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    
    # TABLE 1: users
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('keycloak_id', sa.String(255), nullable=True),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('first_name', sa.String(100), nullable=True),
        sa.Column('last_name', sa.String(100), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_login', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("email LIKE '%@%'", name='valid_email'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('keycloak_id', name='uq_users_keycloak_id'),
        sa.UniqueConstraint('email', name='uq_users_email'),
    )
    op.create_index('ix_users_keycloak_id', 'users', ['keycloak_id'])
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_index('ix_users_is_active', 'users', ['is_active'])
    op.create_index('ix_users_deleted_at', 'users', ['deleted_at'])
    op.create_index('ix_users_created_at', 'users', ['created_at'])
    
    # TABLE 2: roles
    op.create_table(
        'roles',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('permissions', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_roles_name'),
    )
    op.create_index('ix_roles_name', 'roles', ['name'])
    op.create_index('ix_roles_is_active', 'roles', ['is_active'])
    op.create_index('ix_roles_deleted_at', 'roles', ['deleted_at'])
    op.create_index('ix_roles_created_at', 'roles', ['created_at'])
    
    # TABLE 3: user_roles (Junction)
    op.create_table(
        'user_roles',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('assigned_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('assigned_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assigned_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'role_id', name='uq_user_role'),
    )
    op.create_index('ix_user_roles_user_id', 'user_roles', ['user_id'])
    op.create_index('ix_user_roles_role_id', 'user_roles', ['role_id'])
    
    # TABLE 4: business_areas
    op.create_table(
        'business_areas',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_business_areas_name'),
    )
    op.create_index('ix_business_areas_name', 'business_areas', ['name'])
    op.create_index('ix_business_areas_is_active', 'business_areas', ['is_active'])
    op.create_index('ix_business_areas_deleted_at', 'business_areas', ['deleted_at'])
    op.create_index('ix_business_areas_created_at', 'business_areas', ['created_at'])
    
    # TABLE 5: forms
    op.create_table(
        'forms',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(100), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='draft'),
        sa.Column('is_public', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('current_version', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('keywords', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('search_vector', sa.String(), nullable=True),
        sa.Column('embedding', sa.String(), nullable=True),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('effective_date', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_forms_title', 'forms', ['title'])
    op.create_index('ix_forms_status', 'forms', ['status'])
    op.create_index('ix_forms_is_public', 'forms', ['is_public'])
    op.create_index('ix_forms_category', 'forms', ['category'])
    op.create_index('ix_forms_created_by_id', 'forms', ['created_by_id'])
    op.create_index('ix_forms_deleted_at', 'forms', ['deleted_at'])
    op.create_index('ix_forms_created_at', 'forms', ['created_at'])
    op.create_index('idx_forms_status_public', 'forms', ['status', 'is_public'])
    
    # TABLE 6: form_business_areas (Junction)
    op.create_table(
        'form_business_areas',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('form_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('business_area_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['form_id'], ['forms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['business_area_id'], ['business_areas.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('form_id', 'business_area_id', name='uq_form_business_area'),
    )
    op.create_index('ix_form_business_areas_form_id', 'form_business_areas', ['form_id'])
    op.create_index('ix_form_business_areas_business_area_id', 'form_business_areas', ['business_area_id'])
    
    # TABLE 7: form_versions
    op.create_table(
        'form_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('form_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('s3_key', sa.String(500), nullable=False),
        sa.Column('file_name', sa.String(255), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('file_type', sa.String(50), nullable=False),
        sa.Column('change_notes', sa.Text(), nullable=True),
        sa.Column('uploaded_by_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['form_id'], ['forms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('s3_key', name='uq_form_versions_s3_key'),
        sa.UniqueConstraint('form_id', 'version_number', name='uq_form_version_number'),
    )
    op.create_index('ix_form_versions_form_id', 'form_versions', ['form_id'])
    op.create_index('ix_form_versions_uploaded_by_id', 'form_versions', ['uploaded_by_id'])
    op.create_index('ix_form_versions_is_current', 'form_versions', ['is_current'])
    op.create_index('ix_form_versions_deleted_at', 'form_versions', ['deleted_at'])
    op.create_index('idx_form_versions_is_current', 'form_versions', ['form_id', 'is_current'])
    
    # TABLE 8: form_workflow
    op.create_table(
        'form_workflow',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('form_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('from_status', sa.String(50), nullable=False),
        sa.Column('to_status', sa.String(50), nullable=False),
        sa.Column('triggered_by_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('reason_notes', sa.Text(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['form_id'], ['forms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['triggered_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_form_workflow_form_id', 'form_workflow', ['form_id'])
    op.create_index('ix_form_workflow_triggered_by_id', 'form_workflow', ['triggered_by_id'])
    op.create_index('idx_form_workflow_form_date', 'form_workflow', ['form_id', 'created_at'])
    
    # TABLE 9: audit_log
    op.create_table(
        'audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('entity_type', sa.String(100), nullable=False),
        sa.Column('entity_id', sa.String(100), nullable=False),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('old_values', postgresql.JSONB(), nullable=True),
        sa.Column('new_values', postgresql.JSONB(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_log_entity_type', 'audit_log', ['entity_type'])
    op.create_index('ix_audit_log_entity_id', 'audit_log', ['entity_id'])
    op.create_index('ix_audit_log_action', 'audit_log', ['action'])
    op.create_index('ix_audit_log_user_id', 'audit_log', ['user_id'])
    op.create_index('ix_audit_log_deleted_at', 'audit_log', ['deleted_at'])
    op.create_index('ix_audit_log_created_at', 'audit_log', ['created_at'])
    op.create_index('idx_audit_log_entity', 'audit_log', ['entity_type', 'entity_id', 'created_at'])
    op.create_index('idx_audit_log_user_date', 'audit_log', ['user_id', 'created_at'])
    
    # TABLE 10: form_downloads (Analytics)
    op.create_table(
        'form_downloads',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('form_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('form_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('referrer', sa.String(500), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['form_id'], ['forms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['form_version_id'], ['form_versions.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_form_downloads_form_id', 'form_downloads', ['form_id'])
    op.create_index('ix_form_downloads_form_version_id', 'form_downloads', ['form_version_id'])
    op.create_index('ix_form_downloads_user_id', 'form_downloads', ['user_id'])
    op.create_index('idx_form_downloads_form_date', 'form_downloads', ['form_id', 'created_at'])
    op.create_index('idx_form_downloads_user_date', 'form_downloads', ['user_id', 'created_at'])
    
    # TABLE 11: form_previews (Analytics)
    op.create_table(
        'form_previews',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('form_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['form_id'], ['forms.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_form_previews_form_id', 'form_previews', ['form_id'])
    op.create_index('ix_form_previews_user_id', 'form_previews', ['user_id'])
    op.create_index('idx_form_previews_form_date', 'form_previews', ['form_id', 'created_at'])
    op.create_index('idx_form_previews_user_date', 'form_previews', ['user_id', 'created_at'])


def downgrade() -> None:
    # Drop all tables in reverse order (respecting foreign keys)
    op.drop_table('form_previews')
    op.drop_table('form_downloads')
    op.drop_table('audit_log')
    op.drop_table('form_workflow')
    op.drop_table('form_versions')
    op.drop_table('form_business_areas')
    op.drop_table('forms')
    op.drop_table('business_areas')
    op.drop_table('user_roles')
    op.drop_table('roles')
    op.drop_table('users')
    
    # Drop extensions
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
