"""Корень композиции: сборка всех зависимостей приложения в одном месте.

Здесь единственное место, где конкретные адаптеры подставляются вместо портов. API и worker получают готовый
Container и не создают зависимости сами.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis.asyncio import Redis

from app.core.config import Settings
from app.db.repositories import (
    ConversationRepository,
    FeedbackRepository,
    StatsRepository,
    SuggestionRepository,
    WebhookEventRepository,
    knowledge_version,
)
from app.db.session import get_sessionmaker
from app.domain.ports import Assistant, Generator, RateLimiter, StatsProvider
from app.integrations.away.redis import RedisAwayMode
from app.integrations.cache.redis import RedisResponseCache
from app.integrations.crm.stub import StubCrmClient
from app.integrations.llm.groq import GroqGenerator
from app.integrations.llm.health import LlmHealth
from app.integrations.llm.offline import OfflineGenerator
from app.integrations.queue.arq_queue import ArqJobQueue
from app.integrations.rag.index import KnowledgeIndex
from app.integrations.ratelimit.redis import RedisRateLimiter
from app.services.assistant import AssistantService
from app.services.caching import CachingAssistant
from app.services.conversations import ConversationService
from app.services.feedback import FeedbackService
from app.services.limits import BudgetedAssistant
from app.services.metering import MeteredAssistant
from app.services.recording import RecordingAssistant
from app.services.webhooks import WebhookService

logger = logging.getLogger(__name__)

RESPONSE_FORMAT_VERSION = "f2"


@dataclass
class Container:
    """Собранные зависимости приложения.

    Attributes:
        settings: Настройки приложения.
        assistant: Ассистент с бюджетом, кешем, записью подсказок и метриками.
        webhooks: Сервис обработки вебхуков.
        rate_limiter: Ограничитель запросов.
        feedback: Сервис оценок менеджеров.
        stats: Источник сводной статистики.
        conversations: Сервис диалогов клиентов с менеджерами.
        redis: Клиент Redis (кеш); None в тестах.
        queue_pool: Пул соединений очереди arq; None в тестах.
        llm_health: Состояние языковой модели для шапки консоли менеджера.
    """

    settings: Settings
    assistant: Assistant
    webhooks: WebhookService
    rate_limiter: RateLimiter
    feedback: FeedbackService
    stats: StatsProvider
    conversations: ConversationService
    redis: Redis | None = None
    queue_pool: ArqRedis | None = None
    llm_health: LlmHealth = field(default_factory=LlmHealth)

    async def aclose(self) -> None:
        """Закрывает соединения с Redis."""
        if self.redis is not None:
            await self.redis.aclose()
        if self.queue_pool is not None:
            await self.queue_pool.aclose()


def build_generator(settings: Settings) -> Generator:
    """Выбирает генератор ответов по настройкам.

    Args:
        settings: Настройки приложения.

    Returns:
        GroqGenerator, если задан ключ, иначе OfflineGenerator.
    """
    if settings.groq_api_key.get_secret_value():
        return GroqGenerator(settings)
    logger.warning("GROQ_API_KEY не задан: включён офлайн-режим без LLM")
    return OfflineGenerator()


async def build_container(settings: Settings) -> Container:
    """Собирает боевые зависимости: индекс pgvector, генератор, кеш, репозитории, очередь и CRM-заглушку.

    Цепочка ассистента (снаружи внутрь): метрики -> запись подсказки -> кеш -> дневной бюджет -> ядро. Запись стоит
    снаружи кеша, поэтому подсказка из кеша тоже получает идентификатор для оценки менеджером; бюджет стоит под
    кешем, поэтому ответы из кеша его не тратят.

    Args:
        settings: Настройки приложения.

    Returns:
        Готовый Container.
    """
    sessionmaker = get_sessionmaker()
    index = await asyncio.to_thread(KnowledgeIndex, settings)
    generator = build_generator(settings)

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    limiter = RedisRateLimiter(redis)
    core = BudgetedAssistant(AssistantService(index, generator, settings), limiter, settings.daily_request_limit)
    knowledge = await knowledge_version(sessionmaker)
    namespace = f"{settings.prompt_version}:{generator.model_name}:{knowledge}:{RESPONSE_FORMAT_VERSION}"
    cached = CachingAssistant(
        core, RedisResponseCache(redis), namespace, settings.cache_ttl_seconds, settings.cache_history_turns
    )
    suggestion_repository = SuggestionRepository(sessionmaker)
    llm_health = LlmHealth(
        model=generator.model_name,
        fallback_model=settings.groq_fallback_model or None,
        mode=generator.mode,
        prompt_version=settings.prompt_version,
        redis=redis,
        models=list(getattr(generator, "model_names", [generator.model_name])),
    )
    if isinstance(generator, GroqGenerator):
        generator.selector = llm_health.get_selected
        generator.reporter = llm_health.record_model
    assistant = MeteredAssistant(RecordingAssistant(cached, suggestion_repository), llm_health)
    crm = StubCrmClient()

    queue_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    webhooks = WebhookService(
        events=WebhookEventRepository(sessionmaker),
        queue=ArqJobQueue(queue_pool),
        assistant=assistant,
        crm=crm,
    )
    if settings.demo_mode:
        logger.warning(
            "DEMO_MODE включён: консоль менеджера открывается без ввода кода. Только для локальной демонстрации"
        )
    logger.info("Контейнер собран: модель=%s, кеш=%s", generator.model_name, namespace)
    return Container(
        settings=settings,
        assistant=assistant,
        webhooks=webhooks,
        rate_limiter=limiter,
        feedback=FeedbackService(FeedbackRepository(sessionmaker)),
        stats=StatsRepository(sessionmaker, settings.daily_request_limit),
        conversations=ConversationService(
            ConversationRepository(sessionmaker), suggestion_repository, assistant, crm, RedisAwayMode(redis)
        ),
        redis=redis,
        queue_pool=queue_pool,
        llm_health=llm_health,
    )
