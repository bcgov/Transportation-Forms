#!/bin/sh
# migrations/entrypoint.sh
# Runs inside the migrations init container on every deployment.
# Steps:
#   1. Apply all pending Alembic schema migrations (idempotent).
#   2. Seed default reference data: roles, business areas, prefixes (idempotent).
#   3. If INITIAL_ADMIN_EMAIL is set (injected from a K8s secret), seed the
#      initial admin user so they can log in on a brand-new database.
#
# The email value is never written to any file in the repository — it is
# stored exclusively as a GitHub Actions secret and surfaced here via a
# Kubernetes Secret that Helm manages at deploy time.

set -e

echo "==> Running Alembic database migrations..."
alembic upgrade head
echo "==> Migrations complete."

echo "==> Seeding default reference data (roles, business areas, prefixes)..."
python - <<'PYEOF'
from backend.database import SessionLocal
from backend.seeds.default_roles import seed_default_roles
from backend.seeds.default_business_areas import seed_default_business_areas
from backend.seeds.default_prefixes import seed_default_prefixes

db = SessionLocal()
try:
    seed_default_roles(db)
    seed_default_business_areas(db)
    seed_default_prefixes(db)
    print("Default reference data seeded.")
finally:
    db.close()
PYEOF
echo "==> Reference data seeding complete."

if [ -n "${INITIAL_ADMIN_EMAIL:-}" ]; then
    echo "==> Seeding initial admin user..."
    python -m backend.seeds.seed_initial_admin
    echo "==> Admin seeding complete."
fi
