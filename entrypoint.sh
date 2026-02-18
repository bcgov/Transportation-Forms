#!/bin/sh
# Entrypoint script for FastAPI application
# Runs database migrations and starts the application

set -e

echo "Starting BC Transportation Forms backend..."

# Run database migrations
echo "Running database migrations..."
alembic upgrade head

# Start FastAPI server
echo "Starting Uvicorn server..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
