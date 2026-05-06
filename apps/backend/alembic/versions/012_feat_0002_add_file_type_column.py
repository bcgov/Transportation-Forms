"""FEAT-0002: Add file_type column to forms table

Revision ID: 012_feat_0002_add_file_type_column
Revises: 34e55a913ab2
Create Date: 2026-04-24 00:00:00.000000

Adds a nullable VARCHAR(20) column to store the short file-type label
(e.g. 'pdf', 'docx', 'unknown') derived from the MIME type at upload time.
Existing records retain NULL (no backfill per BR-004).
"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "012_feat_0002_add_file_type_column"
down_revision = "34e55a913ab2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "forms",
        sa.Column("file_type", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("forms", "file_type")
