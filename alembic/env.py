"""Alembic migration environment for the application database."""

import os
from logging.config import fileConfig

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from alembic import context
from app.core.config import DEFAULT_SETTINGS_FILE, get_settings
from app.devices.model import Device

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Importing Device registers its table; this is the shared Base metadata.
target_metadata = Device.metadata


def get_database_url() -> str:
    """Return the unwrapped database URL only to Alembic internals."""
    env_file = os.getenv("SETTINGS_FILE", DEFAULT_SETTINGS_FILE)
    settings = get_settings(env_file)
    return settings.database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Run migrations without creating a live database connection."""
    url = get_database_url()

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations through a SQLAlchemy connection and transaction."""
    engine = create_engine(get_database_url(), poolclass=NullPool)

    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
