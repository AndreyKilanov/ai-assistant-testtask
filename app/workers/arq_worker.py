"""Фоновый worker (arq): обработка вебхуков AmoCRM.

Запуск: ``arq app.workers.arq_worker.WorkerSettings``.
"""

import logging
from typing import Any

from arq.connections import RedisSettings
from arq.worker import Retry
from prometheus_client import start_http_server

from app.bootstrap import build_container
from app.core.config import get_settings
from app.core.errors import LlmUnavailable, RateLimitExceeded
from app.core.logging import setup_logging

logger = logging.getLogger(__name__)

RETRY_BASE_SECONDS = 15
# Не меньше худшего случая вызова модели: число моделей × (1 + LLM_MAX_RETRIES) × LLM_TIMEOUT_SECONDS (см. groq.py).
JOB_TIMEOUT_SECONDS = 300
MAX_PARALLEL_JOBS = 10


async def startup(ctx: dict[str, Any]) -> None:
    """Собирает контейнер зависимостей при старте worker'а.

    Args:
        ctx: Контекст arq, доступный задачам.
    """
    setup_logging()
    settings = get_settings()
    try:
        start_http_server(settings.worker_metrics_port)
    except OSError:
        logger.warning("Порт метрик %s занят: метрики worker недоступны", settings.worker_metrics_port)
    ctx["container"] = await build_container(settings)


async def shutdown(ctx: dict[str, Any]) -> None:
    """Закрывает соединения при остановке worker'а.

    Args:
        ctx: Контекст arq.
    """
    container = ctx.get("container")
    if container is not None:
        await container.aclose()


async def process_webhook(ctx: dict[str, Any], event_id: str) -> None:
    """Готовит подсказку по событию вебхука и передаёт её в CRM.

    При недоступности модели задача повторяется с нарастающей задержкой, при исчерпанном дневном бюджете — когда он
    освободится; после исчерпания попыток событие получает статус ``failed``.

    Args:
        ctx: Контекст arq (контейнер и номер попытки).
        event_id: Идентификатор события.

    Raises:
        Retry: Модель недоступна или бюджет исчерпан, и попытки ещё остались.
        LlmUnavailable: Модель недоступна на последней попытке.
        RateLimitExceeded: Бюджет исчерпан на последней попытке.
    """
    container = ctx["container"]
    attempt = ctx["job_try"]
    final = attempt >= container.settings.webhook_max_tries
    try:
        await container.webhooks.process(event_id, final_attempt=final)
    except (LlmUnavailable, RateLimitExceeded) as exc:
        if final:
            raise
        delay = exc.retry_after if isinstance(exc, RateLimitExceeded) else RETRY_BASE_SECONDS * attempt
        logger.warning("Событие %s: %s, повтор через %s с", event_id, exc, delay)
        raise Retry(defer=delay) from exc


class WorkerSettings:
    """Настройки worker'а arq."""

    functions = [process_webhook]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = get_settings().webhook_max_tries
    job_timeout = JOB_TIMEOUT_SECONDS
    max_jobs = MAX_PARALLEL_JOBS
