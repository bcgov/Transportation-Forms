"""US-015 regression coverage for administrator-created catalogues."""

from pathlib import Path

from backend.models import AuditLog, BusinessArea, FormNumberPrefix, Role, User
from backend.seeds import seed_all_defaults


REMOVED_PREFIXES = {"H", "CVSE", "INS", "T", "MV"}
REMOVED_BUSINESS_AREAS = {
    "Licensing",
    "Permits",
    "Applications",
    "Compliance",
    "Reporting",
}


def test_normal_seeding_leaves_catalogues_empty_and_preserves_other_defaults(
    db,
):
    audit_count = db.query(AuditLog).count()

    seed_all_defaults(db)
    seed_all_defaults(db)

    assert db.query(FormNumberPrefix).count() == 0
    assert db.query(BusinessArea).count() == 0
    assert {
        role.name
        for role in db.query(Role).filter(Role.is_system.is_(True)).all()
    } == {"admin", "staff_viewer"}
    demo_user = (
        db.query(User).filter_by(email="demo@example.com").one_or_none()
    )
    assert demo_user is not None
    assert db.query(AuditLog).count() == audit_count


def test_normal_seeding_preserves_administrator_created_catalogues(db):
    prefix = FormNumberPrefix(
        prefix="ADM",
        description="Administrator managed prefix",
        current_sequence=17,
        padding_length=5,
        max_number_length=9,
        is_case_sensitive=True,
        is_active=False,
    )
    business_area = BusinessArea(
        name="Administrator Services",
        mailbox="administrator.services@example.com",
    )
    db.add_all([prefix, business_area])
    db.commit()
    db.refresh(prefix)
    db.refresh(business_area)

    prefix_snapshot = {
        "id": prefix.id,
        "prefix": prefix.prefix,
        "description": prefix.description,
        "current_sequence": prefix.current_sequence,
        "padding_length": prefix.padding_length,
        "max_number_length": prefix.max_number_length,
        "is_case_sensitive": prefix.is_case_sensitive,
        "is_active": prefix.is_active,
        "created_at": prefix.created_at,
        "updated_at": prefix.updated_at,
    }
    business_area_snapshot = {
        "id": business_area.id,
        "name": business_area.name,
        "mailbox": business_area.mailbox,
        "created_at": business_area.created_at,
        "updated_at": business_area.updated_at,
    }

    seed_all_defaults(db)
    seed_all_defaults(db)
    db.refresh(prefix)
    db.refresh(business_area)

    assert {
        "id": prefix.id,
        "prefix": prefix.prefix,
        "description": prefix.description,
        "current_sequence": prefix.current_sequence,
        "padding_length": prefix.padding_length,
        "max_number_length": prefix.max_number_length,
        "is_case_sensitive": prefix.is_case_sensitive,
        "is_active": prefix.is_active,
        "created_at": prefix.created_at,
        "updated_at": prefix.updated_at,
    } == prefix_snapshot
    assert {
        "id": business_area.id,
        "name": business_area.name,
        "mailbox": business_area.mailbox,
        "created_at": business_area.created_at,
        "updated_at": business_area.updated_at,
    } == business_area_snapshot
    assert {
        row.prefix for row in db.query(FormNumberPrefix).all()
    }.isdisjoint(REMOVED_PREFIXES)
    assert {
        row.name for row in db.query(BusinessArea).all()
    }.isdisjoint(REMOVED_BUSINESS_AREAS)


def test_production_and_aggregate_seed_paths_exclude_removed_catalogues():
    backend_root = Path(__file__).resolve().parents[1]
    aggregate_source = (backend_root / "seeds" / "__init__.py").read_text()
    entrypoint_source = (
        backend_root / "migrations" / "entrypoint.sh"
    ).read_text()

    for source in (aggregate_source, entrypoint_source):
        assert "default_business_areas" not in source
        assert "default_prefixes" not in source
        assert "seed_default_business_areas" not in source
        assert "seed_default_prefixes" not in source

    assert "seed_default_roles(db)" in aggregate_source
    assert "seed_demo_user(db)" in aggregate_source
    assert "seed_default_roles(db)" in entrypoint_source
