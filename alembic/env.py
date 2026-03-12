"""Alembic environment configuration for database migrations"""

from logging.config import fileConfig
import logging
from sqlalchemy import engine_from_config, text
from sqlalchemy import pool
from alembic import context
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger('alembic.env')

# Set SQLAlchemy URL from environment
sqlalchemy_url = os.getenv('DATABASE_URL', 'postgresql://transportation:password@localhost:5432/transportation_forms')
config.set_main_option('sqlalchemy.url', sqlalchemy_url)

# Import models for target_metadata
from backend.database import Base
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode"""
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = sqlalchemy_url
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Widen version_num to varchar(128) so long revision IDs (>32 chars) don't fail.
        # This is idempotent — PostgreSQL accepts widening a varchar column at any time.
        connection.execute(text("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'alembic_version'
                ) THEN
                    ALTER TABLE alembic_version
                        ALTER COLUMN version_num TYPE varchar(128);
                END IF;
            END $$;
        """))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
