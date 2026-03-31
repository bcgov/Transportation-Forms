#!/bin/sh
# Entrypoint script for the FastAPI backend container.
#
# Migrations are no longer run here — they are executed by the migrations
# init container (see charts/app/templates/backend/deployment.yaml) before
# this container starts.  Seeding is a one-time administrative task and
# must be run manually or via a separate Job in non-production environments.

set -e

echo "Starting BC Transportation Forms backend..."

# Start FastAPI server (production: no --reload)
echo "Starting Uvicorn server on port 8000..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000

