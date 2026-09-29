"""Ограничения расхода: дневной бюджет обращений к модели и вспомогательные расчёты окон."""

from datetime import UTC, datetime, timedelta

from app.core.errors import RateLimitExceeded
from app.domain.ports import Assistant, RateLimiter
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse


def seconds_until_utc_midnight(now: datetime | None = None) -> int:
    """Считает, сколько секунд осталось до конца суток по UTC.

    Args:
        now: Текущее время (для тестов); по умолчанию — сейчас.

    Returns:
        Число секунд до ближайшей полуночи UTC, не меньше 1.
    """
    current = now or datetime.now(UTC)
    midnight = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(int((midnight - current).total_seconds()), 1)


class BudgetedAssistant:
    """Декоратор Assistant: не даёт превысить дневной бюджет обращений к модели.

    Стоит непосредственно вокруг ядра, то есть под кешем: ответы из кеша бюджет не тратят.

    Attributes:
        inner: Ассистент, который вызывает модель.
        limiter: Ограничитель запросов.
        daily_limit: Максимум вызовов модели в сутки (UTC).
    """

    def __init__(self, inner: Assistant, limiter: RateLimiter, daily_limit: int) -> None:
        """Собирает декоратор.

        Args:
            inner: Ассистент, который вызывает модель.
            limiter: Ограничитель запросов.
            daily_limit: Максимум вызовов модели в сутки.
        """
        self.inner = inner
        self.limiter = limiter
        self.daily_limit = daily_limit

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        """Проверяет бюджет и передаёт запрос ассистенту.

        Args:
            request: Запрос на обработку обращения.

        Returns:
            Ответ ассистента.

        Raises:
            RateLimitExceeded: Дневной бюджет исчерпан.
            LlmUnavailable: Модель недоступна.
        """
        day = datetime.now(UTC).strftime("%Y%m%d")
        decision = await self.limiter.hit(f"budget:llm:{day}", self.daily_limit, seconds_until_utc_midnight())
        if not decision.allowed:
            raise RateLimitExceeded(
                "daily", decision.retry_after, "Достигнут дневной лимит обращений к модели, попробуйте завтра"
            )
        return await self.inner.analyze(request)
