"""
Database models for BC Transportation Forms application
All 10 core tables with UUID primary keys, soft-deletes, audit timestamps
"""

from sqlalchemy import (
    Column, String, Text, Boolean, DateTime, ForeignKey, 
    Table, Integer, Index, UniqueConstraint, CheckConstraint, JSON
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TypeDecorator
import uuid
from datetime import datetime
from backend.database import Base


# Portable JSON type that works with both PostgreSQL (JSONB) and SQLite (JSON)
class PortableJSON(TypeDecorator):
    """Platform-independent JSON type.
    
    Uses JSONB for PostgreSQL for better performance, JSON for other databases.
    """
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(JSONB())
        else:
            return dialect.type_descriptor(JSON())


# ============================================================================
# TABLE 1: users
# ============================================================================
class User(Base):
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    keycloak_id = Column(String(255), unique=True, nullable=True, index=True)  # Keycloak user UUID
    email = Column(String(255), unique=True, nullable=False, index=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    last_login = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    roles = relationship("UserRole", back_populates="user", foreign_keys="UserRole.user_id", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user")
    
    __table_args__ = (
        CheckConstraint("email LIKE '%@%'", name='valid_email'),
    )


# ============================================================================
# TABLE 2: roles
# ============================================================================
class Role(Base):
    __tablename__ = "roles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    permissions = Column(PortableJSON, nullable=False, default={})  # JSON array of permission strings
    is_system = Column(Boolean, default=False, nullable=False)  # System roles (admin, staff_manager, etc)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    user_roles = relationship("UserRole", back_populates="role", cascade="all, delete-orphan")


# ============================================================================
# TABLE 3: user_roles (Junction Table)
# ============================================================================
class UserRole(Base):
    __tablename__ = "user_roles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_at = Column(DateTime, server_default=func.now(), nullable=False)
    assigned_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    
    # Relationships
    user = relationship("User", back_populates="roles", foreign_keys=[user_id])
    role = relationship("Role", back_populates="user_roles")
    assigned_by = relationship("User", foreign_keys=[assigned_by_id], remote_side=[User.id])
    
    __table_args__ = (
        UniqueConstraint('user_id', 'role_id', name='unique_user_role'),
    )


# ============================================================================
# TABLE 4: business_areas
# ============================================================================
class BusinessArea(Base):
    __tablename__ = "business_areas"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    form_business_areas = relationship("FormBusinessArea", back_populates="business_area", cascade="all, delete-orphan")


# ============================================================================
# TABLE 5: forms
# ============================================================================
class Form(Base):
    __tablename__ = "forms"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    category = Column(String(100), nullable=False, index=True)
    status = Column(String(50), default='draft', nullable=False, index=True)  # draft, pending_review, approved, published, archived
    is_public = Column(Boolean, default=False, nullable=False, index=True)
    current_version = Column(Integer, default=0, nullable=False)
    keywords = Column(PortableJSON, nullable=False, default=[])  # Array of search keywords
    search_vector = Column(String, nullable=True)  # Full-text search vector (tsvector)
    embedding = Column(String, nullable=True)  # Semantic embedding (vector)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    effective_date = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    created_by = relationship("User", foreign_keys=[created_by_id])
    versions = relationship("FormVersion", back_populates="form", cascade="all, delete-orphan")
    business_areas = relationship("FormBusinessArea", back_populates="form", cascade="all, delete-orphan")
    workflow_history = relationship("FormWorkflow", back_populates="form", cascade="all, delete-orphan")
    downloads = relationship("FormDownload", back_populates="form", cascade="all, delete-orphan")
    previews = relationship("FormPreview", back_populates="form", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_forms_status_public', 'status', 'is_public'),
        Index('idx_forms_category', 'category'),
        Index('idx_forms_created_by', 'created_by_id'),
    )


# ============================================================================
# TABLE 6: form_business_areas (Junction Table)
# ============================================================================
class FormBusinessArea(Base):
    __tablename__ = "form_business_areas"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    form_id = Column(UUID(as_uuid=True), ForeignKey("forms.id", ondelete="CASCADE"), nullable=False, index=True)
    business_area_id = Column(UUID(as_uuid=True), ForeignKey("business_areas.id", ondelete="CASCADE"), nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    
    # Relationships
    form = relationship("Form", back_populates="business_areas")
    business_area = relationship("BusinessArea", back_populates="form_business_areas")
    
    __table_args__ = (
        UniqueConstraint('form_id', 'business_area_id', name='unique_form_business_area'),
    )


# ============================================================================
# TABLE 7: form_versions
# ============================================================================
class FormVersion(Base):
    __tablename__ = "form_versions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    form_id = Column(UUID(as_uuid=True), ForeignKey("forms.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    s3_key = Column(String(500), nullable=False, unique=True)  # S3 object key
    file_name = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)  # Size in bytes
    file_type = Column(String(50), nullable=False)  # pdf, docx, etc
    change_notes = Column(Text, nullable=True)
    uploaded_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    is_current = Column(Boolean, default=False, nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    
    # Relationships
    form = relationship("Form", back_populates="versions")
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])
    
    __table_args__ = (
        UniqueConstraint('form_id', 'version_number', name='unique_form_version'),
        Index('idx_form_versions_is_current', 'form_id', 'is_current'),
    )


# ============================================================================
# TABLE 8: form_workflow
# ============================================================================
class FormWorkflow(Base):
    __tablename__ = "form_workflow"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    form_id = Column(UUID(as_uuid=True), ForeignKey("forms.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(50), nullable=False)  # submit_review, approve, reject, publish, unpublish, archive
    from_status = Column(String(50), nullable=False)  # Previous status
    to_status = Column(String(50), nullable=False)  # New status
    triggered_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reason_notes = Column(Text, nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    
    # Relationships
    form = relationship("Form", back_populates="workflow_history")
    triggered_by = relationship("User", foreign_keys=[triggered_by_id])
    
    __table_args__ = (
        Index('idx_form_workflow_form_date', 'form_id', 'created_at'),
    )


# ============================================================================
# TABLE 9: audit_log
# ============================================================================
class AuditLog(Base):
    __tablename__ = "audit_log"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String(100), nullable=False, index=True)  # users, forms, form_versions, etc
    entity_id = Column(String(100), nullable=False, index=True)
    action = Column(String(50), nullable=False, index=True)  # CREATE, UPDATE, DELETE, LOGIN, EXPORT
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    old_values = Column(PortableJSON, nullable=True)  # Previous state (immutable)
    new_values = Column(PortableJSON, nullable=True)  # New state (immutable)
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    
    # Relationships
    user = relationship("User", back_populates="audit_logs")
    
    __table_args__ = (
        Index('idx_audit_log_entity', 'entity_type', 'entity_id', 'created_at'),
        Index('idx_audit_log_user_date', 'user_id', 'created_at'),
    )


# ============================================================================
# TABLE 10: form_downloads (Analytics)
# ============================================================================
class FormDownload(Base):
    __tablename__ = "form_downloads"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    form_id = Column(UUID(as_uuid=True), ForeignKey("forms.id", ondelete="CASCADE"), nullable=False, index=True)
    form_version_id = Column(UUID(as_uuid=True), ForeignKey("form_versions.id"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)  # NULL for anonymous
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    referrer = Column(String(500), nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    
    # Relationships
    form = relationship("Form", back_populates="downloads")
    form_version = relationship("FormVersion", foreign_keys=[form_version_id])
    user = relationship("User", foreign_keys=[user_id])
    
    __table_args__ = (
        Index('idx_form_downloads_form_date', 'form_id', 'created_at'),
        Index('idx_form_downloads_user_date', 'user_id', 'created_at'),
    )


# ============================================================================
# TABLE 11: form_previews (Analytics)
# ============================================================================
class FormPreview(Base):
    __tablename__ = "form_previews"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    form_id = Column(UUID(as_uuid=True), ForeignKey("forms.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)  # NULL for anonymous
    duration_seconds = Column(Integer, nullable=True)  # How long form was viewed
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    
    # Relationships
    form = relationship("Form", back_populates="previews")
    user = relationship("User", foreign_keys=[user_id])
    
    __table_args__ = (
        Index('idx_form_previews_form_date', 'form_id', 'created_at'),
        Index('idx_form_previews_user_date', 'user_id', 'created_at'),
    )
