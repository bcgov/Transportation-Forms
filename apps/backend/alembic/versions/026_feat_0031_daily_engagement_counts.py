"""FEAT-0031 US-007: anonymous daily engagement counts and writer grants.

Revision ID: 026_feat_0031_daily_engagement_counts
Revises: 025_feat_0031_form_activity

Run as the migration account, which remains the table owner. The separately
provisioned LOGIN account may be granted membership in the NOLOGIN writer
role; this migration does not create credentials or grant membership.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "026_feat_0031_daily_engagement_counts"
down_revision = "025_feat_0031_form_activity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_engagement_counts",
        sa.Column("form_id", UUID(as_uuid=True), nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("source", sa.String(6), nullable=False),
        sa.Column("pct_day", sa.Date(), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "form_id",
            "metric",
            "source",
            "pct_day",
            name="pk_daily_engagement_counts",
        ),
        sa.CheckConstraint(
            "metric IN ('download', 'detail_view', 'link_click')",
            name="ck_daily_engagement_counts_metric",
        ),
        sa.CheckConstraint(
            "source IN ('Staff', 'Public')",
            name="ck_daily_engagement_counts_source",
        ),
        sa.CheckConstraint(
            "count >= 0",
            name="ck_daily_engagement_counts_nonnegative",
        ),
    )

    # Do not replace an existing function: the migration must not silently
    # change unrelated objects in an environment with a naming collision.
    op.execute("""
        CREATE FUNCTION public.daily_engagement_counts_no_decrease()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $function$
        BEGIN
            IF NEW.count < OLD.count THEN
                RAISE EXCEPTION 'daily engagement count cannot decrease'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $function$
    """)
    op.execute("""
        CREATE TRIGGER trg_daily_engagement_counts_no_decrease
        BEFORE UPDATE ON public.daily_engagement_counts
        FOR EACH ROW
        EXECUTE FUNCTION public.daily_engagement_counts_no_decrease()
    """)

    # Roles are cluster-wide; TEST and PROD can share a cluster. Reuse an
    # existing role only if it cannot log in, administer the cluster, or
    # acquire privileges through membership in another role. Grant only in
    # the database currently being migrated. Creating it needs CREATEROLE.
    op.execute("""
        DO $role$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles
                WHERE rolname = 'daily_engagement_writer'
            ) THEN
                BEGIN
                    CREATE ROLE daily_engagement_writer
                        NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
                        NOREPLICATION NOBYPASSRLS;
                EXCEPTION WHEN duplicate_object THEN
                    -- Another database on this cluster created it first.
                    NULL;
                END;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles
                WHERE rolname = 'daily_engagement_writer'
                  AND NOT rolcanlogin AND NOT rolinherit
                  AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
                  AND NOT rolreplication AND NOT rolbypassrls
            ) OR EXISTS (
                SELECT 1 FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS writer
                  ON writer.oid = membership.member
                WHERE writer.rolname = 'daily_engagement_writer'
            ) THEN
                RAISE EXCEPTION
                    'daily_engagement_writer has unsafe attributes or memberships';
            END IF;
        END
        $role$
    """)
    op.execute("REVOKE ALL ON TABLE public.daily_engagement_counts FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO daily_engagement_writer")
    op.execute(
        "GRANT INSERT ON TABLE public.daily_engagement_counts "
        "TO daily_engagement_writer"
    )
    op.execute(
        "GRANT UPDATE (count), "
        "SELECT (form_id, metric, source, pct_day, count) "
        "ON TABLE public.daily_engagement_counts "
        "TO daily_engagement_writer"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE ALL ON TABLE public.daily_engagement_counts "
        "FROM daily_engagement_writer"
    )
    op.execute("REVOKE USAGE ON SCHEMA public FROM daily_engagement_writer")
    # Do not DROP ROLE: another database in this cluster may still use it.
    op.execute(
        "DROP TRIGGER trg_daily_engagement_counts_no_decrease "
        "ON public.daily_engagement_counts"
    )
    op.execute("DROP FUNCTION public.daily_engagement_counts_no_decrease()")
    op.drop_table("daily_engagement_counts")
