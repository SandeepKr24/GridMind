"""Alembic environment.

Differs from the generated template in four ways, each deliberate:

* the URL comes from `Settings`, not `alembic.ini`, so migrations and the
  application can never disagree about which database they mean, and no
  credential is written to a tracked file;
* migrations run as the **writer** role — the read-only role has no DDL rights
  at all, which is the point of it;
* `include_schemas` plus `version_table_schema` keep both our tables and
  Alembic's own bookkeeping inside `gridmind` rather than `public`;
* the Windows event-loop fix is applied before connecting, because psycopg
  cannot run async on the default Windows loop.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.db.models import SCHEMA, Base
from app.runtime import configure_event_loop

configure_event_loop()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

settings = Settings()  # type: ignore[call-arg]
config.set_main_option("sqlalchemy.url", settings.database_url)


def include_object(obj: object, name: str | None, type_: str, *args: object) -> bool:
    """Keep autogenerate focused on our own schema.

    Without this, a table in `public` — Alembic's own, or anything Neon adds —
    would show up in a migration as something to drop.
    """
    if type_ == "table":
        return getattr(obj, "schema", None) == SCHEMA
    return True


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
        version_table_schema=SCHEMA,
        # Without this, a column type change is silently ignored.
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_object=include_object,
        version_table_schema=SCHEMA,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        # NullPool: a migration run is a one-shot process. Pooling would only
        # hold a Neon connection open after the work is done.
        poolclass=NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
