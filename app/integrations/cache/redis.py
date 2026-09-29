"""Кеш ответов в Redis; недоступность Redis деградирует в «промах», а не ломает запрос."""

import logging

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.schemas.analyze import AnalyzeResponse

logger = logging.getLogger(__name__)


class RedisResponseCache:
    """Кеш готовых ответов в Redis (реализует порт ResponseCache).

    Attributes:
        redis: Асинхронный клиент Redis (с ``decode_responses=True``).
    """

    def __init__(self, redis: Redis) -> None:
        """Запоминает клиент Redis.

        Args:
            redis: Асинхронный клиент Redis.
        """
        self.redis = redis

    async def get(self, key: str) -> AnalyzeResponse | None:
        """Читает ответ из кеша.

        Args:
            key: Ключ кеша.

        Returns:
            Ответ или None, если записи нет, она повреждена или Redis недоступен.
        """
        try:
            raw = await self.redis.get(key)
        except RedisError:
            logger.warning("Redis недоступен при чтении кеша", exc_info=True)
            return None
        if raw is None:
            return None
        try:
            return AnalyzeResponse.model_validate_json(raw)
        except ValidationError:
            logger.warning("Повреждённая запись кеша %s проигнорирована", key)
            return None

    async def set(self, key: str, response: AnalyzeResponse, ttl_seconds: int) -> None:
        """Записывает ответ в кеш.

        Args:
            key: Ключ кеша.
            response: Ответ для сохранения.
            ttl_seconds: Время жизни записи.
        """
        try:
            await self.redis.set(key, response.model_dump_json(), ex=ttl_seconds)
        except RedisError:
            logger.warning("Redis недоступен при записи кеша", exc_info=True)
