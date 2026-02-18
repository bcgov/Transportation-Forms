#!/bin/sh
# Entrypoint script for FastAPI application
# Runs database migrations and starts the application

set -e

echo "Starting BC Transportation Forms backend..."

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

# Seed default data
echo "Seeding default data..."
python -c "
from backend.database import SessionLocal
from backend.seeds import seed_all_defaults
db = SessionLocal()
try:
    seed_all_defaults(db)
finally:
    db.close()
"

# Start FastAPI server
echo "Starting Uvicorn server..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
