import pytest
from sqlalchemy.orm import Session
from backend.database import get_db, engine, Base
from backend.models import Role, FormNumberPrefix, BusinessArea

# Import all seeds
from backend.seeds.default_roles import seed_roles
from backend.seeds.default_prefixes import seed_prefixes
from backend.seeds.default_business_areas import seed_business_areas
from backend.seeds.seed_initial_admin import seed_admin

@pytest.fixture(scope="module")
def seeded_db():
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    yield db
    Base.metadata.drop_all(bind=engine)

class TestDatabaseSeeds:
    def test_seed_roles_creates_core_roles(self, seeded_db: Session):
        seed_roles(seeded_db)
        roles = seeded_db.query(Role).all()
        assert len(roles) >= 3
        role_codes = [r.code for r in roles]
        assert "admin" in role_codes
        assert "reviewer" in role_codes

    def test_seed_roles_idempotent(self, seeded_db: Session):
        # Running it twice shouldn't crash or duplicate system roles
        seed_roles(seeded_db)
        seed_roles(seeded_db)
        roles = seeded_db.query(Role).filter(Role.is_system == True).all()
        assert len(roles) == 3 # assuming admin, reviewer, staff_manager

    def test_seed_prefixes_successful(self, seeded_db: Session):
        seed_prefixes(seeded_db)
        prefixes = seeded_db.query(FormNumberPrefix).all()
        assert len(prefixes) > 0
        codes = [p.prefix for p in prefixes]
        assert "MV" in codes
        assert "CVCR" in codes 

    def test_seed_business_areas_successful(self, seeded_db: Session):
        seed_business_areas(seeded_db)
        areas = seeded_db.query(BusinessArea).all()
        assert len(areas) > 0
        names = [a.name for a in areas]
        assert "Commercial Vehicle Safety and Enforcement" in names

    def test_seed_initial_admin(self, seeded_db: Session):
        # Create a mock env var payload for the admin email
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"INITIAL_ADMIN_EMAIL": "test-admin@gov.bc.ca"}):
            # You might need to call seed_admin assuming it pulls from settings
            # We assume it just injects the initial admin config properly
            seed_admin(seeded_db, initial_email="test-admin@gov.bc.ca")
            
            # Note: Checking the admin users table in backend models.
            from backend.models import AdminUser
            admin = seeded_db.query(AdminUser).filter_by(email="test-admin@gov.bc.ca").first()
            assert admin is not None
            assert admin.is_active is True
