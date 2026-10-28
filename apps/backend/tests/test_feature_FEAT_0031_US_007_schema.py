"""PostgreSQL contract for FEAT-0031 US-007's anonymous count store.

Requires a test database whose migration account can create a NOLOGIN role.
The shared test fixture creates an isolated *_test database; the migration
is exercised here rather than relying on metadata.create_all(), which cannot
install the decrease-prevention trigger or the writer role.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
import importlib.util
from pathlib import Path
from threading import Barrier
import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from backend.models import DailyEngagementCount

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/026_feat_0031_daily_engagement_counts.py"
)
_INSERT = text("""
    INSERT INTO public.daily_engagement_counts
        (form_id, metric, source, pct_day, count)
    VALUES (:form_id, :metric, :source, :pct_day, :count)
""")
_UPSERT = text("""
    INSERT INTO public.daily_engagement_counts AS daily
        (form_id, metric, source, pct_day, count)
    VALUES (:form_id, :metric, :source, :pct_day, 1)
    ON CONFLICT ON CONSTRAINT pk_daily_engagement_counts
    DO UPDATE SET count = daily.count + 1
""")


def _migration():
    spec = importlib.util.spec_from_file_location(
        "feat_0031_us_007_schema_migration", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def migrated_engine(_test_engine):
    """Run upgrade on the disposable test DB, then downgrade and restore ORM."""
    migration = _migration()
    with _test_engine.begin() as conn:
        DailyEngagementCount.__table__.drop(conn)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()

    try:
        yield _test_engine
    finally:
        with _test_engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade()
                assert not inspect(conn).has_table("daily_engagement_counts")
                assert (
                    conn.execute(
                        text(
                            "SELECT rolcanlogin FROM pg_roles "
                            "WHERE rolname = 'daily_engagement_writer'"
                        )
                    ).scalar_one()
                    is False
                )
                # Upgrade again with an existing cluster-wide role: it must
                # reuse the role and recreate only this database's objects.
                migration.upgrade()
                assert inspect(conn).has_table("daily_engagement_counts")
                migration.downgrade()
            assert not inspect(conn).has_table("daily_engagement_counts")
            DailyEngagementCount.__table__.create(conn)


def _key(**overrides):
    return {
        "form_id": uuid.uuid4(),
        "metric": "download",
        "source": "Staff",
        "pct_day": date(2026, 10, 22),
        "count": 1,
    } | overrides


def _count(engine, params):
    with engine.connect() as conn:
        return conn.execute(
            text("""
                SELECT count FROM public.daily_engagement_counts
                WHERE form_id = :form_id AND metric = :metric
                  AND source = :source AND pct_day = :pct_day
            """),
            params,
        ).scalar_one()


def test_migration_schema_matches_model_and_has_no_forms_fk(migrated_engine):
    table = DailyEngagementCount.__table__
    assert list(table.columns.keys()) == [
        "form_id",
        "metric",
        "source",
        "pct_day",
        "count",
    ]
    assert not table.foreign_keys
    assert [column.name for column in table.primary_key.columns] == [
        "form_id",
        "metric",
        "source",
        "pct_day",
    ]

    inspector = inspect(migrated_engine)
    columns = inspector.get_columns("daily_engagement_counts")
    assert [column["name"] for column in columns] == list(table.columns.keys())
    assert all(not column["nullable"] for column in columns)
    assert [column["name"] for column in columns[:4]] == inspector.get_pk_constraint(
        "daily_engagement_counts"
    )["constrained_columns"]
    assert not inspector.get_foreign_keys("daily_engagement_counts")
    assert {
        check["name"]
        for check in inspector.get_check_constraints("daily_engagement_counts")
    } == {
        "ck_daily_engagement_counts_metric",
        "ck_daily_engagement_counts_source",
        "ck_daily_engagement_counts_nonnegative",
    }
    assert all(
        column["type"].compile(dialect=migrated_engine.dialect)
        == table.c[column["name"]].type.compile(dialect=migrated_engine.dialect)
        for column in columns
    )


@pytest.mark.parametrize(
    "invalid",
    [
        {"metric": "other"},
        {"source": "public"},
        {"count": -1},
        {"count": None},
        {"form_id": None},
        {"pct_day": None},
    ],
)
def test_database_rejects_invalid_or_missing_fields(migrated_engine, invalid):
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        conn.execute(_INSERT, _key(**invalid))


@pytest.mark.parametrize("metric", ["download", "detail_view", "link_click"])
@pytest.mark.parametrize("source", ["Staff", "Public"])
def test_all_approved_combinations_and_bigint_are_storable(
    migrated_engine,
    metric,
    source,
):
    params = _key(metric=metric, source=source, count=2**32)
    with migrated_engine.begin() as conn:
        conn.execute(_INSERT, params)
    assert _count(migrated_engine, params) == 2**32


def test_owner_cannot_lower_count_but_can_increment(migrated_engine):
    params = _key(count=5)
    with migrated_engine.begin() as conn:
        conn.execute(_INSERT, params)
    for lowered in (4, 0):
        with pytest.raises(DBAPIError) as error, migrated_engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE public.daily_engagement_counts SET count = :lowered
                    WHERE form_id = :form_id AND metric = :metric
                      AND source = :source AND pct_day = :pct_day
                """),
                params | {"lowered": lowered},
            )
        assert error.value.orig.sqlstate == "23514"
        assert _count(migrated_engine, params) == 5
    with migrated_engine.begin() as conn:
        conn.execute(_UPSERT, params)
    assert _count(migrated_engine, params) == 6


def test_writer_role_is_nologin_and_column_limited(migrated_engine):
    with migrated_engine.connect() as conn:
        role = conn.execute(text("""
                SELECT rolcanlogin, rolinherit, rolsuper, rolcreatedb, rolcreaterole,
                       rolreplication, rolbypassrls
                FROM pg_roles WHERE rolname = 'daily_engagement_writer'
            """)).one()
        assert tuple(role) == (False,) * 7
        assert conn.execute(text("""
                SELECT pg_get_userbyid(relowner)
                FROM pg_class WHERE oid = 'public.daily_engagement_counts'::regclass
            """)).scalar_one() != "daily_engagement_writer"

        table_grants = conn.execute(text("""
            SELECT privilege_type FROM information_schema.table_privileges
            WHERE grantee = 'daily_engagement_writer'
              AND table_schema = 'public'
              AND table_name = 'daily_engagement_counts'
        """)).scalars().all()
        column_grants = conn.execute(text("""
            SELECT column_name, privilege_type
            FROM information_schema.column_privileges
            WHERE grantee = 'daily_engagement_writer'
              AND table_schema = 'public'
              AND table_name = 'daily_engagement_counts'
        """)).all()
        assert set(table_grants) == {"INSERT"}
        # Table-wide INSERT is also surfaced for every column here.
        assert {grant for grant in column_grants if grant[1] != "INSERT"} == {
            (name, "SELECT")
            for name in ("form_id", "metric", "source", "pct_day", "count")
        } | {("count", "UPDATE")}
        assert conn.execute(text("""
            SELECT count(*) FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
              AND c.relname <> 'daily_engagement_counts'
              AND (
                has_table_privilege(
                    'daily_engagement_writer', c.oid,
                    'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER'
                )
                OR has_any_column_privilege(
                    'daily_engagement_writer', c.oid,
                    'SELECT, INSERT, UPDATE, REFERENCES'
                )
              )
        """)).scalar_one() == 0
        assert conn.execute(text("""
            SELECT count(*) FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND CASE WHEN c.relkind = 'S' THEN has_sequence_privilege(
                  'daily_engagement_writer', c.oid, 'USAGE, SELECT, UPDATE'
              ) ELSE false END
        """)).scalar_one() == 0
        for privilege in ("DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            assert not conn.execute(
                text("""
                    SELECT has_table_privilege(
                        'daily_engagement_writer',
                        'public.daily_engagement_counts', :privilege
                    )
                """),
                {"privilege": privilege},
            ).scalar_one()


def test_restricted_role_can_upsert_but_cannot_access_other_tables_or_delete(
    migrated_engine,
):
    params = _key(count=5)
    with migrated_engine.begin() as conn:
        conn.execute(_INSERT, params)

    # SET ROLE needs superuser or role membership on the test DB connection.
    # A lack of either is an infrastructure limitation, not a grant bypass.
    with migrated_engine.begin() as conn:
        try:
            conn.execute(text("SET LOCAL ROLE daily_engagement_writer"))
        except DBAPIError:
            pytest.skip("migration account cannot SET ROLE daily_engagement_writer")
        conn.execute(_UPSERT, params)
        assert (
            conn.execute(
                text(
                    "SELECT form_id FROM public.daily_engagement_counts "
                    "WHERE form_id = :form_id"
                ),
                params,
            ).scalar_one()
            == params["form_id"]
        )
        for forbidden in (
            "DELETE FROM public.daily_engagement_counts",
            "SELECT id FROM public.forms",
            "TRUNCATE public.daily_engagement_counts",
            "ALTER TABLE public.daily_engagement_counts ADD COLUMN denied text",
            "CREATE TABLE public.denied_writer_table (id integer)",
        ):
            with pytest.raises(DBAPIError) as error, conn.begin_nested():
                conn.execute(text(forbidden))
            assert error.value.orig.sqlstate == "42501"
        with pytest.raises(DBAPIError) as error, conn.begin_nested():
            conn.execute(
                text("UPDATE public.daily_engagement_counts SET count = count - 1")
            )
        assert error.value.orig.sqlstate == "23514"
    assert _count(migrated_engine, params) == 6


def test_concurrent_first_day_upserts_do_not_lose_counts(migrated_engine):
    params = _key()
    barrier = Barrier(6)

    def increment(_):
        with migrated_engine.begin() as conn:
            barrier.wait(timeout=20)
            conn.execute(_UPSERT, params)

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(increment, range(6)))
    assert _count(migrated_engine, params) == 6
