"""Index normalized business-area contact emails for contact-based scope.

FEAT-0032 US-003 matches email-only contacts to the signed-in account using
``lower(btrim(email))``. This expression index keeps that lookup indexed on
every scoped authorization check and at login.

Revision ID: 026_feat_0032_contact_email_index
Revises: 025_feat_0031_form_activity
"""

from alembic import op

revision = "026_feat_0032_contact_email_index"
down_revision = "025_feat_0031_form_activity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_business_area_contacts_email_normalized "
        "ON business_area_contacts (lower(btrim(email))) "
        "WHERE email IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_business_area_contacts_email_normalized")
