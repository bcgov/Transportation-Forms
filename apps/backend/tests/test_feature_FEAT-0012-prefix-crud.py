"""Tests for FEAT-0012: Form Number Prefix CRUD operations.

Test cases TC2.1–TC7.5 verify the full lifecycle of prefix management:
  - TC2.x  Read (list + detail)
  - TC3.x  Create
  - TC4.x  Update (including prefix-text locking and sequence conflict check)
  - TC5.x  Archive
  - TC6.x  Soft-delete
  - TC7.x  Detail view (reservation history + linked forms)
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import status

from backend.models import (
    Form,
    UserRole,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADMIN_PREFIX_BASE = "/api/v1/admin/prefixes"
PUBLIC_PREFIX_BASE = "/api/v1/prefixes"

_ALL_PREFIX_PERMS = [
    "form_number_prefix:create",
    "form_number_prefix:read",
    "form_number_prefix:update",
    "form_number_prefix:delete",
    "form_number_prefix:archive",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_admin_has_prefix_perms(db, admin_user):
    """Ensure admin user's role has all prefix permissions in the DB.

    The ``admin_user`` fixture creates a role named *admin* but
    ``role_factory`` does not populate ``permissions``.  The
    ``require_permission`` decorator resolves permissions from the DB,
    so the role must carry the correct permission strings.
    """
    user_role = (
        db.query(UserRole)
        .filter(UserRole.user_id == admin_user.id)
        .first()
    )
    role = user_role.role
    perms = list(role.permissions) if isinstance(role.permissions, list) else []
    for p in _ALL_PREFIX_PERMS:
        if p not in perms:
            perms.append(p)
    role.permissions = perms
    db.flush()


# ---------------------------------------------------------------------------
# Module-level fixture: admin with prefix permissions
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _admin_prefix_perms(db, admin_user):
    """Auto-use fixture that ensures admin has prefix permissions for every
    test in this module."""
    _ensure_admin_has_prefix_perms(db, admin_user)


# ---------------------------------------------------------------------------
# TC2.x — Read (List + Detail)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTC2Read:
    """TC2.x: Read operations for prefix list and detail."""

    # TC2.1 ---------------------------------------------------------------
    def test_tc2_1_list_returns_active_and_archived(
        self, client, db, admin_user, admin_token_headers, prefix_factory,
    ):
        """Active *and* archived (but not deleted) prefixes appear in admin list."""
        active = prefix_factory(prefix="ACT", is_active=True, created_by=admin_user)
        archived = prefix_factory(prefix="ARC", is_active=False, created_by=admin_user)

        resp = client.get(ADMIN_PREFIX_BASE, headers=admin_token_headers)
        assert resp.status_code == status.HTTP_200_OK

        data = resp.json()
        returned_ids = {item["id"] for item in data}
        assert str(active.id) in returned_ids
        assert str(archived.id) in returned_ids

    # TC2.2 ---------------------------------------------------------------
    def test_tc2_2_detail_returns_full_response(
        self, client, db, admin_user, admin_token_headers, prefix_factory,
    ):
        """GET detail returns PrefixDetailResponse with expected fields."""
        pfx = prefix_factory(prefix="DET", created_by=admin_user)

        resp = client.get(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_200_OK

        data = resp.json()
        assert data["prefix"] == "DET"
        assert data["created_by_name"] is not None
        assert "reservation_history" in data
        assert "linked_forms" in data
        assert "has_linked_forms" in data
        assert isinstance(data["reservation_history"], list)
        assert isinstance(data["linked_forms"], list)

    # TC2.3 ---------------------------------------------------------------
    def test_tc2_3_user_without_read_permission_denied(
        self, client, user_token_headers,
    ):
        """Staff user (no prefix:read permission) gets 403."""
        resp = client.get(ADMIN_PREFIX_BASE, headers=user_token_headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    # TC2.4 ---------------------------------------------------------------
    def test_tc2_4_missing_prefix_returns_404(
        self, client, admin_token_headers,
    ):
        """Non-existent UUID → 404."""
        fake_id = str(uuid.uuid4())
        resp = client.get(
            f"{ADMIN_PREFIX_BASE}/{fake_id}", headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_tc2_4_deleted_prefix_returns_404(
        self, client, db, admin_user, admin_token_headers, prefix_factory,
    ):
        """Soft-deleted prefix → 404 on detail."""
        pfx = prefix_factory(prefix="DEL", created_by=admin_user)
        pfx.deleted_at = datetime.now(timezone.utc)
        db.flush()

        resp = client.get(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    # TC2.5 ---------------------------------------------------------------
    def test_tc2_5_active_and_archived_states_visible(
        self, client, db, admin_user, admin_token_headers, prefix_factory,
    ):
        """is_active reflects the correct state for both active and archived."""
        active = prefix_factory(prefix="A25", is_active=True, created_by=admin_user)
        archived = prefix_factory(prefix="I25", is_active=False, created_by=admin_user)

        resp = client.get(ADMIN_PREFIX_BASE, headers=admin_token_headers)
        data = {item["id"]: item for item in resp.json()}

        assert data[str(active.id)]["is_active"] is True
        assert data[str(archived.id)]["is_active"] is False


# ---------------------------------------------------------------------------
# TC3.x — Create
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTC3Create:
    """TC3.x: Prefix creation."""

    # TC3.1 ---------------------------------------------------------------
    def test_tc3_1_create_valid_prefix(
        self, client, admin_token_headers,
    ):
        """Valid create → 201, prefix normalised to uppercase, created_by_name set."""
        payload = {
            "prefix": "abc",
            "description": "Test prefix",
            "current_sequence": 0,
            "padding_length": 4,
            "max_number_length": 10,
            "is_case_sensitive": False,
        }
        resp = client.post(
            ADMIN_PREFIX_BASE, json=payload, headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED

        data = resp.json()
        assert data["prefix"] == "ABC"
        assert data["description"] == "Test prefix"
        assert data["current_sequence"] == 0
        assert data["created_by_name"] is not None

    # TC3.2 ---------------------------------------------------------------
    def test_tc3_2_duplicate_normalised_prefix_rejected(
        self, client, admin_token_headers,
    ):
        """Creating 'ABC' then 'abc' should fail (duplicate after normalisation)."""
        payload = {"prefix": "DUP31"}
        client.post(ADMIN_PREFIX_BASE, json=payload, headers=admin_token_headers)

        resp = client.post(
            ADMIN_PREFIX_BASE,
            json={"prefix": "dup31"},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # TC3.3 ---------------------------------------------------------------
    def test_tc3_3_user_without_create_permission_denied(
        self, client, user_token_headers,
    ):
        """Staff user without create permission → 403."""
        resp = client.post(
            ADMIN_PREFIX_BASE,
            json={"prefix": "NOPE"},
            headers=user_token_headers,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    # TC3.4 ---------------------------------------------------------------
    def test_tc3_4_missing_prefix_rejected(
        self, client, admin_token_headers,
    ):
        """Omitting required ``prefix`` → 422."""
        resp = client.post(
            ADMIN_PREFIX_BASE,
            json={"description": "no prefix"},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_tc3_4_non_alphanumeric_rejected(
        self, client, admin_token_headers,
    ):
        """Non-alphanumeric prefix → 422."""
        resp = client.post(
            ADMIN_PREFIX_BASE,
            json={"prefix": "A-B!"},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_tc3_4_prefix_too_long_rejected(
        self, client, admin_token_headers,
    ):
        """Prefix longer than 10 chars → 422."""
        resp = client.post(
            ADMIN_PREFIX_BASE,
            json={"prefix": "A" * 11},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_tc3_4_negative_sequence_rejected(
        self, client, admin_token_headers,
    ):
        """current_sequence < 0 → 422."""
        resp = client.post(
            ADMIN_PREFIX_BASE,
            json={"prefix": "NEG", "current_sequence": -1},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_tc3_4_padding_out_of_range_rejected(
        self, client, admin_token_headers,
    ):
        """padding_length outside [1,20] → 422."""
        resp = client.post(
            ADMIN_PREFIX_BASE,
            json={"prefix": "PAD", "padding_length": 0},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_tc3_4_max_number_out_of_range_rejected(
        self, client, admin_token_headers,
    ):
        """max_number_length outside [1,50] → 422."""
        resp = client.post(
            ADMIN_PREFIX_BASE,
            json={"prefix": "MNL", "max_number_length": 0},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # TC3.5 ---------------------------------------------------------------
    def test_tc3_5_current_sequence_zero_stored(
        self, client, admin_token_headers,
    ):
        """Create with current_sequence=0 → response shows current_sequence=0."""
        resp = client.post(
            ADMIN_PREFIX_BASE,
            json={"prefix": "SEQ0", "current_sequence": 0},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["current_sequence"] == 0


# ---------------------------------------------------------------------------
# TC4.x — Update
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTC4Update:
    """TC4.x: Prefix update, linked-form locking, and sequence conflict check."""

    # TC4.1 ---------------------------------------------------------------
    def test_tc4_1_update_active_prefix(
        self, client, db, admin_user, admin_token_headers, prefix_factory,
    ):
        """Valid update → 200, fields updated, updated_by_name populated."""
        pfx = prefix_factory(prefix="UPD", created_by=admin_user)

        resp = client.put(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}",
            json={"description": "Updated desc", "padding_length": 6},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_200_OK

        data = resp.json()
        assert data["description"] == "Updated desc"
        assert data["padding_length"] == 6
        assert data["updated_by_name"] is not None

    # TC4.2 ---------------------------------------------------------------
    def test_tc4_2_linked_forms_lock_prefix_text(
        self, client, db, admin_user, admin_token_headers,
        prefix_factory, reservation_factory,
    ):
        """When forms are linked via reservations, prefix text change → 400.
        Description change is still allowed."""
        pfx = prefix_factory(prefix="LCK", created_by=admin_user)
        res = reservation_factory(
            prefix=pfx, reserved_by=admin_user, status="reserved",
        )
        # Link a form to the reservation
        form = Form(
            id=uuid.uuid4(),
            title="Linked Form",
            status="draft",
            created_by_id=admin_user.id,
            form_number_reservation_id=res.id,
        )
        db.add(form)
        db.flush()

        # Prefix text change → blocked
        resp = client.put(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}",
            json={"prefix": "NEW"},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "linked forms" in resp.json()["detail"].lower()

        # Description change → allowed
        resp2 = client.put(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}",
            json={"description": "New description"},
            headers=admin_token_headers,
        )
        assert resp2.status_code == status.HTTP_200_OK
        assert resp2.json()["description"] == "New description"

    # TC4.3 ---------------------------------------------------------------
    def test_tc4_3_check_sequence_no_conflicts(
        self, client, db, admin_user, admin_token_headers, prefix_factory,
    ):
        """check-sequence with no reservations → no conflicts."""
        pfx = prefix_factory(prefix="CSQ", created_by=admin_user)

        resp = client.post(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}/check-sequence",
            json={"proposed_sequence": 10},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_200_OK

        data = resp.json()
        assert data["has_conflicts"] is False
        assert data["conflicting_numbers"] == []
        assert data["suggested_sequence"] == 10

    # TC4.4 ---------------------------------------------------------------
    def test_tc4_4_check_sequence_with_conflicts(
        self, client, db, admin_user, admin_token_headers,
        prefix_factory, reservation_factory,
    ):
        """check-sequence when reservation exists above proposed → has_conflicts."""
        pfx = prefix_factory(prefix="CFQ", created_by=admin_user)
        reservation_factory(
            prefix=pfx,
            form_number="0005",
            reserved_by=admin_user,
            status="reserved",
        )

        resp = client.post(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}/check-sequence",
            json={"proposed_sequence": 3},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_200_OK

        data = resp.json()
        assert data["has_conflicts"] is True
        assert 5 in data["conflicting_numbers"]
        assert data["suggested_sequence"] >= 5

    # TC4.5 ---------------------------------------------------------------
    def test_tc4_5_user_without_update_permission_denied(
        self, client, db, admin_user, user_token_headers, prefix_factory,
    ):
        """Staff user without update permission → 403."""
        pfx = prefix_factory(prefix="NUP", created_by=admin_user)
        resp = client.put(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}",
            json={"description": "hack"},
            headers=user_token_headers,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    # TC4.6 ---------------------------------------------------------------
    def test_tc4_6_invalid_update_preserves_existing(
        self, client, db, admin_user, admin_token_headers, prefix_factory,
    ):
        """Invalid values → 400/422, prefix unchanged."""
        pfx = prefix_factory(
            prefix="PRV", current_sequence=10, created_by=admin_user,
        )

        resp = client.put(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}",
            json={"current_sequence": -5},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

        # Verify unchanged
        detail = client.get(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=admin_token_headers,
        )
        assert detail.json()["current_sequence"] == 10

    # TC4.7 ---------------------------------------------------------------
    def test_tc4_7_reservations_alone_do_not_lock_prefix(
        self, client, db, admin_user, admin_token_headers,
        prefix_factory, reservation_factory,
    ):
        """Reservation without linked form → prefix text change is allowed."""
        pfx = prefix_factory(prefix="RES", created_by=admin_user)
        reservation_factory(
            prefix=pfx, reserved_by=admin_user, status="reserved",
        )

        resp = client.put(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}",
            json={"prefix": "REN"},
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["prefix"] == "REN"


# ---------------------------------------------------------------------------
# TC5.x — Archive
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTC5Archive:
    """TC5.x: Prefix archive lifecycle."""

    # TC5.1 ---------------------------------------------------------------
    def test_tc5_1_archive_active_prefix(
        self, client, db, admin_user, admin_token_headers, prefix_factory,
    ):
        """POST archive → 200, is_active=False."""
        pfx = prefix_factory(prefix="ARV", created_by=admin_user)

        resp = client.post(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}/archive",
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["is_active"] is False

    # TC5.2 ---------------------------------------------------------------
    def test_tc5_2_archived_prefix_not_in_public_list(
        self, client, db, admin_user, admin_token_headers, prefix_factory,
    ):
        """Archived prefix does not appear on the public endpoint."""
        pfx = prefix_factory(prefix="PUB", created_by=admin_user)

        # Archive it
        client.post(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}/archive",
            headers=admin_token_headers,
        )

        resp = client.get(PUBLIC_PREFIX_BASE, headers=admin_token_headers)
        assert resp.status_code == status.HTTP_200_OK

        ids_in_public = {item["id"] for item in resp.json()}
        assert str(pfx.id) not in ids_in_public

    # TC5.3 ---------------------------------------------------------------
    def test_tc5_3_archive_preserves_history(
        self, client, db, admin_user, admin_token_headers,
        prefix_factory, reservation_factory,
    ):
        """After archiving, detail still shows reservation_history."""
        pfx = prefix_factory(prefix="AHR", created_by=admin_user)
        reservation_factory(
            prefix=pfx, reserved_by=admin_user, status="released",
        )

        # Archive
        client.post(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}/archive",
            headers=admin_token_headers,
        )

        # Detail should still contain history
        resp = client.get(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.json()["reservation_history"]) == 1

    # TC5.4 ---------------------------------------------------------------
    def test_tc5_4_user_without_archive_permission_denied(
        self, client, db, admin_user, user_token_headers, prefix_factory,
    ):
        """Staff user without archive permission → 403."""
        pfx = prefix_factory(prefix="NAR", created_by=admin_user)
        resp = client.post(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}/archive",
            headers=user_token_headers,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    # TC5.5 ---------------------------------------------------------------
    def test_tc5_5_already_archived_cannot_archive_again(
        self, client, db, admin_user, admin_token_headers, prefix_factory,
    ):
        """Archiving an already-archived prefix → 400."""
        pfx = prefix_factory(prefix="DAR", is_active=False, created_by=admin_user)

        resp = client.post(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}/archive",
            headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# TC6.x — Soft Delete
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTC6Delete:
    """TC6.x: Soft-delete with reservation guards."""

    # TC6.1 ---------------------------------------------------------------
    def test_tc6_1_delete_prefix_without_active_reservations(
        self, client, db, admin_user, admin_token_headers, prefix_factory,
    ):
        """DELETE with no active reservations → 200, then GET → 404."""
        pfx = prefix_factory(prefix="DL1", created_by=admin_user)

        resp = client.delete(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_200_OK

        get_resp = client.get(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=admin_token_headers,
        )
        assert get_resp.status_code == status.HTTP_404_NOT_FOUND

    # TC6.2 ---------------------------------------------------------------
    def test_tc6_2_active_reservations_block_delete(
        self, client, db, admin_user, admin_token_headers,
        prefix_factory, reservation_factory,
    ):
        """Active reservation (status='reserved') blocks delete → 400."""
        pfx = prefix_factory(prefix="BLK", created_by=admin_user)
        reservation_factory(
            prefix=pfx, reserved_by=admin_user, status="reserved",
        )

        resp = client.delete(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "active reservation" in resp.json()["detail"].lower()

    # TC6.3 ---------------------------------------------------------------
    def test_tc6_3_non_blocking_statuses_allow_delete(
        self, client, db, admin_user, admin_token_headers,
        prefix_factory, reservation_factory,
    ):
        """Released / expired / rejected reservations do NOT block delete."""
        pfx = prefix_factory(prefix="NBL", created_by=admin_user)
        for s in ("released", "expired", "rejected"):
            reservation_factory(
                prefix=pfx, reserved_by=admin_user, status=s,
            )

        resp = client.delete(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_200_OK

    # TC6.4 ---------------------------------------------------------------
    def test_tc6_4_user_without_delete_permission_denied(
        self, client, db, admin_user, user_token_headers, prefix_factory,
    ):
        """Staff user without delete permission → 403."""
        pfx = prefix_factory(prefix="NDE", created_by=admin_user)
        resp = client.delete(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=user_token_headers,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    # TC6.5 ---------------------------------------------------------------
    def test_tc6_5_missing_prefix_returns_400(
        self, client, admin_token_headers,
    ):
        """DELETE on a non-existent prefix → 400."""
        fake_id = str(uuid.uuid4())
        resp = client.delete(
            f"{ADMIN_PREFIX_BASE}/{fake_id}", headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_tc6_5_already_deleted_returns_400(
        self, client, db, admin_user, admin_token_headers, prefix_factory,
    ):
        """DELETE on an already soft-deleted prefix → 400."""
        pfx = prefix_factory(prefix="ADD", created_by=admin_user)
        pfx.deleted_at = datetime.now(timezone.utc)
        db.flush()

        resp = client.delete(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# TC7.x — Detail View (History + Linked Forms)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTC7Detail:
    """TC7.x: Detail response with reservation history and linked forms."""

    # TC7.1 ---------------------------------------------------------------
    def test_tc7_1_detail_includes_history_and_linked_forms(
        self, client, db, admin_user, admin_token_headers,
        prefix_factory, reservation_factory,
    ):
        """Detail includes non-empty reservation_history and linked_forms."""
        pfx = prefix_factory(prefix="HLF", created_by=admin_user)
        res = reservation_factory(
            prefix=pfx, reserved_by=admin_user, status="reserved",
        )
        form = Form(
            id=uuid.uuid4(),
            title="Linked Form 7.1",
            status="draft",
            created_by_id=admin_user.id,
            form_number_reservation_id=res.id,
        )
        db.add(form)
        db.flush()

        resp = client.get(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_200_OK

        data = resp.json()
        assert len(data["reservation_history"]) >= 1
        assert len(data["linked_forms"]) >= 1
        assert data["has_linked_forms"] is True

    # TC7.2 ---------------------------------------------------------------
    def test_tc7_2_reservation_history_reverse_chronological(
        self, client, db, admin_user, admin_token_headers,
        prefix_factory, reservation_factory,
    ):
        """Reservations are returned newest-first."""
        pfx = prefix_factory(prefix="CHR", created_by=admin_user)

        reservation_factory(
            prefix=pfx,
            form_number="0001",
            reserved_by=admin_user,
            status="released",
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        reservation_factory(
            prefix=pfx,
            form_number="0002",
            reserved_by=admin_user,
            status="reserved",
            created_at=datetime.now(timezone.utc),
        )

        resp = client.get(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=admin_token_headers,
        )
        history = resp.json()["reservation_history"]
        assert len(history) == 2
        # First item should be the newer reservation
        assert history[0]["form_number"] == "0002"
        assert history[1]["form_number"] == "0001"

    # TC7.3 ---------------------------------------------------------------
    def test_tc7_3_linked_forms_present(
        self, client, db, admin_user, admin_token_headers,
        prefix_factory, reservation_factory,
    ):
        """linked_forms contains correct form data."""
        pfx = prefix_factory(prefix="LNK", created_by=admin_user)
        res = reservation_factory(
            prefix=pfx, reserved_by=admin_user, status="reserved",
        )
        form = Form(
            id=uuid.uuid4(),
            title="My Test Form",
            status="published",
            created_by_id=admin_user.id,
            form_number_reservation_id=res.id,
        )
        db.add(form)
        db.flush()

        resp = client.get(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=admin_token_headers,
        )
        data = resp.json()
        assert len(data["linked_forms"]) == 1

        lf = data["linked_forms"][0]
        assert lf["title"] == "My Test Form"
        assert lf["status"] == "published"
        assert lf["created_by_name"] is not None
        assert lf["created_at"] != ""

    # TC7.4  (covered by TC2.3 — brief duplicate for completeness)
    def test_tc7_4_user_without_read_cannot_view_detail(
        self, client, db, admin_user, user_token_headers, prefix_factory,
    ):
        """Staff user cannot view prefix detail."""
        pfx = prefix_factory(prefix="NRD", created_by=admin_user)
        resp = client.get(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=user_token_headers,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    # TC7.5 ---------------------------------------------------------------
    def test_tc7_5_empty_history_shows_empty_lists(
        self, client, db, admin_user, admin_token_headers, prefix_factory,
    ):
        """Prefix with no reservations → empty reservation_history & linked_forms."""
        pfx = prefix_factory(prefix="EMP", created_by=admin_user)

        resp = client.get(
            f"{ADMIN_PREFIX_BASE}/{pfx.id}", headers=admin_token_headers,
        )
        assert resp.status_code == status.HTTP_200_OK

        data = resp.json()
        assert data["reservation_history"] == []
        assert data["linked_forms"] == []
        assert data["has_linked_forms"] is False
