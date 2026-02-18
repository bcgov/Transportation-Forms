#!/bin/bash
# Setup script for BC Transportation Forms
# Create the PostgreSQL database and user

set -e

echo "🔧 BC Transportation Forms - Database Setup"
echo "==========================================="
echo ""
echo "This script creates the PostgreSQL database and user."
echo "Ensure PostgreSQL is running on localhost:5432"
echo ""

# database name
DB_NAME="transportation_forms"
DB_USER="postgres"
DB_PASSWORD="password"
DB_HOST="localhost"
DB_PORT="5432"

echo "Creating database: $DB_NAME"
echo "User: $DB_USER"
echo "Host: $DB_HOST:$DB_PORT"
echo ""

# Create database (if it doesn't exist)
psql -h $DB_HOST -U $DB_USER -p $DB_PORT -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 || psql -h $DB_HOST -U $DB_USER -p $DB_PORT -c "CREATE DATABASE $DB_NAME;"

echo "✅ Database created successfully!"
echo ""
echo "Next steps:"
echo "1. Copy .env.example to .env"
echo "2. Update DATABASE_URL in .env if needed"
echo "3. Run: docker build -t transportation-forms ."
echo "4. Run: docker run -p 8000:8000 --env-file .env transportation-forms"
echo ""
echo "Or use docker-compose:"
echo "   docker-compose up"
