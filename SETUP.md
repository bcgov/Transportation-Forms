# BC Transportation Forms - Local Development Setup

## Prerequisites

- PostgreSQL 16 LTS running on localhost:5432
- Docker & Docker Compose installed
- Python 3.12 (for local development without Docker)
- Git

## Step 1: Clone and Initial Setup

```bash
# Clone repository
git clone https://github.com/bcgov/Transportation-Forms.git
cd Transportation-Forms

# Create the transportation_forms database (if not using default)
# Using your local PostgreSQL at localhost:5432
psql -U postgres -h localhost -c "CREATE DATABASE transportation_forms;"
```

## Step 2: Create Environment File (.env)

⚠️ **IMPORTANT**: The `.env` file contains credentials and is **git-ignored** for security.

```bash
# Copy the example template
cp .env.example .env

# Edit .env with your local credentials
# Update DATABASE_URL to match your PostgreSQL setup:
# DATABASE_URL=postgresql://postgres:password@localhost:5432/transportation_forms
```

**Your `.env` file should contain:**
```
ENVIRONMENT=development
LOG_LEVEL=INFO
DATABASE_URL=postgresql://postgres:password@localhost:5432/transportation_forms
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
SECRET_KEY=dev-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
CORS_ORIGINS=["http://localhost:3000", "http://localhost:8080", "http://127.0.0.1:3000"]
CORS_ALLOW_CREDENTIALS=true
CORS_ALLOW_METHODS=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
CORS_ALLOW_HEADERS=["*"]
# ... rest of variables from .env.example
```

## Step 3: Build Docker Image

```bash
# Build the FastAPI container
docker build -t transportation-forms .

# Verify build succeeded
docker images | grep transportation-forms
```

## Step 4: Run Database Migrations

```bash
# Option A: Using docker-compose (includes optional PostgreSQL)
docker-compose up -d

# Option B: Using Docker (connect to local PostgreSQL)
docker run -p 8000:8000 \
  --env-file .env \
  --network host \
  transportation-forms

# Option C: Manual migration (Python environment)
alembic upgrade head
python backend/sample_data.py
```

## Step 5: Load Sample Data

```bash
# Option A: If using docker-compose
docker-compose exec app python backend/sample_data.py

# Option B: If running container directly
docker exec <container-id> python backend/sample_data.py

# Option C: Python environment
python backend/sample_data.py
```

Sample data includes:
- 4 System Roles: admin, staff_manager, reviewer, staff_viewer
- 6 Business Areas
- 4 Test Users (one per role)

## Step 6: Verify Installation

```bash
# Health check endpoint
curl http://localhost:8000/health
# Expected response: {"status": "healthy", "service": "BC Transportation Forms API"}

# API documentation
# Swagger UI: http://localhost:8000/api/v1/docs
# ReDoc: http://localhost:8000/api/v1/redoc
```

## Step 7: Test Sample Users

Use these credentials to test different roles:

| Email | Role | Password |
|-------|------|----------|
| admin@transportation.bc.ca | admin | (Azure AD auth) |
| manager@transportation.bc.ca | staff_manager | (Azure AD auth) |
| reviewer@transportation.bc.ca | reviewer | (Azure AD auth) |
| staff@transportation.bc.ca | staff_viewer | (Azure AD auth) |

**Note**: Authentication uses Azure AD (Entra) in production. For local development, you may need to mock the auth or use a test Azure AD tenant.

## Development Workflow

### Pre-commit Hooks

```bash
# Install pre-commit hooks (runs black, flake8, isort, bandit on commit)
pre-commit install

# Run hooks manually
pre-commit run --all-files
```

### Running Tests

```bash
# All tests with coverage
pytest backend/ --cov=backend --cov-report=html

# Specific test file
pytest backend/tests/test_auth.py -v

# With debugging info
pytest backend/ -vvs --tb=short
```

### Code Quality Checks

```bash
# Format code with Black
black backend/

# Check linting (Flake8)
flake8 backend/ --max-line-length=100

# Type checking (mypy)
mypy backend/ --ignore-missing-imports

# Security scan (Bandit)
bandit -r backend/ -c .bandit
```

### Database Migrations

```bash
# Create new migration (auto-detects model changes)
alembic revision --autogenerate -m "description of changes"

# Apply migrations up to current version
alembic upgrade head

# Rollback one version
alembic downgrade -1

# View migration history
alembic history --oneline
```

## Troubleshooting

### Connection Error: "Could not connect to server: Connection refused"
- Ensure PostgreSQL is running: `psql -U postgres -c "SELECT 1"`
- Check DATABASE_URL in .env file
- Verify PostgreSQL is listening on localhost:5432

### Docker Build Fails
- Clear build cache: `docker build --no-cache -t transportation-forms .`
- Check Python version: `docker run transportation-forms python --version`
- View build logs: `docker build -t transportation-forms . 2>&1 | tee build.log`

### Migration Fails
- Check database exists: `psql -U postgres -l | grep transportation_forms`
- Delete and recreate: `psql -U postgres -c "DROP DATABASE transportation_forms; CREATE DATABASE transportation_forms;"`
- Retry: `alembic upgrade head`

### Tests Fail
- Ensure test database is clean: `alembic downgrade base && alembic upgrade head`
- Check PostgreSQL connection: `pytest backend/ -vvs --tb=short`
- Clear pytest cache: `rm -rf .pytest_cache/ && pytest backend/`

## Docker Compose Commands

```bash
# Start all services (app + optional PostgreSQL)
docker-compose up -d

# View logs
docker-compose logs -f app

# Stop services
docker-compose down

# Remove volumes (database data)
docker-compose down -v

# Rebuild on code changes
docker-compose up -d --build
```

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| ENVIRONMENT | development | dev/test/production |
| DATABASE_URL | postgresql://postgres:password@localhost:5432/transportation_forms | PostgreSQL connection string |
| DB_POOL_SIZE | 10 | Base connection pool size |
| DB_MAX_OVERFLOW | 20 | Max additional connections |
| SECRET_KEY | dev-secret-key-* | JWT signing key (change in production!) |
| ENABLE_SEMANTIC_SEARCH | true | Enable pgvector semantic search |
| ENABLE_EMAIL_NOTIFICATIONS | false | Enable email notifications |
| AZURE_TENANT_ID | (required for prod) | Azure AD tenant ID |
| S3_BUCKET | (required for prod) | AWS S3 bucket name |

## Next Steps

1. **Day 1**: Verify setup with health check and sample data
2. **Day 2**: Run full test suite to ensure environment is correct
3. **Development**: Use pre-commit hooks to maintain code quality
4. **Migrations**: Follow the migration workflow for schema changes

## Support

For issues or questions:
- Check logs: `docker-compose logs`
- Verify environment: `cat .env` (but don't commit!)
- Review CONSTITUTION.md for standards and requirements
- Check SPECIFICATION.md for API contracts
