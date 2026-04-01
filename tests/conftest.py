"""Shared test fixtures for the Transportation Forms test suite.

Uses a real PostgreSQL database (the only approved database) for all tests.
Each test function runs inside a SAVEPOINT-based transaction that is rolled
back after the test, providing fast isolation while exercising real
PostgreSQL behaviour (partial unique indexes, check constraints, etc.).

Requires a running PostgreSQL instance.  By default the connection string
is read from the ``TEST_DATABASE_URL`` environment variable; the fallback
points at the Rancher Desktop Compose service on port 5432.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.database import Base
from backend.models import (
    AuditLog,
    BusinessArea,
    Form,
    FormNumberPrefix,
    FormNumberReservation,
    FormReservationApprover,
    Role,
    User,
    UserRole,
)
from backend.auth.jwt_handler import TokenData


# ---------------------------------------------------------------------------
# PostgreSQL test database setup
# ---------------------------------------------------------------------------

# Connection to the *admin* database used to CREATE/DROP the test database.
# Locally: read from the .env file (PG_ADMIN_URL) or falls back to port 5432.
# CI: set PG_ADMIN_URL via GitHub Actions env block.
_PG_ADMIN_URL = os.getenv(
    "PG_ADMIN_URL",
    "postgresql://transportation:password@localhost:5432/postgres",
)

# Connection to the dedicated *test* database.
# Locally: read from the .env file (TEST_DATABASE_URL) or falls back to port 5432.
# CI: set TEST_DATABASE_URL via GitHub Actions env block.
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://transportation:password@localhost:5432/transportation_forms_test",
)

_TEST_DB_NAME = TEST_DATABASE_URL.rsplit("/", 1)[-1]


@pytest.fixture(scope="session")
def _test_engine():
    """Create the test database (if needed) and return an engine bound to it.

    The database is created once per test session and the full schema is
    applied via ``Base.metadata.create_all``.
    """
    # Connect to the admin database to create the test database.
    admin_engine = create_engine(_PG_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": _TEST_DB_NAME},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{_TEST_DB_NAME}"'))
    admin_engine.dispose()

    # Build the engine for the test database.
    engine = create_engine(TEST_DATABASE_URL, echo=False)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def _session_factory(_test_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)


# ---------------------------------------------------------------------------
# Per-test transactional isolation
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(_test_engine, _session_factory) -> Generator[Session, None, None]:
    """Provide a PostgreSQL session wrapped in a SAVEPOINT.

    The outer transaction is rolled back after every test so that each test
    starts with a clean database.  Service code that calls
    ``session.commit()`` is transparently converted into a nested
    SAVEPOINT release, keeping the outer transaction intact.
    """
    connection = _test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="conditional_savepoint")

    # Nested transactions via SAVEPOINT so SUT commits work as expected.
    session.begin_nested()

    # Re-open a SAVEPOINT after every ``session.commit()`` call so the
    # outer transaction is never actually committed.
    from sqlalchemy import event

    @event.listens_for(session, "after_transaction_end")
    def _restart(session, transaction_):
        if transaction_.nested and not transaction_.parent.nested:
            session.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Reusable entity factories
# ---------------------------------------------------------------------------

@pytest.fixture()
def user_factory(db: Session):
    """Factory to create and persist a User."""

    def _create(
        *,
        email: str | None = None,
        first_name: str = "Test",
        last_name: str = "User",
        is_active: bool = True,
    ) -> User:
        user = User(
            id=uuid.uuid4(),
            email=email or f"{uuid.uuid4().hex[:8]}@example.com",
            first_name=first_name,
            last_name=last_name,
            is_active=is_active,
        )
        db.add(user)
        db.flush()
        return user

    return _create


@pytest.fixture()
def role_factory(db: Session):
    """Factory to create and persist a Role."""

    def _create(
        *,
        name: str = "staff",
        permissions: dict | None = None,
        is_system: bool = False,
        is_active: bool = True,
    ) -> Role:
        role = Role(
            id=uuid.uuid4(),
            name=name,
            permissions=permissions or {},
            is_system=is_system,
            is_active=is_active,
        )
        db.add(role)
        db.flush()
        return role

    return _create


@pytest.fixture()
def prefix_factory(db: Session):
    """Factory to create and persist a FormNumberPrefix."""

    def _create(
        *,
        prefix: str = "H",
        description: str | None = "Test prefix",
        current_sequence: int = 0,
        padding_length: int = 4,
        max_number_length: int = 10,
        is_case_sensitive: bool = False,
        is_active: bool = True,
        created_by: User | None = None,
    ) -> FormNumberPrefix:
        obj = FormNumberPrefix(
            id=uuid.uuid4(),
            prefix=prefix,
            description=description,
            current_sequence=current_sequence,
            padding_length=padding_length,
            max_number_length=max_number_length,
            is_case_sensitive=is_case_sensitive,
            is_active=is_active,
            created_by_id=created_by.id if created_by else None,
        )
        db.add(obj)
        db.flush()
        return obj

    return _create


@pytest.fixture()
def reservation_factory(db: Session):
    """Factory to create and persist a FormNumberReservation."""

    def _create(
        *,
        prefix: FormNumberPrefix,
        form_number: str = "0001",
        full_form_number: str | None = None,
        numbering_method: str = "auto_generated",
        custom_number_reason: str | None = None,
        status: str = "reserved",
        reserved_by: User,
        expires_at: datetime | None = None,
        released_at: datetime | None = None,
        released_by: User | None = None,
        created_at: datetime | None = None,
    ) -> FormNumberReservation:
        if full_form_number is None:
            full_form_number = f"{prefix.prefix}{form_number}"
        if expires_at is None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=14)
        obj = FormNumberReservation(
            id=uuid.uuid4(),
            prefix_id=prefix.id,
            form_number=form_number,
            full_form_number=full_form_number,
            numbering_method=numbering_method,
            custom_number_reason=custom_number_reason,
            status=status,
            reserved_by_id=reserved_by.id,
            expires_at=expires_at,
            released_at=released_at,
            released_by_id=released_by.id if released_by else None,
        )
        db.add(obj)
        # Override created_at if requested (for expiry tests)
        if created_at is not None:
            db.flush()
            obj.created_at = created_at  # type: ignore[assignment]
        db.flush()
        return obj

    return _create


# ---------------------------------------------------------------------------
# Common pre-built fixtures (user + prefix ready to use)
# ---------------------------------------------------------------------------

@pytest.fixture()
def staff_user(user_factory, role_factory, db: Session) -> User:
    """A basic staff user with the 'staff' role."""
    user = user_factory(email="staff@example.com", first_name="Staff", last_name="Member")
    role = role_factory(name="staff")
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
    db.flush()
    return user


@pytest.fixture()
def approver_user(user_factory, role_factory, db: Session) -> User:
    """A reviewer user with the 'reviewer' role (approver-eligible)."""
    user = user_factory(email="approver@example.com", first_name="Approver", last_name="One")
    role = role_factory(name="reviewer")
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
    db.flush()
    return user


@pytest.fixture()
def admin_user(user_factory, role_factory, db: Session) -> User:
    """An admin user with the 'admin' role."""
    user = user_factory(email="admin@example.com", first_name="Admin", last_name="Boss")
    role = role_factory(name="admin")
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
    db.flush()
    return user


@pytest.fixture()
def active_prefix(prefix_factory) -> FormNumberPrefix:
    """An active prefix 'H' ready to use."""
    return prefix_factory(prefix="H", padding_length=4, max_number_length=10)


# ---------------------------------------------------------------------------
# FastAPI TestClient helpers
# ---------------------------------------------------------------------------

def make_token_data(
    user: User,
    roles: list[str] | None = None,
) -> TokenData:
    """Build a ``TokenData`` from a User ORM object (for dependency overrides)."""
    return TokenData(
        sub=str(user.id),
        email=user.email,
        name=f"{user.first_name} {user.last_name}",
        roles=roles or ["staff"],
        token_type="access",
    )
