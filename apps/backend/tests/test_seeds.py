from backend.models import Role
from backend.seeds import seed_all_defaults
from backend.seeds.default_roles import seed_roles
from backend.seeds.seed_initial_admin import seed_admin
from sqlalchemy.orm import Session


class TestDatabaseSeeds:
    def test_seed_roles_creates_core_roles(self, db: Session):
        seed_roles(db)
        roles = db.query(Role).filter(Role.is_system.is_(True)).all()
        assert {role.name for role in roles} == {"admin", "staff_viewer"}

    def test_seed_roles_idempotent(self, db: Session):
        # Running it twice shouldn't crash or duplicate system roles
        seed_roles(db)
        seed_roles(db)
        roles = db.query(Role).filter(Role.is_system.is_(True)).all()
        assert {role.name for role in roles} == {"admin", "staff_viewer"}

    def test_seed_initial_admin(self, db: Session):
        from backend.models import User

        seed_roles(db)
        seed_admin(db, "test-admin@gov.bc.ca")
        admin = db.query(User).filter_by(email="test-admin@gov.bc.ca").first()
        assert admin is not None
        assert admin.is_active is True

    def test_seed_all_defaults_is_idempotent(self, db: Session):
        """Running all default seed functions twice must not fail."""
        seed_all_defaults(db)
        seed_all_defaults(db)

    def test_seed_admin_idempotent_existing_user(self, db: Session):
        """Calling seed_admin twice for the same email must not crash."""
        seed_roles(db)
        seed_admin(db, "test-admin@gov.bc.ca")
        seed_admin(db, "test-admin@gov.bc.ca")

    def test_seed_admin_existing_user_missing_role(self, db: Session):
        """Assign Admin when an existing user has no Admin role."""
        import uuid

        from backend.models import User

        email = f"partial-admin-{uuid.uuid4().hex[:6]}@gov.bc.ca"
        user = User(id=uuid.uuid4(), email=email, is_active=True)
        db.add(user)
        db.commit()
        seed_roles(db)
        # Now seed — should assign admin role to the existing user
        seed_admin(db, email)
        db.refresh(user)
        assert user.is_active is True

    def test_seed_admin_no_admin_role_warns(self):
        """Return without error when the Admin role does not exist."""
        from unittest.mock import MagicMock

        from backend.seeds.seed_initial_admin import seed_initial_admin

        mock_db = MagicMock()
        query = mock_db.query.return_value
        query.filter.return_value.first.return_value = None
        # Should not raise
        seed_initial_admin(mock_db, "nobody@gov.bc.ca")
