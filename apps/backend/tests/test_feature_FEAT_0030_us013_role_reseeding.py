from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from backend.auth.permissions import Permission
from backend.models import Role
from backend.seeds.default_roles import seed_default_roles
from sqlalchemy.exc import IntegrityError


def test_reseeding_preserves_existing_retained_role_configuration(db):
    seed_default_roles(db)
    admin_query = db.query(Role).filter(
        Role.name == "admin",
        Role.deleted_at.is_(None),
    )
    admin_role = admin_query.one()
    configured_permissions = [Permission.FORM_READ.value]
    admin_role.description = "Environment-managed administrator"
    admin_role.permissions = configured_permissions
    db.commit()

    result = seed_default_roles(db)
    db.refresh(admin_role)

    assert admin_role.description == "Environment-managed administrator"
    assert admin_role.permissions == configured_permissions
    assert result["created"] == 0
    assert result["updated"] == 0
    assert result["existing"] == 2


@pytest.mark.parametrize(
    ("is_system", "is_active"),
    [(False, True), (True, False)],
)
def test_reseeding_rejects_invalid_retained_role_identity(
    db,
    is_system,
    is_active,
):
    conflicting_role = Role(
        name="staff_viewer",
        description="Conflicting retained role",
        permissions=[Permission.FORM_READ.value],
        is_system=is_system,
        is_active=is_active,
    )
    db.add(conflicting_role)
    db.commit()

    with pytest.raises(RuntimeError, match="Default role seeding failed"):
        seed_default_roles(db)

    db.refresh(conflicting_role)
    assert conflicting_role.description == "Conflicting retained role"
    assert conflicting_role.permissions == [Permission.FORM_READ.value]
    assert conflicting_role.is_system is is_system
    assert conflicting_role.is_active is is_active
    assert db.query(Role).filter(Role.name == "admin").first() is None


def test_concurrent_retained_role_insert_is_treated_as_existing():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [
        None,
        None,
        SimpleNamespace(id=uuid4(), is_system=True, is_active=True),
        SimpleNamespace(id=uuid4(), is_system=True, is_active=True),
    ]
    db.commit.side_effect = [
        IntegrityError("INSERT INTO roles", {}, Exception("duplicate"))
    ]

    result = seed_default_roles(db)

    assert result["created"] == 0
    assert result["updated"] == 0
    assert result["existing"] == 2
    assert result["failed"] == 0
    assert db.rollback.call_count == 1


def test_concurrent_invalid_retained_role_insert_fails():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [
        None,
        None,
        SimpleNamespace(id=uuid4(), is_system=False, is_active=True),
        SimpleNamespace(id=uuid4(), is_system=True, is_active=True),
    ]
    db.commit.side_effect = [
        IntegrityError("INSERT INTO roles", {}, Exception("duplicate"))
    ]

    with pytest.raises(RuntimeError, match="Default role seeding failed"):
        seed_default_roles(db)

    assert db.rollback.call_count == 1


def test_rollback_failure_is_sanitized_without_retry():
    db = MagicMock()
    db.query.side_effect = IntegrityError(
        "SELECT roles",
        {},
        Exception("private-integrity-detail"),
    )
    db.rollback.side_effect = RuntimeError("private-rollback-detail")

    with pytest.raises(RuntimeError) as exc_info:
        seed_default_roles(db)

    assert str(exc_info.value) == "Default role seeding failed"
    assert db.query.call_count == 1
    db.rollback.assert_called_once_with()
