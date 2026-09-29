"""Окружение Alembic: асинхронные миграции с DSN из настроек приложения."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata
EXTERNAL_TABLE_PREFIX = "data_"


def include_object(obj: object, name: str | None, type_: str, reflected: bool, compare_to: object) -> bool:
    """Исключает из сравнения таблицы LlamaIndex (префикс data_), которыми Alembic не управляет.

    Args:
        obj: Проверяемый объект схемы.
        name: Имя объекта.
        type_: Тип объекта (table, index и т.д.).
        reflected: Объект найден в БД, а не в моделях.
        compare_to: Соответствующий объект другой стороны сравнения.

    Returns:
        False для внешних таблиц, иначе True.
    """
    return not (type_ == "table" and reflected and name and name.startswith(EXTERNAL_TABLE_PREFIX))


def run_migrations_offline() -> None:
    """Генерирует SQL без подключения к БД."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Выполняет миграции на открытом соединении.

    Args:
        connection: Синхронная обёртка над асинхронным соединением.
    """
    context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Применяет миграции через асинхронный движок."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
