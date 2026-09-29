"""Подключение к Postgres: асинхронный движок и фабрика сессий."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Создаёт единственный асинхронный движок SQLAlchemy на процесс.

    Returns:
        AsyncEngine с проверкой живости соединений перед использованием.
    """
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Возвращает фабрику асинхронных сессий.

    Returns:
        async_sessionmaker, не сбрасывающий объекты после commit.
    """
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Зависимость FastAPI: выдаёт сессию на время запроса.

    Yields:
        Открытая AsyncSession, закрывается после ответа.
    """
    async with get_sessionmaker()() as session:
        yield session
