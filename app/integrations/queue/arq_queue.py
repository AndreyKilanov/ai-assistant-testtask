"""Очередь фоновых задач на arq (Redis)."""

import logging

from arq.connections import ArqRedis
from redis.exceptions import RedisError

from app.core.errors import QueueUnavailable

logger = logging.getLogger(__name__)

WEBHOOK_TASK_NAME = "process_webhook"


class ArqJobQueue:
    """Очередь arq (реализует порт JobQueue).

    Attributes:
        pool: Пул соединений arq.
    """

    def __init__(self, pool: ArqRedis) -> None:
        """Запоминает пул соединений.

        Args:
            pool: Пул соединений arq.
        """
        self.pool = pool

    async def enqueue_webhook(self, event_id: str) -> None:
        """Ставит обработку события вебхука в очередь.

        Идентификатор задачи совпадает с идентификатором события, поэтому очередь сама не создаст дубль.

        Args:
            event_id: Идентификатор события.

        Raises:
            QueueUnavailable: Redis недоступен.
        """
        try:
            await self.pool.enqueue_job(WEBHOOK_TASK_NAME, event_id, _job_id=f"webhook:{event_id}")
        except (RedisError, OSError) as exc:
            logger.exception("Не удалось поставить событие %s в очередь", event_id)
            raise QueueUnavailable("Очередь обработки временно недоступна") from exc
