"""Порты: интерфейсы, от которых зависят сервисы. Реализации лежат в integrations/ и db/repositories/.

Правило раскладки: один модуль на агрегат, и у каждого порта есть реализация под тем же именем.
Новый порт кладите в модуль своего агрегата; если подходящего нет, заведите новый модуль здесь и, если порту нужна БД,
одноимённый модуль в ``app/db/repositories/``.

* ``assistant`` — Assistant, Retriever, Generator, ResponseCache;
* ``suggestions`` — SuggestionStore, FeedbackStore, StatsProvider (``db/repositories/suggestions``, ``feedback``,
  ``stats``);
* ``conversations`` — ConversationStore, SuggestionReader, AwayModeStore (``db/repositories/conversations``);
* ``webhooks`` — WebhookEventStore, JobQueue, CrmClient (``db/repositories/webhooks``, ``integrations/queue``,
  ``integrations/crm``);
* ``quotas`` — RateLimiter (``integrations/ratelimit``);
* ``llm_health`` — LlmHealthTracker (``integrations/llm/health``).

Импортировать можно из пакета целиком: ``from app.domain.ports import Assistant``.
Границы слоёв проверяет import-linter (см. ``[tool.importlinter]`` в pyproject.toml и tests/test_architecture.py).
"""

from app.domain.ports.assistant import Assistant, Generator, ResponseCache, Retriever
from app.domain.ports.conversations import AwayModeStore, ConversationStore, SuggestionReader
from app.domain.ports.llm_health import LlmHealthTracker
from app.domain.ports.quotas import RateDecision, RateLimiter
from app.domain.ports.suggestions import FeedbackStore, StatsProvider, SuggestionStore
from app.domain.ports.webhooks import CrmClient, JobQueue, WebhookEventRecord, WebhookEventStore

__all__ = [
    "Assistant",
    "AwayModeStore",
    "ConversationStore",
    "CrmClient",
    "FeedbackStore",
    "Generator",
    "JobQueue",
    "LlmHealthTracker",
    "RateDecision",
    "RateLimiter",
    "ResponseCache",
    "Retriever",
    "StatsProvider",
    "SuggestionReader",
    "SuggestionStore",
    "WebhookEventRecord",
    "WebhookEventStore",
]
