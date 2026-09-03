"""Successful granular reservation permission flows for FEAT-0030 US-007."""

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi.testclient import TestClient

from backend.auth.dependencies import get_current_user
from backend.auth.jwt_handler import TokenData
from backend.database import get_db
from backend.main import app
from backend.models import FormNumberPrefix, FormNumberReservation, Role, UserRole


def _assign_role(db, user, name: str, permissions: list[str]) -> TokenData:
    role = Role(
        id=uuid.uuid4(),
        name=name,
        permissions=permissions,
        is_system=False,
        is_active=True,
    )
    db.add(role)
    db.flush()
    db.add(UserRole(id=uuid.uuid4(), user_id=user.id, role_id=role.id))
    db.flush()
    return TokenData(
        sub=str(user.id),
        email=str(user.email),
        name=name,
        roles=[name],
        token_type="access",
        permissions=permissions,
    )


def _request_as(client: TestClient, token: TokenData, method: str, path: str, **kwargs):
    app.dependency_overrides[get_current_user] = lambda: token
    return client.request(method, path, **kwargs)


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def test_custom_roles_complete_granular_reservation_workflows(
    db, user_factory
) -> None:
    requester = user_factory(email="custom-requester-feat0030@example.com")
    approver = user_factory(email="custom-approver-feat0030@example.com")
    operator = user_factory(email="custom-operator-feat0030@example.com")
    requester_token = _assign_role(
        db,
        requester,
        "custom_reservation_requester",
        [
            "reservation:create",
            "reservation:read",
            "reservation:submit",
            "reservation:release",
        ],
    )
    approver_token = _assign_role(
        db,
        approver,
        "custom_reservation_decider",
        [
            "reservation:read",
            "reservation:approve",
            "reservation:reject",
            "reservation:request_changes",
        ],
    )
    operator_token = _assign_role(
        db,
        operator,
        "custom_reservation_operator",
        ["reservation:read", "reservation:admin"],
    )
    prefix = FormNumberPrefix(
        id=uuid.uuid4(),
        prefix="CST",
        current_sequence=0,
        padding_length=4,
        max_number_length=12,
        is_case_sensitive=False,
        is_active=True,
    )
    db.add(prefix)
    db.flush()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    def generate() -> str:
        response = _request_as(
            client,
            requester_token,
            "post",
            "/api/v1/reservations/generate",
            json={"prefix_id": str(prefix.id)},
        )
        assert response.status_code == 201, response.text
        reservation_id = response.json()["id"]
        assert db.get(FormNumberReservation, uuid.UUID(reservation_id)).status == "reserved"
        return reservation_id

    approved_id = generate()
    submit_response = _request_as(
        client,
        requester_token,
        "post",
        f"/api/v1/reservations/{approved_id}/submit",
    )
    assert submit_response.status_code == 200
    assert submit_response.json()["status"] == "pending_approval"
    approve_response = _request_as(
        client,
        approver_token,
        "post",
        f"/api/v1/reservations/{approved_id}/approve",
    )
    assert approve_response.status_code == 200
    assert db.get(FormNumberReservation, uuid.UUID(approved_id)).status == "approved"

    changes_id = generate()
    assert _request_as(
        client,
        requester_token,
        "post",
        f"/api/v1/reservations/{changes_id}/submit",
    ).status_code == 200
    changes_response = _request_as(
        client,
        approver_token,
        "post",
        f"/api/v1/reservations/{changes_id}/request-changes",
        json={"comments": "Clarify the custom number request"},
    )
    assert changes_response.status_code == 200
    assert changes_response.json()["status"] == "changes_requested"
    resubmit_response = _request_as(
        client,
        requester_token,
        "post",
        f"/api/v1/reservations/{changes_id}/resubmit",
    )
    assert resubmit_response.status_code == 200
    assert db.get(FormNumberReservation, uuid.UUID(changes_id)).status == "pending_approval"

    rejected_id = generate()
    assert _request_as(
        client,
        requester_token,
        "post",
        f"/api/v1/reservations/{rejected_id}/submit",
    ).status_code == 200
    reject_response = _request_as(
        client,
        approver_token,
        "post",
        f"/api/v1/reservations/{rejected_id}/reject",
        json={"reason": "Number is already represented elsewhere"},
    )
    assert reject_response.status_code == 200
    assert db.get(FormNumberReservation, uuid.UUID(rejected_id)).status == "rejected"

    released_id = generate()
    release_response = _request_as(
        client,
        requester_token,
        "post",
        f"/api/v1/reservations/{released_id}/release",
    )
    assert release_response.status_code == 200
    assert db.get(FormNumberReservation, uuid.UUID(released_id)).status == "released"

    custom_response = _request_as(
        client,
        requester_token,
        "post",
        "/api/v1/reservations/custom",
        json={
            "prefix_id": str(prefix.id),
            "form_number": "SPECIAL1",
            "reason": "Approved custom numbering requirement",
        },
    )
    assert custom_response.status_code == 201
    assert custom_response.json()["numbering_method"] == "custom"

    my_response = _request_as(
        client, requester_token, "get", "/api/v1/reservations/my"
    )
    all_response = _request_as(
        client, requester_token, "get", "/api/v1/reservations"
    )
    detail_response = _request_as(
        client,
        requester_token,
        "get",
        f"/api/v1/reservations/{approved_id}",
    )
    approved_unused_response = _request_as(
        client, requester_token, "get", "/api/v1/reservations/approved-unused"
    )
    pending_response = _request_as(
        client, approver_token, "get", "/api/v1/reservations/pending"
    )
    assert my_response.status_code == 200 and my_response.json()["total"] == 5
    assert all_response.status_code == 200 and all_response.json()["total"] == 5
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == approved_id
    assert approved_unused_response.status_code == 200
    assert approved_id in {
        item["id"] for item in approved_unused_response.json()["reservations"]
    }
    assert pending_response.status_code == 200
    assert changes_id in {item["id"] for item in pending_response.json()["items"]}

    stale_id = generate()
    stale = db.get(FormNumberReservation, uuid.UUID(stale_id))
    stale.created_at = datetime.now(timezone.utc) - timedelta(days=13)
    db.flush()
    expiring_response = _request_as(
        client, operator_token, "get", "/api/v1/reservations/expiring"
    )
    assert expiring_response.status_code == 200
    assert stale_id in {item["id"] for item in expiring_response.json()["items"]}

    stale.created_at = datetime.now(timezone.utc) - timedelta(days=15)
    db.flush()
    expiry_response = _request_as(
        client, operator_token, "post", "/api/v1/reservations/expire"
    )
    assert expiry_response.status_code == 200
    assert expiry_response.json()["expired_count"] == 1
    assert db.get(FormNumberReservation, uuid.UUID(stale_id)).status == "expired"