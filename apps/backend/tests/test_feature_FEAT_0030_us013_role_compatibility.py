import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from backend.auth.authorization import get_user_permissions, has_permission
from backend.auth.permissions import DEFAULT_ROLES, Permission
from backend import main as backend_main
from backend.seeds import seed_all_defaults
from backend.seeds.default_roles import seed_default_roles
from backend.routes.auth import map_keycloak_roles_to_local
from backend.services.roles import RoleService
from backend.services.forms import FormService, FormWorkflowValidationError


RETIRED_ROLE_NAMES = {"content_editor", "reviewer", "staff_manager"}


def _db_with_custom_role(permissions):
    db = MagicMock()
    role = SimpleNamespace(
        name="custom_capability_role",
        is_active=True,
        deleted_at=None,
        permissions=permissions,
    )
    assignment = SimpleNamespace(role=role)
    query = db.query.return_value.filter.return_value
    query.first.return_value = SimpleNamespace(id=uuid4(), is_active=True)
    query.all.return_value = [assignment]
    return db


def test_default_role_catalogue_contains_only_retained_roles():
    assert set(DEFAULT_ROLES) == {"admin", "staff_viewer"}


def test_retained_role_permissions_match_pre_us013_contract():
    admin_permissions = {
        permission.value
        for permission in DEFAULT_ROLES["admin"]["permissions"]
    }
    viewer_permissions = {
        permission.value
        for permission in DEFAULT_ROLES["staff_viewer"]["permissions"]
    }

    assert admin_permissions == {permission.value for permission in Permission}
    assert viewer_permissions == {
        Permission.FORM_READ.value,
        Permission.BUSINESS_AREA_READ.value,
        Permission.CATEGORY_READ.value,
    }


@pytest.mark.asyncio
async def test_startup_role_failure_logs_type_without_exception_details(
    monkeypatch,
):
    sentinel = "private-database-detail-must-not-be-logged"
    logger = MagicMock()

    def fail_role_seed(_db):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(backend_main, "logger", logger)
    monkeypatch.setattr("backend.database.SessionLocal", MagicMock())
    monkeypatch.setattr(
        "backend.seeds.default_roles.seed_default_roles",
        fail_role_seed,
    )
    monkeypatch.setattr(
        "backend.services.s3_service.ensure_bucket_exists",
        MagicMock(),
    )

    with pytest.raises(RuntimeError, match=sentinel):
        async with backend_main.lifespan(MagicMock()):
            pass

    role_failure_calls = [
        call
        for call in logger.warning.call_args_list
        if call.args == ("default_roles_seed_failed",)
    ]
    assert len(role_failure_calls) == 1
    assert role_failure_calls[0].kwargs == {"error_type": "RuntimeError"}
    assert sentinel not in repr(logger.mock_calls)


@pytest.mark.asyncio
async def test_startup_rejects_reported_role_seed_failure(monkeypatch):
    logger = MagicMock()
    ensure_bucket = MagicMock()

    monkeypatch.setattr(backend_main, "logger", logger)
    monkeypatch.setattr("backend.database.SessionLocal", MagicMock())
    monkeypatch.setattr(
        "backend.seeds.default_roles.seed_default_roles",
        MagicMock(return_value={"failed": 1}),
    )
    monkeypatch.setattr(
        "backend.services.s3_service.ensure_bucket_exists",
        ensure_bucket,
    )

    with pytest.raises(RuntimeError, match="Default role seeding failed"):
        async with backend_main.lifespan(MagicMock()):
            pass

    logger.info.assert_not_called()
    logger.warning.assert_called_once_with(
        "default_roles_seed_failed",
        error_type="RuntimeError",
    )
    ensure_bucket.assert_not_called()


def test_aggregate_seeding_rejects_reported_role_failure(monkeypatch):
    seed_demo_user = MagicMock()

    monkeypatch.setattr(
        "backend.seeds.seed_default_roles",
        MagicMock(return_value={"failed": 1}),
    )
    monkeypatch.setattr(
        "backend.seeds.seed_demo_user",
        seed_demo_user,
    )

    with pytest.raises(RuntimeError, match="Default role seeding failed"):
        seed_all_defaults(MagicMock())

    seed_demo_user.assert_not_called()


def test_role_seeder_raises_sanitized_error_after_database_failure():
    db = MagicMock()
    db.query.side_effect = RuntimeError("private-database-detail")

    with pytest.raises(RuntimeError) as exc_info:
        seed_default_roles(db)

    assert str(exc_info.value) == "Default role seeding failed"
    assert "private-database-detail" not in str(exc_info.value)
    assert db.rollback.call_count == len(DEFAULT_ROLES)


@pytest.mark.parametrize(
    "external_role",
    ["content_editor", "reviewer", "staff_manager", "manager", "approver"],
)
def test_retired_external_roles_have_no_local_mapping(external_role):
    assert map_keycloak_roles_to_local([external_role]) == []


def test_retained_external_role_mappings_are_unchanged():
    assert map_keycloak_roles_to_local(
        ["ADMIN", "administrator", "staff_viewer", "viewer"]
    ) == ["admin", "staff_viewer"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "permission",
    [
        Permission.CMS_MANAGE.value,
        Permission.FORM_APPROVE.value,
        Permission.RESERVATION_APPROVE.value,
    ],
)
async def test_neutral_custom_role_allows_only_explicit_permission(permission):
    db = _db_with_custom_role([permission])

    assert await has_permission(str(uuid4()), permission, db) is True
    assert (
        await has_permission(str(uuid4()), Permission.ROLE_CREATE.value, db)
        is False
    )


@pytest.mark.asyncio
async def test_missing_role_assignment_denies_all_permissions():
    db = _db_with_custom_role([])
    db.query.return_value.filter.return_value.all.return_value = []

    assert await get_user_permissions(str(uuid4()), db) == set()
    assert (
        await has_permission(str(uuid4()), Permission.FORM_APPROVE.value, db)
        is False
    )


def test_custom_role_permission_does_not_bypass_self_approval(monkeypatch):
    user_id = uuid4()
    form = SimpleNamespace(created_by_id=user_id)
    monkeypatch.setattr(
        FormService,
        "_get_form_for_transition",
        MagicMock(return_value=form),
    )

    with pytest.raises(
        FormWorkflowValidationError,
        match="cannot approve your own",
    ):
        FormService.approve_form(MagicMock(), uuid4(), user_id)


def test_retired_names_are_not_reserved_system_role_names():
    assert RoleService.SYSTEM_ROLE_NAMES == {"admin", "staff_viewer"}
    assert RETIRED_ROLE_NAMES.isdisjoint(RoleService.SYSTEM_ROLE_NAMES)


def test_runtime_modules_do_not_depend_on_retired_role_names():
    backend_root = Path(__file__).resolve().parents[1]
    excluded_parts = {"alembic", "tests", "__pycache__"}
    runtime_sources = [
        path
        for path in backend_root.rglob("*.py")
        if excluded_parts.isdisjoint(path.relative_to(backend_root).parts)
    ]

    matches = {}
    for path in runtime_sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(
                node,
                (
                    ast.Module,
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                ),
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        executable_strings = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        }
        retired_matches = sorted(
            retired_name
            for retired_name in RETIRED_ROLE_NAMES
            if any(retired_name in value for value in executable_strings)
        )
        if retired_matches:
            matches[str(path.relative_to(backend_root))] = retired_matches

    assert matches == {}


def test_alembic_revisions_do_not_seed_retired_roles():
    versions_dir = (
        Path(__file__).resolve().parents[1] / "alembic" / "versions"
    )
    matches = {}

    for path in versions_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        executable_strings = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
        }
        retired_matches = sorted(
            retired_name
            for retired_name in RETIRED_ROLE_NAMES
            if any(retired_name in value for value in executable_strings)
        )
        if retired_matches:
            matches[path.name] = retired_matches

    assert matches == {}
