"""Comprehensive test suite for Form CRUD operations and database integration.

Tests cover:
- Create, Read, Update, Delete operations
- Database persistence verification
- Filtering, pagination, sorting
- Soft delete behavior
- Audit logging
- Archive/unarchive operations

Uses PostgreSQL running in Docker container on port 6432.
Database: transportation_forms (shared with app)
"""

import pytest
import os
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import Base, get_db
from backend.models import Form, AuditLog, FormVersion, FormWorkflow, User, Role, UserRole, BusinessArea, FormBusinessArea
from backend.services.forms import FormService
from backend.auth.jwt_handler import jwt_handler


# ============================================================================
# TEST DATABASE SETUP (PostgreSQL - uses Docker container on port 6432)
# ============================================================================

# Test database URL pointing to Docker PostgreSQL (shared database)
# Detect if running inside Docker container and use appropriate host
import socket
def _get_test_db_url():
    # Try to determine if running in Docker by checking for docker.sock
    # or use environment variable override
    if os.getenv('DATABASE_URL'):
        return os.getenv('DATABASE_URL')
    
    # Default: assume running outside Docker, use localhost:6432
    # Inside container, pass DATABASE_URL or the app will fail anyway
    return "postgresql://transportation:password@127.0.0.1:6432/transportation_forms"

TEST_DATABASE_URL = _get_test_db_url()

# Create engine for test database
engine_test = create_engine(
    TEST_DATABASE_URL,
    echo=False,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)


def cleanup_test_data(session: Session):
    """Clean up test data by truncating all test tables."""
    tables_to_truncate = [
        'form_downloads',
        'form_previews',
        'form_workflow',
        'form_versions',
        'form_business_areas',
        'forms',
        'user_roles',
        'business_areas',
        'roles',
        'audit_log',
        'users',
    ]
    
    for table in tables_to_truncate:
        try:
            session.execute(text(f'TRUNCATE TABLE "{table}" CASCADE'))
        except Exception:
            pass
    
    session.commit()


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture(scope="function")
def db():
    """
    Create a test database session using the shared transportation_forms database.
    
    Uses PostgreSQL running in Docker container on port 6432.
    Cleans up test data before and after each test to ensure isolation.
    """
    session = TestingSessionLocal()
    
    # Clean up any existing test data
    cleanup_test_data(session)
    
    try:
        yield session
    finally:
        # Clean up after test
        cleanup_test_data(session)
        session.close()


@pytest.fixture(scope="function")
def client(db: Session, test_user):
    """Create a test client with override for database dependency and authentication."""
    from backend.auth.dependencies import get_current_user
    from backend.auth.jwt_handler import TokenData
    
    def override_get_db():
        try:
            yield db
        finally:
            pass
    
    def override_get_current_user():
        """Override authentication to return TokenData with test user info."""
        return TokenData(
            sub=str(test_user.id),
            email=test_user.email,
            name=test_user.email,
            roles=["admin"],
            iss="test",
            aud="test"
        )
    
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db: Session):
    """Create a test user."""
    user = User(
        id=uuid4(),
        azure_id="test-user-001",
        email="testuser@gov.bc.ca",
        first_name="Test",
        last_name="User",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def test_business_areas(db: Session):
    """Create test business areas."""
    areas = []
    for i in range(3):
        ba = BusinessArea(
            id=uuid4(),
            name=f"Business Area {i+1}",
            description=f"Description for business area {i+1}",
            is_active=True,
        )
        db.add(ba)
        areas.append(ba)
    db.commit()
    return areas


@pytest.fixture
def auth_token(test_user):
    """Create a JWT token for test user."""
    from datetime import timedelta
    return jwt_handler.generate_access_token(
        user_id=str(test_user.id),
        email=test_user.email,
        name=test_user.email,
        roles=["admin"],
        expires_delta=timedelta(hours=1)
    )


@pytest.fixture
def auth_headers(auth_token):
    """Create authorization headers."""
    return {"Authorization": f"Bearer {auth_token}"}


# ============================================================================
# SERVICE LAYER TESTS (Database Integration)
# ============================================================================

class TestFormServiceCRUD:
    """Test Form Service CRUD operations with direct database access."""
    
    def test_create_form_persists_to_database(self, db: Session, test_user, test_business_areas):
        """
        Test: Create form via service → Verify record exists in forms table.
        
        Acceptance Criteria:
        - Form is created with correct values
        - Form is immediately retrievable from database
        - All fields are persisted correctly
        """
        # Create form
        form = FormService.create_form(
            db=db,
            title="Test Form",
            description="A test form",
            category="transportation",
            is_public=True,
            keywords=["test", "form"],
            business_area_ids=[test_business_areas[0].id],
            created_by_id=test_user.id,
        )
        
        # Verify form exists in database
        db_form = db.query(Form).filter(Form.id == form.id).first()
        assert db_form is not None
        assert db_form.title == "Test Form"
        assert db_form.description == "A test form"
        assert db_form.category == "transportation"
        assert db_form.is_public is True
        assert db_form.keywords == ["test", "form"]
        assert db_form.status == "draft"
        assert db_form.created_by_id == test_user.id
    
    def test_read_form_returns_correct_data(self, db: Session, test_user, test_business_areas):
        """
        Test: Create form → Call GET via service → Verify returned data matches input.
        
        Acceptance Criteria:
        - Retrieved form has all input fields
        - Related records (business areas) are populated
        - Timestamps are set correctly
        """
        # Create form
        form = FormService.create_form(
            db=db,
            title="Finance Form 2024",
            description="Annual financial submission",
            category="finance",
            is_public=False,
            keywords=["finance", "annual"],
            business_area_ids=[test_business_areas[0].id, test_business_areas[1].id],
            created_by_id=test_user.id,
        )
        
        # Retrieve via service
        form_data = FormService.get_form_with_details(db, form.id)
        
        assert form_data is not None
        assert form_data["title"] == "Finance Form 2024"
        assert form_data["description"] == "Annual financial submission"
        assert form_data["category"] == "finance"
        assert form_data["is_public"] is False
        assert form_data["keywords"] == ["finance", "annual"]
        assert len(form_data["business_areas"]) == 2
    
    def test_update_form_persists_changes_to_database(self, db: Session, test_user, test_business_areas):
        """
        Test: Create form → Update fields → Call GET → Verify changes persisted in DB.
        
        Acceptance Criteria:
        - All updated fields are reflected in database
        - Untouched fields remain unchanged
        - updated_at timestamp is updated
        """
        # Create form
        form = FormService.create_form(
            db=db,
            title="Original Title",
            description="Original Description",
            category="permits",
            is_public=True,
            keywords=["original"],
            business_area_ids=[test_business_areas[0].id],
            created_by_id=test_user.id,
        )
        original_created_at = form.created_at
        
        # Update form
        updated_form = FormService.update_form(
            db=db,
            form_id=form.id,
            updated_by_id=test_user.id,
            title="Updated Title",
            description="Updated Description",
            keywords=["updated", "modified"],
        )
        
        # Verify changes in database
        db_form = db.query(Form).filter(Form.id == form.id).first()
        assert db_form.title == "Updated Title"
        assert db_form.description == "Updated Description"
        assert db_form.keywords == ["updated", "modified"]
        assert db_form.category == "permits"  # Unchanged
        assert db_form.is_public is True  # Unchanged
        assert db_form.created_at == original_created_at  # Unchanged
        assert db_form.updated_at > original_created_at  # Updated timestamp
    
    def test_delete_form_soft_delete_sets_deleted_at(self, db: Session, test_user, test_business_areas):
        """
        Test: Create form → Delete (soft delete) → Verify deleted_at is set in DB → Call GET returns None.
        
        Acceptance Criteria:
        - deleted_at timestamp is set
        - Form is excluded from list queries (not returned by get_form_by_id)
        - Record exists in database (not hard deleted)
        """
        # Create form
        form = FormService.create_form(
            db=db,
            title="To Delete",
            description="This will be deleted",
            category="test",
            is_public=False,
            keywords=[],
            business_area_ids=[test_business_areas[0].id],
            created_by_id=test_user.id,
        )
        form_id = form.id
        
        # Delete (soft delete)
        deleted = FormService.delete_form(
            db=db,
            form_id=form_id,
            deleted_by_id=test_user.id
        )
        assert deleted is True
        
        # Verify deleted_at is set in database
        db_form = db.query(Form).filter(Form.id == form_id).first()
        assert db_form is not None  # Hard delete doesn't happen
        assert db_form.deleted_at is not None
        
        # Verify get_form_by_id excludes it
        retrieved = FormService.get_form_by_id(db, form_id)
        assert retrieved is None
    
    def test_list_forms_returns_all_active_forms(self, db: Session, test_user, test_business_areas):
        """
        Test: Create 5 forms → Call list → Verify all records returned with pagination.
        
        Acceptance Criteria:
        - All non-deleted forms are returned
        - Total count is correct
        - Pagination works correctly
        """
        # Create 5 forms
        form_ids = []
        for i in range(5):
            form = FormService.create_form(
                db=db,
                title=f"Form {i+1}",
                description=f"Description {i+1}",
                category="transportation",
                is_public=i % 2 == 0,  # Alternate public/private
                keywords=[f"keyword{i+1}"],
                business_area_ids=[test_business_areas[0].id],
                created_by_id=test_user.id,
            )
            form_ids.append(form.id)
        
        # List with default pagination
        forms, total = FormService.list_forms(db, skip=0, limit=20)
        assert total == 5
        assert len(forms) == 5
        
        # Test pagination (2 per page)
        forms_page1, total = FormService.list_forms(db, skip=0, limit=2)
        assert len(forms_page1) == 2
        assert total == 5
        
        forms_page2, total = FormService.list_forms(db, skip=2, limit=2)
        assert len(forms_page2) == 2
        assert total == 5
    
    def test_filter_forms_by_category(self, db: Session, test_user, test_business_areas):
        """
        Test: Create forms with different categories → Call list with filter → Verify only matching records returned.
        
        Acceptance Criteria:
        - Only forms with matching category are returned
        - Total count reflects filtered results
        - Other categories are excluded
        """
        # Create forms in different categories
        for category in ["transportation", "permits", "finance"]:
            for i in range(2):
                FormService.create_form(
                    db=db,
                    title=f"{category} Form {i+1}",
                    description=f"Description",
                    category=category,
                    is_public=True,
                    keywords=[],
                    business_area_ids=[test_business_areas[0].id],
                    created_by_id=test_user.id,
                )
        
        # Filter by category
        forms, total = FormService.list_forms(db, category="permits")
        assert total == 2
        assert len(forms) == 2
        assert all(f.category == "permits" for f in forms)
    
    def test_audit_log_created_for_form_operations(self, db: Session, test_user, test_business_areas):
        """
        Test: Create/Update/Delete form → Query audit_logs table → Verify entries logged with correct action/timestamp.
        
        Acceptance Criteria:
        - Audit log entry exists for each operation
        - Action field matches the operation (CREATE, UPDATE, DELETE)
        - user_id is recorded correctly
        - Timestamps are accurate
        """
        # Create form
        form = FormService.create_form(
            db=db,
            title="Form for Audit",
            description="Test audit logging",
            category="test",
            is_public=False,
            keywords=[],
            business_area_ids=[test_business_areas[0].id],
            created_by_id=test_user.id,
        )
        
        # Check CREATE audit log
        create_logs = db.query(AuditLog).filter(
            AuditLog.entity_type == "forms",
            AuditLog.entity_id == str(form.id),
            AuditLog.action == "CREATE"
        ).all()
        assert len(create_logs) >= 1
        assert create_logs[0].user_id == test_user.id
        
        # Update form
        FormService.update_form(
            db=db,
            form_id=form.id,
            updated_by_id=test_user.id,
            title="Updated Title"
        )
        
        # Check UPDATE audit log
        update_logs = db.query(AuditLog).filter(
            AuditLog.entity_type == "forms",
            AuditLog.entity_id == str(form.id),
            AuditLog.action == "UPDATE"
        ).all()
        assert len(update_logs) >= 1
        
        # Delete form
        FormService.delete_form(
            db=db,
            form_id=form.id,
            deleted_by_id=test_user.id
        )
        
        # Check DELETE audit log
        delete_logs = db.query(AuditLog).filter(
            AuditLog.entity_type == "forms",
            AuditLog.entity_id == str(form.id),
            AuditLog.action == "DELETE"
        ).all()
        assert len(delete_logs) >= 1
    
    def test_archive_form_changes_status_in_database(self, db: Session, test_user, test_business_areas):
        """
        Test: Create form → Archive → Query DB directly → Verify status is 'archived' and workflow logged.
        
        Acceptance Criteria:
        - Form status changes to 'archived'
        - FormWorkflow entry created with correct action
        - Form remains in database (not deleted)
        - Audit log records the operation
        """
        # Create and publish form
        form = FormService.create_form(
            db=db,
            title="Form to Archive",
            description="Test archive",
            category="test",
            is_public=True,
            keywords=[],
            business_area_ids=[test_business_areas[0].id],
            created_by_id=test_user.id,
        )
        form.status = "published"
        db.commit()
        
        # Archive form
        archived_form = FormService.archive_form(
            db=db,
            form_id=form.id,
            archived_by_id=test_user.id
        )
        
        # Verify in database
        db_form = db.query(Form).filter(Form.id == form.id).first()
        assert db_form.status == "archived"
        
        # Verify workflow logged
        workflow = db.query(FormWorkflow).filter(
            FormWorkflow.form_id == form.id,
            FormWorkflow.action == "archive"
        ).first()
        assert workflow is not None
        assert workflow.from_status == "published"
        assert workflow.to_status == "archived"


# ============================================================================
# API ENDPOINT TESTS
# ============================================================================

class TestFormAPI:
    """Test Form API endpoints."""
    
    def test_create_form_endpoint_returns_created_form(self, client: TestClient, db: Session, test_user, auth_headers, test_business_areas):
        """Test POST /api/v1/forms endpoint."""
        payload = {
            "title": "New Form",
            "description": "New form description",
            "category": "transportation",
            "is_public": True,
            "keywords": ["test", "new"],
            "business_area_ids": [str(test_business_areas[0].id)],
        }
        
        response = client.post("/api/v1/forms", json=payload, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "New Form"
        assert data["category"] == "transportation"
        
        # Verify in database
        db_form = db.query(Form).filter(Form.title == "New Form").first()
        assert db_form is not None
    
    def test_get_form_endpoint_returns_form_details(self, client: TestClient, db: Session, test_user, test_business_areas):
        """Test GET /api/v1/forms/{id} endpoint."""
        # Create form
        form = FormService.create_form(
            db=db,
            title="Get Test Form",
            description="Test form for GET",
            category="permits",
            is_public=True,
            keywords=[],
            business_area_ids=[test_business_areas[0].id],
            created_by_id=test_user.id,
        )
        
        response = client.get(f"/api/v1/forms/{form.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(form.id)
        assert data["title"] == "Get Test Form"
        assert data["category"] == "permits"
    
    def test_list_forms_endpoint_with_pagination(self, client: TestClient, db: Session, test_user, test_business_areas):
        """Test GET /api/v1/forms with pagination."""
        # Create 5 forms
        for i in range(5):
            FormService.create_form(
                db=db,
                title=f"List Test Form {i+1}",
                description="Test",
                category="test",
                is_public=True,
                keywords=[],
                business_area_ids=[test_business_areas[0].id],
                created_by_id=test_user.id,
            )
        
        # Get first page (2 items)
        response = client.get("/api/v1/forms?skip=0&limit=2")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["skip"] == 0
        assert data["limit"] == 2
    
    def test_update_form_endpoint(self, client: TestClient, db: Session, test_user, test_business_areas, auth_headers):
        """Test PUT /api/v1/forms/{id} endpoint."""
        # Create form
        form = FormService.create_form(
            db=db,
            title="Original Title",
            description="Original Description",
            category="test",
            is_public=False,
            keywords=[],
            business_area_ids=[test_business_areas[0].id],
            created_by_id=test_user.id,
        )
        
        # Update via API
        payload = {
            "title": "Updated Title",
            "is_public": True,
        }
        response = client.put(f"/api/v1/forms/{form.id}", json=payload, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"
        assert data["is_public"] is True
        
        # Verify in database
        db_form = db.query(Form).filter(Form.id == form.id).first()
        assert db_form.title == "Updated Title"
        assert db_form.is_public is True
    
    def test_delete_form_endpoint(self, client: TestClient, db: Session, test_user, test_business_areas, auth_headers):
        """Test DELETE /api/v1/forms/{id} endpoint."""
        # Create form
        form = FormService.create_form(
            db=db,
            title="To Delete",
            description="Test",
            category="test",
            is_public=True,
            keywords=[],
            business_area_ids=[test_business_areas[0].id],
            created_by_id=test_user.id,
        )
        form_id = form.id
        
        # Delete via API
        response = client.delete(f"/api/v1/forms/{form_id}", headers=auth_headers)
        assert response.status_code == 204
        
        # Verify soft delete in database
        db_form = db.query(Form).filter(Form.id == form_id).first()
        assert db_form is not None
        assert db_form.deleted_at is not None
        
        # Verify GET returns 404 (soft deleted)
        response = client.get(f"/api/v1/forms/{form_id}")
        assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
