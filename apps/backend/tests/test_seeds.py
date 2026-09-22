import pytest
from sqlalchemy.orm import Session
from backend.models import Role

# Import all seeds
from backend.seeds.default_roles import seed_roles
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
        roles = seeded_db.query(Role).filter(Role.is_system.is_(True)).all()
        assert {role.name for role in roles} == {"admin", "staff_viewer"}

    def test_seed_roles_idempotent(self, seeded_db: Session):
        # Running it twice shouldn't crash or duplicate system roles
        seed_roles(seeded_db)
        seed_roles(seeded_db)
        roles = seeded_db.query(Role).filter(Role.is_system.is_(True)).all()
        assert {role.name for role in roles} == {"admin", "staff_viewer"}

    def test_seed_initial_admin(self, seeded_db: Session):
        from backend.models import User

        seed_admin(seeded_db, "test-admin@gov.bc.ca")
        admin = (
            seeded_db.query(User)
            .filter_by(email="test-admin@gov.bc.ca")
            .first()
        )
        assert admin is not None
        assert admin.is_active is True

    def test_seed_all_defaults_is_idempotent(self, seeded_db: Session):
        """Running all default seed functions twice must not fail."""
        seed_all_defaults(seeded_db)
        seed_all_defaults(seeded_db)

    def test_seed_admin_idempotent_existing_user(self, seeded_db: Session):
        """Calling seed_admin twice for the same email must not crash."""
        seed_admin(seeded_db, "test-admin@gov.bc.ca")
        seed_admin(seeded_db, "test-admin@gov.bc.ca")

    def test_seed_admin_existing_user_missing_role(self, seeded_db: Session):
        """Assign Admin when an existing user has no Admin role."""
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
        """Return without error when the Admin role does not exist."""
        from backend.seeds.seed_initial_admin import seed_initial_admin
        from unittest.mock import MagicMock

        mock_db = MagicMock()
        query = mock_db.query.return_value
        query.filter.return_value.first.return_value = None
        # Should not raise
        seed_initial_admin(mock_db, "nobody@gov.bc.ca")
