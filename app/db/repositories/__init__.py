"""Репозитории Postgres: по модулю на агрегат, реализуют порты из ``app.domain.ports``.

Раскладка зеркальна ``app/domain/ports/``: порт ``suggestions`` — репозиторий ``suggestions`` и так далее.
"""

from app.db.repositories.conversations import ConversationRepository
from app.db.repositories.feedback import FeedbackRepository
from app.db.repositories.knowledge import knowledge_version
from app.db.repositories.stats import StatsRepository
from app.db.repositories.suggestions import SuggestionRepository
from app.db.repositories.webhooks import WebhookEventRepository
from app.db.session import Sessionmaker

__all__ = [
    "ConversationRepository",
    "FeedbackRepository",
    "Sessionmaker",
    "StatsRepository",
    "SuggestionRepository",
    "WebhookEventRepository",
    "knowledge_version",
]
