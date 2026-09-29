"""Ограничитель запросов на Redis: счётчик с фиксированным окном."""

import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.domain.ports import RateDecision

logger = logging.getLogger(__name__)


class RedisRateLimiter:
    """Счётчик обращений в Redis (реализует порт RateLimiter).

    Недоступность Redis не блокирует работу сервиса: обращение разрешается (fail-open), а причина пишется в лог.

    Attributes:
        redis: Асинхронный клиент Redis.
    """

    def __init__(self, redis: Redis) -> None:
        """Запоминает клиент Redis.

        Args:
            redis: Асинхронный клиент Redis.
        """
        self.redis = redis

    async def hit(self, key: str, limit: int, window_seconds: int) -> RateDecision:
        """Учитывает обращение атомарно (MULTI): создаёт счётчик с TTL при первом обращении и увеличивает его.

        Args:
            key: Ключ счётчика.
            limit: Максимум обращений за окно.
            window_seconds: Длина окна в секундах.

        Returns:
            Решение; при ошибке Redis обращение разрешается.
        """
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.set(key, 0, ex=window_seconds, nx=True)
                pipe.incr(key)
                pipe.ttl(key)
                _, count, ttl = await pipe.execute()
        except RedisError:
            logger.warning("Redis недоступен: лимит %s не применён", key, exc_info=True)
            return RateDecision(allowed=True, retry_after=0)
        return RateDecision(allowed=count <= limit, retry_after=max(int(ttl), 1))
