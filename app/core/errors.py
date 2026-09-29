"""Доменные ошибки приложения; HTTP-коды для них назначаются в слое API."""


class LlmUnavailable(Exception):
    """Модель недоступна или вернула ответ, который не удалось разобрать.

    Attributes:
        reason: ``rate_limit`` — исчерпан лимит провайдера, ``bad_format`` — ответ не по схеме, иначе ``unavailable``.
    """

    def __init__(self, message: str = "", reason: str = "unavailable") -> None:
        """Создаёт ошибку.

        Args:
            message: Сообщение для пользователя.
            reason: Причина недоступности модели.
        """
        super().__init__(message)
        self.reason = reason


class QueueUnavailable(Exception):
    """Очередь задач недоступна: событие нельзя поставить в обработку."""


class RateLimitExceeded(Exception):
    """Превышен лимит запросов: на клиента в минуту или дневной бюджет обращений к модели.

    Attributes:
        scope: Какой лимит сработал: ``client`` или ``daily``.
        retry_after: Через сколько секунд можно повторить запрос.
    """

    def __init__(self, scope: str, retry_after: int, message: str) -> None:
        """Создаёт ошибку.

        Args:
            scope: Какой лимит сработал.
            retry_after: Через сколько секунд можно повторить запрос.
            message: Сообщение для пользователя.
        """
        super().__init__(message)
        self.scope = scope
        self.retry_after = retry_after


class SuggestionNotFound(Exception):
    """Подсказка с таким идентификатором не найдена."""


class ConversationNotFound(Exception):
    """Диалог с таким идентификатором не найден."""
