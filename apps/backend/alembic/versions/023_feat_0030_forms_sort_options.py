"""FEAT-0030 US-012: add Staff Forms natural English title collation.

Revision ID: 023_feat_0030_forms_sort_options
Revises: 022_feat_0030_staff_viewer_forms_only_access
Create Date: 2026-09-09 00:00:00.000000
"""

from alembic import op


revision = "023_feat_0030_forms_sort_options"
down_revision = "022_feat_0030_staff_viewer_forms_only_access"
branch_labels = None
depends_on = None

_COLLATION_NAME = "forms_title_en_natural_ci"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE COLLATION public.{_COLLATION_NAME} (
            provider = icu,
            locale = 'en-u-kn-ks-level2',
            deterministic = false
        )
        """
    )


def downgrade() -> None:
    op.execute(f"DROP COLLATION public.{_COLLATION_NAME}")