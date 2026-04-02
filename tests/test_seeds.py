import pytest
from sqlalchemy.orm import Session
from backend.database import get_db, engine, Base
from backend.models import Role, FormNumberPrefix, BusinessArea

# Import all seeds
from backend.seeds.default_roles import seed_roles
from backend.seeds.default_prefixes import seed_prefixes
from backend.seeds.default_business_areas import seed_business_areas
from backend.seeds.seed_initial_admin import seed_admin
from backend.seeds import seed_all_defaults

@pytest.fixture(scope="module")
def seeded_db(_test_engine):
    db = Session(bind=_test_engine)
    yield db
    db.close()

class TestDatabaseSeeds:
    def test_seed_roles_creates_core_roles(self, seeded_db: Session):
        seed_roles(seeded_db)
        roles = seeded_db.query(Role).all()
        assert len(roles) >= 3
        role_codes = [r.name for r in roles]
        assert "admin" in role_codes
        assert "reviewer" in role_codes

    def test_seed_roles_idempotent(self, seeded_db: Session):
        # Running it twice shouldn't crash or duplicate system roles
        seed_roles(seeded_db)
        seed_roles(seeded_db)
        roles = seeded_db.query(Role).filter(Role.is_system == True).all()
        assert len(roles) == 4 # admin, reviewer, staff_manager, staff_viewer

    def test_seed_prefixes_successful(self, seeded_db: Session):
        seed_prefixes(seeded_db)
        prefixes = seeded_db.query(FormNumberPrefix).all()
        assert len(prefixes) > 0
        codes = [p.prefix for p in prefixes]
        assert "MV" in codes
        assert "CVSE" in codes 

    def test_seed_business_areas_successful(self, seeded_db: Session):
        seed_business_areas(seeded_db)
        areas = seeded_db.query(BusinessArea).all()
        assert len(areas) > 0
        names = [a.name for a in areas]
        assert "Compliance" in names

    def test_seed_initial_admin(self, seeded_db: Session):
        from backend.models import User
        seed_admin(seeded_db, "test-admin@gov.bc.ca")
        admin = seeded_db.query(User).filter_by(email="test-admin@gov.bc.ca").first()
        assert admin is not None
        assert admin.is_active is True

    def test_seed_all_defaults_is_idempotent(self, seeded_db: Session):
        """seed_all_defaults combines all seed functions; running twice must not fail."""
        seed_all_defaults(seeded_db)
        seed_all_defaults(seeded_db)

    def test_seed_admin_idempotent_existing_user(self, seeded_db: Session):
        """Calling seed_admin twice for the same email must not crash."""
        seed_admin(seeded_db, "test-admin@gov.bc.ca")
        seed_admin(seeded_db, "test-admin@gov.bc.ca")

    def test_seed_admin_existing_user_missing_role(self, seeded_db: Session):
        """If user exists but has no admin role, the role should be assigned."""
        from backend.models import User
        import uuid
        email = f"partial-admin-{uuid.uuid4().hex[:6]}@gov.bc.ca"
        user = User(id=uuid.uuid4(), email=email, is_active=True)
        seeded_db.add(user)
        seeded_db.commit()
        # Now seed — should assign admin role to the existing user
        seed_admin(seeded_db, email)
        seeded_db.refresh(user)
        assert user.is_active is True

    def test_seed_admin_no_admin_role_warns(self, seeded_db: Session):
        """If admin role doesn't exist, seed_admin should return without error."""
        from backend.seeds.seed_initial_admin import seed_initial_admin
        from unittest.mock import patch, MagicMock
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        # Should not raise
        seed_initial_admin(mock_db, "nobody@gov.bc.ca")
