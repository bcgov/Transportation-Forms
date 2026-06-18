"""Regression tests for ``backend.seeds.default_business_areas``.

The seed runs on every migrations-container start (see
``apps/backend/migrations/entrypoint.sh``) and previously failed with
``psycopg.errors.UniqueViolation`` on subsequent deploys whenever a
``business_areas`` row existed with the same ``name`` but a different
``id`` (which is the common case once admins start creating their own
Business Areas via the FEAT-0025 admin UI).

These tests lock down the idempotency contract: re-running the seed
against any pre-existing state must not raise and must not mutate
admin-managed rows.
"""

import uuid
from datetime import datetime, timezone

import pytest

from backend.models import BusinessArea
from backend.seeds.default_business_areas import (
    BUSINESS_AREAS,
    seed_default_business_areas,
)


class TestSeedDefaultBusinessAreasIdempotency:
    def test_fresh_install_inserts_all_canonical_rows(self, db):
        # Sanity: no canonical names present yet.
        canonical_names = {entry["name"] for entry in BUSINESS_AREAS}
        existing = (
            db.query(BusinessArea)
            .filter(BusinessArea.name.in_(canonical_names))
            .all()
        )
        for row in existing:
            db.delete(row)
        db.commit()

        seed_default_business_areas(db)

        rows = (
            db.query(BusinessArea)
            .filter(BusinessArea.name.in_(canonical_names))
            .all()
        )
        assert {r.name for r in rows} == canonical_names
        for r in rows:
            # Canonical ids should be used on a fresh install.
            assert str(r.id) in {entry["id"] for entry in BUSINESS_AREAS}

    def test_second_run_is_noop_when_rows_already_exist(self, db):
        seed_default_business_areas(db)
        before = {
            r.name: r.id
            for r in db.query(BusinessArea).all()
        }

        # Re-running must not raise and must not change ids.
        seed_default_business_areas(db)

        after = {
            r.name: r.id
            for r in db.query(BusinessArea).all()
        }
        for name in {entry["name"] for entry in BUSINESS_AREAS}:
            assert before[name] == after[name]

    def test_skips_when_name_exists_under_different_id(self, db):
        """Reproduces the production bug: a BA with one of the canonical
        names was created via the admin UI under a different ``id``. The
        old seed crashed with ``UniqueViolation`` on the next deploy."""
        target = BUSINESS_AREAS[1]  # 'Permits' in the canonical list
        canonical_id = uuid.UUID(target["id"])
        canonical_name = target["name"]

        # Make sure the canonical row is gone, then create an admin-managed
        # row with the same NAME but a DIFFERENT id.
        db.query(BusinessArea).filter(
            (BusinessArea.id == canonical_id)
            | (BusinessArea.name == canonical_name)
        ).delete(synchronize_session=False)
        db.commit()

        admin_id = uuid.uuid4()
        admin_row = BusinessArea(
            id=admin_id,
            name=canonical_name,
            mailbox="admin-managed@example.com",
        )
        db.add(admin_row)
        db.commit()

        # The seed must NOT raise.
        seed_default_business_areas(db)

        # The admin-managed row must be untouched (id and mailbox preserved).
        rows = (
            db.query(BusinessArea)
            .filter(BusinessArea.name == canonical_name)
            .all()
        )
        assert len(rows) == 1, (
            "Seed should not have inserted a duplicate row under the "
            "canonical id when the name was already taken."
        )
        assert rows[0].id == admin_id
        assert rows[0].mailbox == "admin-managed@example.com"

    def test_skips_when_name_exists_soft_deleted(self, db):
        """A soft-deleted row still occupies the unique ``name`` slot, so the
        seed must not attempt to insert a fresh row under the canonical id.
        """
        target = BUSINESS_AREAS[2]  # 'Applications'
        canonical_id = uuid.UUID(target["id"])
        canonical_name = target["name"]

        db.query(BusinessArea).filter(
            (BusinessArea.id == canonical_id)
            | (BusinessArea.name == canonical_name)
        ).delete(synchronize_session=False)
        db.commit()

        soft_deleted_id = uuid.uuid4()
        db.add(
            BusinessArea(
                id=soft_deleted_id,
                name=canonical_name,
                deleted_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        db.commit()

        seed_default_business_areas(db)

        rows = (
            db.query(BusinessArea)
            .filter(BusinessArea.name == canonical_name)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].id == soft_deleted_id
        assert rows[0].deleted_at is not None  # untouched
