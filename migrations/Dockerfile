# ── Stage 1: Build ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS build

WORKDIR /build

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install only the packages required for running Alembic migrations
RUN pip install --upgrade pip setuptools wheel && \
    pip install --prefix=/install \
        alembic \
        psycopg2-binary \
        SQLAlchemy \
        python-jose[cryptography] \
        passlib[bcrypt] \
        python-dotenv \
        pydantic \
        pydantic-settings \
        pydantic-extra-types \
        structlog \
        pytz \
        python-dateutil

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /install /usr/local

# Copy Alembic configuration and migration scripts
COPY alembic/ ./alembic/
COPY alembic.ini .

# Copy backend package so alembic/env.py can import backend.database / backend.models
COPY backend/ ./backend/

# Copy migrations entrypoint (runs migrations + reference data seeds + optional admin seed)
COPY migrations/entrypoint.sh ./entrypoint.sh

# OpenShift compatibility: UID 1001, root group (GID 0)
RUN chown -R 1001:0 /app && \
    chmod -R g=u /app && \
    chmod +x /app/entrypoint.sh

USER 1001

ENTRYPOINT ["/app/entrypoint.sh"]
