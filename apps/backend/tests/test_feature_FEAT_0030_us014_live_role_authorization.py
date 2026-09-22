"""Live role authorization tests for FEAT-0030 US-014."""

import ast
from datetime import datetime, timezone
from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import AuditLog, Form, Role, UserRole
from sqlalchemy.exc import SQLAlchemyError


def _assign_role(
    db, user, name: str, permissions: list[str]
) -> tuple[Role, UserRole]:
    role = Role(
        id=uuid.uuid4(),
        name=name,
        permissions=permissions,
        is_system=False,
        is_active=True,
    )
    db.add(role)
    db.flush()
    membership = UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id)
    db.add(membership)
    db.flush()
    return role, membership


def _client(
    db,
    user,
    *,
    token_roles: list[str],
    token_permissions: list[str],
) -> TestClient:
    token = TokenData(
        sub=str(user.id),
        email=str(user.email),
        name="FEAT-0030 US-014 Test",
        roles=token_roles,
        token_type="access",
        permissions=token_permissions,
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: token
    return TestClient(app)


def _commit_authorization_change(db) -> None:
    db.commit()
    db.expire_all()


def _revoke_membership(db, membership: UserRole) -> None:
    membership.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    _commit_authorization_change(db)


def _assert_generic_denial(response) -> None:
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Insufficient permissions for this action"
    }


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def test_roles_list_uses_live_role_read_not_token_claims(
    db, user_factory
) -> None:
    user = user_factory(email="us014-live-role-read@example.com")
    _assign_role(db, user, "custom_role_reader", ["role:read"])
    client = _client(
        db,
        user,
        token_roles=["staff_viewer"],
        token_permissions=["form:read"],
    )

    response = client.get("/api/v1/admin/roles")

    assert response.status_code == 200
    assert response.json()["total"] == 1


@pytest.mark.parametrize(
    ("method", "path", "permissions", "payload", "allowed_status"),
    (
        ("get", "/api/v1/admin/roles", ["role:read"], None, 200),
        (
            "get",
            f"/api/v1/admin/roles/{uuid.uuid4()}",
            ["role:read"],
            None,
            404,
        ),
        (
            "post",
            "/api/v1/admin/roles",
            ["role:create"],
            {
                "name": "us014_created_role",
                "description": "US-014 route inventory",
                "permissions": ["form:read"],
            },
            201,
        ),
        (
            "put",
            f"/api/v1/admin/roles/{uuid.uuid4()}",
            ["role:edit"],
            {
                "name": "us014_updated_role",
                "description": "US-014 route inventory",
                "permissions": ["form:read"],
            },
            404,
        ),
        (
            "delete",
            f"/api/v1/admin/roles/{uuid.uuid4()}",
            ["role:delete"],
            None,
            404,
        ),
        ("get", "/api/v1/admin/users", ["user:manage_roles"], None, 200),
        (
            "get",
            f"/api/v1/admin/users/{uuid.uuid4()}",
            ["user:manage_roles"],
            None,
            404,
        ),
        (
            "put",
            f"/api/v1/admin/users/{uuid.uuid4()}/roles",
            ["user:manage_roles"],
            {"role_ids": []},
            404,
        ),
        (
            "get",
            "/api/v1/admin/access-requests",
            ["user:manage_roles"],
            None,
            200,
        ),
        (
            "post",
            f"/api/v1/admin/access-requests/{uuid.uuid4()}/approve",
            ["user:manage_roles"],
            {"review_notes": "US-014 inventory"},
            404,
        ),
        (
            "post",
            f"/api/v1/admin/access-requests/{uuid.uuid4()}/reject",
            ["user:manage_roles"],
            {"review_notes": "US-014 inventory"},
            404,
        ),
        ("get", "/api/v1/forms?limit=24", ["form:read"], None, 200),
        (
            "get",
            "/api/v1/forms/autocomplete?q=missing",
            ["form:read"],
            None,
            200,
        ),
        ("get", f"/api/v1/forms/{uuid.uuid4()}", ["form:read"], None, 404),
        (
            "get",
            f"/api/v1/forms/{uuid.uuid4()}/file",
            ["form:read"],
            None,
            404,
        ),
        (
            "delete",
            f"/api/v1/forms/{uuid.uuid4()}",
            ["form:delete"],
            None,
            404,
        ),
        (
            "get",
            "/api/v1/staff/forms/pending-approvals",
            ["form:approve", "form:review"],
            None,
            200,
        ),
        (
            "post",
            f"/api/v1/staff/forms/{uuid.uuid4()}/submit",
            ["form:submit_for_review"],
            None,
            404,
        ),
        (
            "post",
            f"/api/v1/staff/forms/{uuid.uuid4()}/approve",
            ["form:approve", "form:review"],
            None,
            404,
        ),
        (
            "post",
            f"/api/v1/staff/forms/{uuid.uuid4()}/reject",
            ["form:approve", "form:review"],
            {"reason_notes": "US-014 inventory"},
            404,
        ),
        (
            "post",
            f"/api/v1/staff/forms/{uuid.uuid4()}/publish",
            ["form:approve", "form:review"],
            None,
            404,
        ),
        (
            "post",
            f"/api/v1/staff/forms/{uuid.uuid4()}/unpublish",
            ["form:approve"],
            None,
            404,
        ),
        (
            "post",
            f"/api/v1/staff/forms/{uuid.uuid4()}/revert",
            ["form:create", "form:edit"],
            {"reason_notes": "US-014 inventory"},
            404,
        ),
        (
            "post",
            f"/api/v1/staff/forms/{uuid.uuid4()}/archive",
            ["form:archive"],
            None,
            404,
        ),
        (
            "post",
            f"/api/v1/staff/forms/{uuid.uuid4()}/restore",
            ["form:approve"],
            None,
            404,
        ),
        (
            "get",
            f"/api/v1/staff/forms/{uuid.uuid4()}/workflow-history",
            ["form:review"],
            None,
            404,
        ),
    ),
)
def test_protected_route_inventory_uses_live_grants_and_revocations(
    db,
    user_factory,
    method: str,
    path: str,
    permissions: list[str],
    payload: dict | None,
    allowed_status: int,
) -> None:
    user = user_factory(
        email=f"us014-inventory-{uuid.uuid4().hex}@example.com"
    )
    _, membership = _assign_role(
        db, user, f"us014_inventory_{uuid.uuid4().hex}", permissions
    )
    _commit_authorization_change(db)
    client = _client(
        db,
        user,
        token_roles=["admin"],
        token_permissions=permissions,
    )

    allowed = client.request(method, path, json=payload)

    assert allowed.status_code == allowed_status

    membership = db.get(UserRole, membership.id)
    assert membership is not None
    _revoke_membership(db, membership)

    denied = client.request(method, path, json=payload)

    _assert_generic_denial(denied)


def test_same_session_identity_and_identified_lists_follow_live_roles(
    db, user_factory
) -> None:
    user = user_factory(email="us014-same-session@example.com")
    client = _client(
        db,
        user,
        token_roles=["staff_viewer"],
        token_permissions=["form:read"],
    )
    permissions = [
        "role:read",
        "user:manage_roles",
        "form:approve",
        "form:review",
    ]
    _, membership = _assign_role(db, user, "us014_live_operator", permissions)
    _commit_authorization_change(db)

    identity = client.get("/api/v1/auth/me")
    responses = [
        client.get("/api/v1/admin/roles"),
        client.get("/api/v1/admin/users"),
        client.get("/api/v1/admin/access-requests"),
        client.get("/api/v1/staff/forms/pending-approvals"),
    ]

    assert identity.status_code == 200
    assert identity.json()["roles"] == ["us014_live_operator"]
    assert set(identity.json()["permissions"]) == {*permissions, "user:read"}
    assert all(response.status_code == 200 for response in responses)

    membership = db.get(UserRole, membership.id)
    assert membership is not None
    _revoke_membership(db, membership)

    revoked_identity = client.get("/api/v1/auth/me")
    assert revoked_identity.status_code == 200
    assert revoked_identity.json()["roles"] == []
    assert revoked_identity.json()["permissions"] == []
    for response in (
        client.get("/api/v1/admin/roles"),
        client.get("/api/v1/admin/users"),
        client.get("/api/v1/admin/access-requests"),
        client.get("/api/v1/staff/forms/pending-approvals"),
    ):
        _assert_generic_denial(response)


def test_multiple_current_roles_combine_for_all_permission_requirement(
    db, user_factory
) -> None:
    user = user_factory(email="us014-additive@example.com")
    _assign_role(db, user, "us014_approver", ["form:approve"])
    _, review_membership = _assign_role(
        db, user, "us014_reviewer", ["form:review"]
    )
    _commit_authorization_change(db)
    client = _client(db, user, token_roles=[], token_permissions=[])

    allowed = client.get("/api/v1/staff/forms/pending-approvals")
    assert allowed.status_code == 200

    review_membership = db.get(UserRole, review_membership.id)
    assert review_membership is not None
    _revoke_membership(db, review_membership)
    _assert_generic_denial(
        client.get("/api/v1/staff/forms/pending-approvals")
    )


@pytest.mark.parametrize(
    "excluded_record",
    (
        "inactive_user",
        "deleted_user",
        "inactive_role",
        "deleted_role",
        "deleted_assignment",
    ),
)
def test_inactive_or_deleted_authorization_records_fail_closed(
    db,
    user_factory,
    excluded_record: str,
) -> None:
    user = user_factory(email=f"us014-{excluded_record}@example.com")
    role, membership = _assign_role(
        db, user, f"us014_{excluded_record}", ["role:read", "role:create"]
    )
    if excluded_record == "inactive_user":
        user.is_active = False
    elif excluded_record == "deleted_user":
        user.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    elif excluded_record == "inactive_role":
        role.is_active = False
    elif excluded_record == "deleted_role":
        role.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        membership.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    _commit_authorization_change(db)
    client = _client(
        db,
        user,
        token_roles=["admin"],
        token_permissions=["role:read", "role:create"],
    )

    _assert_generic_denial(client.get("/api/v1/admin/roles"))
    response = client.post(
        "/api/v1/admin/roles",
        json={
            "name": f"must_not_exist_{excluded_record}",
            "permissions": ["form:read"],
        },
    )
    _assert_generic_denial(response)
    assert (
        db.query(Role)
        .filter(Role.name == f"must_not_exist_{excluded_record}")
        .first()
        is None
    )


def test_self_approval_uses_current_optional_permission(
    db, user_factory
) -> None:
    user = user_factory(email="us014-self-approval@example.com")
    _assign_role(db, user, "us014_approver", ["form:approve", "form:review"])
    form = Form(
        id=uuid.uuid4(),
        title="US-014 self approval",
        description="Must remain pending without a live optional permission",
        status="pending_review",
        is_public=False,
        keywords=[],
        created_by_id=user.id,
        collects_personal_info="No",
    )
    db.add(form)
    _commit_authorization_change(db)
    client = _client(
        db,
        user,
        token_roles=["admin"],
        token_permissions=["form:approve", "form:review", "form:approve-self"],
    )

    response = client.post(f"/api/v1/staff/forms/{form.id}/approve")

    assert response.status_code == 400
    db.refresh(form)
    assert form.status == "pending_review"

    _assign_role(db, user, "us014_self_approver", ["form:approve-self"])
    _commit_authorization_change(db)

    allowed = client.post(f"/api/v1/staff/forms/{form.id}/approve")

    assert allowed.status_code == 200
    assert allowed.json()["status"] == "published"


def test_form_delete_ownership_bypass_uses_current_role(
    db, user_factory
) -> None:
    owner = user_factory(email="us014-delete-owner@example.com")
    actor = user_factory(email="us014-delete-actor@example.com")
    _assign_role(db, actor, "us014_deleter", ["form:delete"])
    form = Form(
        id=uuid.uuid4(),
        title="US-014 protected draft",
        description="Cross-owner delete requires a current admin role",
        status="draft",
        is_public=False,
        keywords=[],
        created_by_id=owner.id,
        collects_personal_info="No",
    )
    db.add(form)
    _commit_authorization_change(db)
    client = _client(
        db,
        actor,
        token_roles=["admin"],
        token_permissions=["form:delete"],
    )

    denied = client.delete(f"/api/v1/forms/{form.id}")

    assert denied.status_code == 403
    db.refresh(form)
    assert form.deleted_at is None

    custom_admin, _ = _assign_role(db, actor, "admin", ["form:delete"])
    _commit_authorization_change(db)

    custom_admin_denied = client.delete(f"/api/v1/forms/{form.id}")

    assert custom_admin_denied.status_code == 403
    db.refresh(form)
    assert form.deleted_at is None

    custom_admin = db.get(Role, custom_admin.id)
    assert custom_admin is not None
    custom_admin.is_system = True
    _commit_authorization_change(db)

    allowed = client.delete(f"/api/v1/forms/{form.id}")

    assert allowed.status_code == 204


def test_authorization_resolution_failure_is_generic_and_non_mutating(
    db, user_factory, monkeypatch
) -> None:
    user = user_factory(email="us014-resolution-failure@example.com")
    _assign_role(db, user, "us014_role_creator", ["role:create"])
    _commit_authorization_change(db)
    client = _client(
        db,
        user,
        token_roles=["admin"],
        token_permissions=["role:create"],
    )

    def _fail_query(*_args, **_kwargs):
        raise SQLAlchemyError("sensitive database detail")

    rollback_calls = []
    with monkeypatch.context() as authorization_failure:
        authorization_failure.setattr(db, "query", _fail_query)
        authorization_failure.setattr(
            db, "rollback", lambda: rollback_calls.append(True)
        )
        response = client.post(
            "/api/v1/admin/roles",
            json={
                "name": "must_not_exist_after_failure",
                "permissions": ["form:read"],
            },
        )

    _assert_generic_denial(response)
    assert rollback_calls
    assert "sensitive database detail" not in response.text
    assert (
        db.query(Role)
        .filter(Role.name == "must_not_exist_after_failure")
        .first()
        is None
    )


@pytest.mark.parametrize(
    "authentication_failure", ("missing", "invalid", "expired")
)
def test_authentication_failure_precedes_live_authorization(
    authentication_failure: str, monkeypatch
) -> None:
    from backend.auth.jwt_handler import jwt_handler

    client = TestClient(app)
    headers = {}
    if authentication_failure != "missing":
        headers = {"Authorization": "Bearer unusable-token"}
        if authentication_failure == "invalid":
            monkeypatch.setattr(
                jwt_handler,
                "validate_token",
                lambda *_args, **_kwargs: None,
            )
        else:
            def _expired(*_args, **_kwargs):
                raise ValueError("Token has expired")

            monkeypatch.setattr(jwt_handler, "validate_token", _expired)

    try:
        response = client.get("/api/v1/admin/roles", headers=headers)
    finally:
        client.close()

    assert response.status_code in {401, 403}
    assert response.status_code != 500
    assert "Insufficient permissions for this action" not in response.text


def test_permission_check_audit_uses_live_outcome(db, user_factory) -> None:
    user = user_factory(email="us014-audit@example.com")
    _, membership = _assign_role(
        db, user, "us014_user_manager", ["user:manage_roles"]
    )
    _commit_authorization_change(db)
    client = _client(
        db,
        user,
        token_roles=["staff_viewer"],
        token_permissions=[],
    )

    assert client.get("/api/v1/admin/users").status_code == 200
    membership = db.get(UserRole, membership.id)
    assert membership is not None
    _revoke_membership(db, membership)
    _assert_generic_denial(client.get("/api/v1/admin/users"))

    outcomes = [
        row.new_values["allowed"]
        for row in db.query(AuditLog)
        .filter(
            AuditLog.user_id == user.id,
            AuditLog.action == "permission_check",
            AuditLog.entity_id == "user:manage_roles",
        )
        .order_by(AuditLog.created_at.asc())
        .all()
    ]
    assert outcomes == [True, False]


def test_role_assignment_audit_behavior_is_unchanged(db, user_factory) -> None:
    actor = user_factory(email="us014-role-audit-actor@example.com")
    target = user_factory(email="us014-role-audit-target@example.com")
    _assign_role(db, actor, "us014_role_manager", ["user:manage_roles"])
    target_role, _ = _assign_role(
        db, target, "us014_initial_role", ["form:read"]
    )
    replacement_role = Role(
        id=uuid.uuid4(),
        name="us014_replacement_role",
        permissions=["form:review"],
        is_system=False,
        is_active=True,
    )
    db.add(replacement_role)
    _commit_authorization_change(db)
    client = _client(db, actor, token_roles=[], token_permissions=[])

    response = client.put(
        f"/api/v1/admin/users/{target.id}/roles",
        json={"role_ids": [str(replacement_role.id)]},
    )

    assert response.status_code == 200
    audit = (
        db.query(AuditLog)
        .filter(
            AuditLog.user_id == actor.id,
            AuditLog.entity_type == "users",
            AuditLog.entity_id == str(target.id),
            AuditLog.action == "UPDATE_ROLES",
        )
        .one()
    )
    assert audit.old_values == {"role_ids": [str(target_role.id)]}
    assert audit.new_values == {"role_ids": [str(replacement_role.id)]}


def test_route_source_inventory_contains_no_token_claim_authorization(
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    violations: list[str] = []
    for path in sorted((backend_dir / "routes").glob("*.py")):
        tree = ast.parse(
            path.read_text(encoding="utf-8"), filename=str(path)
        )
        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            token_parameters = {
                argument.arg
                for argument in function.args.args
                if isinstance(argument.annotation, ast.Name)
                and argument.annotation.id == "TokenData"
            }
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr in {"roles", "permissions"}
                    and isinstance(node.value, ast.Name)
                    and node.value.id in token_parameters
                ):
                    claim = f"{node.value.id}.{node.attr}"
                    violations.append(
                        f"{path.name}:{function.name}:{claim}"
                    )

    dependency_path = backend_dir / "auth" / "dependencies.py"
    dependency_source = dependency_path.read_text(encoding="utf-8")
    authorization_path = backend_dir / "auth" / "authorization.py"
    authorization_source = authorization_path.read_text(encoding="utf-8")

    assert violations == []
    assert "def require_admin(" not in dependency_source
    assert "async def is_admin(" not in authorization_source
