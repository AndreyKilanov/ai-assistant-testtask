"""Порты квот: ограничитель запросов."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RateDecision:
    """Решение ограничителя запросов.

    Attributes:
        allowed: Запрос укладывается в лимит.
        retry_after: Через сколько секунд окно лимита сбросится (для заголовка Retry-After).
    """

    allowed: bool
    retry_after: int


class RateLimiter(Protocol):
    """Ограничитель запросов (счётчик с фиксированным окном)."""

    async def hit(self, key: str, limit: int, window_seconds: int) -> RateDecision:
        """Учитывает одно обращение и решает, укладывается ли оно в лимит.

        Args:
            key: Ключ счётчика (клиент, сутки и т. п.).
            limit: Максимум обращений за окно.
            window_seconds: Длина окна; отсчёт начинается с первого обращения.

        Returns:
            Решение. Недоступность хранилища не должна блокировать работу: тогда обращение разрешается.
        """
        ...
