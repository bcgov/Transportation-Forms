"""FEAT-0030 US-007: align Staff portal and reservation permissions.

Revision ID: 022_feat_0030_staff_viewer_forms_only_access
Revises: 021_feat_0029_public_forms_view_link_url
Create Date: 2026-09-02 00:00:00.000000
"""

from alembic import op


revision = "022_feat_0030_staff_viewer_forms_only_access"
down_revision = "021_feat_0029_public_forms_view_link_url"
branch_labels = None
depends_on = None

_NAVIGATION_PERMISSION = "portal:navigation"
_BACKUP_TABLE = "feat_0030_role_permissions_backup"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_BACKUP_TABLE} (
            role_id uuid PRIMARY KEY,
            permissions jsonb
        )
        """
    )
    op.execute(
        f"""
        INSERT INTO {_BACKUP_TABLE} (role_id, permissions)
        SELECT id, permissions
          FROM roles
         WHERE (
                   is_active IS TRUE
               AND deleted_at IS NULL
               AND (
                       lower(btrim(name)) IN (
                           'admin',
                           'staff_manager',
                           'reviewer',
                           'content_editor'
                       )
                    OR is_system IS FALSE
               )
               AND lower(btrim(name)) != 'staff_viewer'
         )
            OR lower(btrim(name)) = 'staff_viewer'
        ON CONFLICT (role_id) DO NOTHING
        """
    )
    op.execute(
        f"""
        WITH normalized AS (
            SELECT id,
                   CASE jsonb_typeof(permissions)
                       WHEN 'array' THEN permissions
                       WHEN 'object' THEN COALESCE(
                           (
                               SELECT jsonb_agg(to_jsonb(permission))
                                 FROM jsonb_object_keys(permissions) AS permission
                           ),
                           '[]'::jsonb
                       )
                       ELSE '[]'::jsonb
                   END AS permissions
              FROM roles
        )
        UPDATE roles
           SET permissions = CASE
               WHEN normalized.permissions @> '["{_NAVIGATION_PERMISSION}"]'::jsonb
               THEN normalized.permissions
               ELSE normalized.permissions || '["{_NAVIGATION_PERMISSION}"]'::jsonb
           END
          FROM normalized
         WHERE roles.id = normalized.id
           AND roles.is_active IS TRUE
           AND roles.deleted_at IS NULL
           AND (lower(btrim(roles.name)) IN (
                    'admin',
                    'staff_manager',
                    'reviewer',
                    'content_editor'
                )
                OR roles.is_system IS FALSE)
           AND lower(btrim(roles.name)) != 'staff_viewer'
        """
    )
    op.execute(
        f"""
        WITH normalized AS (
            SELECT id,
                   CASE jsonb_typeof(permissions)
                       WHEN 'array' THEN permissions
                       WHEN 'object' THEN COALESCE(
                           (
                               SELECT jsonb_agg(to_jsonb(permission))
                                 FROM jsonb_object_keys(permissions) AS permission
                           ),
                           '[]'::jsonb
                       )
                       ELSE '[]'::jsonb
                   END AS permissions
              FROM roles
        )
        UPDATE roles
           SET permissions = COALESCE(
               (
                   SELECT jsonb_agg(permission)
                     FROM jsonb_array_elements(normalized.permissions) AS permission
                    WHERE jsonb_typeof(permission) = 'string'
                      AND permission #>> '{{}}' != '{_NAVIGATION_PERMISSION}'
                      AND permission #>> '{{}}' NOT LIKE 'reservation:%'
               ),
               '[]'::jsonb
           )
          FROM normalized
         WHERE roles.id = normalized.id
           AND lower(btrim(roles.name)) = 'staff_viewer'
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE roles
           SET permissions = backup.permissions
          FROM {_BACKUP_TABLE} AS backup
         WHERE roles.id = backup.role_id
        """
    )
    op.execute(f"DROP TABLE {_BACKUP_TABLE}")