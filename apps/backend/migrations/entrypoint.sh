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

# Wait for PostgreSQL to become available (handles k8s startup race conditions
# where the Crunchy primary service endpoint may not be ready yet).
MAX_RETRIES=30
RETRY_INTERVAL=2
for i in $(seq 1 $MAX_RETRIES); do
  if python -c "
import os, sys
from sqlalchemy import create_engine, text
url = os.getenv('DATABASE_URL')
engine = create_engine(url, pool_pre_ping=True)
with engine.connect() as conn:
    conn.execute(text('SELECT 1'))
" 2>/dev/null; then
    echo "==> Database is ready."
    break
  fi
  if [ "$i" -eq "$MAX_RETRIES" ]; then
    echo "ERROR: Database not available after $MAX_RETRIES attempts."
    exit 1
  fi
  echo "Waiting for database... (attempt $i/$MAX_RETRIES)"
  sleep $RETRY_INTERVAL
done

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
