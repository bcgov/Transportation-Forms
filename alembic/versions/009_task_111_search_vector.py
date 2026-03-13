"""TASK-111: add PostgreSQL full-text search vector infrastructure

Revision ID: 009_task_111_search_vector
Revises: 008_task_420_remove_form_user_version_field
Create Date: 2026-03-13 00:00:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = '009_task_111_search_vector'
down_revision = '008_task_420_remove_form_user_version_field'
branch_labels = None
depends_on = None


def _search_vector_expression(qualifier: str = "") -> str:
    prefix = f"{qualifier}." if qualifier else ""
    return (
        f"setweight(to_tsvector('english', coalesce({prefix}title, '')), 'A') || "
        f"setweight(to_tsvector('english', coalesce({prefix}description, '')), 'B') || "
        f"setweight(to_tsvector('english', coalesce({prefix}keywords::text, '')), 'C') || "
        f"setweight(to_tsvector('english', coalesce({prefix}form_source, '')), 'D') || "
        f"setweight(to_tsvector('english', coalesce({prefix}form_source_url, '')), 'D')"
    )


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE forms
        ALTER COLUMN search_vector TYPE tsvector
        USING ({_search_vector_expression()})
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION forms_search_vector_update()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := {_search_vector_expression('NEW')};
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_forms_search_vector_update
        BEFORE INSERT OR UPDATE OF title, description, keywords, form_source, form_source_url
        ON forms
        FOR EACH ROW
        EXECUTE FUNCTION forms_search_vector_update();
        """
    )

    op.execute(
        f"""
        UPDATE forms
        SET search_vector = {_search_vector_expression()}
        """
    )

    op.create_index(
        'idx_forms_search_vector',
        'forms',
        ['search_vector'],
        unique=False,
        postgresql_using='gin',
    )


def downgrade() -> None:
    op.drop_index('idx_forms_search_vector', table_name='forms')

    op.execute("DROP TRIGGER IF EXISTS trg_forms_search_vector_update ON forms")
    op.execute("DROP FUNCTION IF EXISTS forms_search_vector_update")

    op.execute("""
        ALTER TABLE forms
        ALTER COLUMN search_vector TYPE varchar
        USING search_vector::text
    """)
