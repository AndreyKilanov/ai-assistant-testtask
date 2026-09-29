"""Режим «менеджер ушёл» в Redis: общий для API и worker'а и переживает перезапуск (Redis пишет AOF)."""

import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

AWAY_KEY = "manager:away"


class RedisAwayMode:
    """Флаг режима в Redis (реализует порт AwayModeStore).

    Недоступность Redis не должна ломать чат: чтение считается «режим выключен» (fail-safe: бот молчит, ответит
    менеджер), а запись пробрасывает ошибку, чтобы менеджер увидел, что режим не включился.

    Attributes:
        redis: Асинхронный клиент Redis.
    """

    def __init__(self, redis: Redis) -> None:
        """Запоминает клиент Redis.

        Args:
            redis: Асинхронный клиент Redis.
        """
        self.redis = redis

    async def is_enabled(self) -> bool:
        """Возвращает, включён ли режим.

        Returns:
            True, если бот отвечает клиентам сам; False также при сбое Redis.
        """
        try:
            return await self.redis.get(AWAY_KEY) == "1"
        except RedisError:
            logger.warning("Redis недоступен: режим «менеджер ушёл» считается выключенным")
            return False

    async def set_enabled(self, enabled: bool) -> None:
        """Включает или выключает режим.

        Args:
            enabled: Новое состояние.
        """
        if enabled:
            await self.redis.set(AWAY_KEY, "1")
        else:
            await self.redis.delete(AWAY_KEY)
