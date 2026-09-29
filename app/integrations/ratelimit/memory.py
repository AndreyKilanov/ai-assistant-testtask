"""Ограничитель запросов в памяти процесса: для тестов и локального запуска без Redis."""

import time

from app.domain.ports import RateDecision


class InMemoryRateLimiter:
    """Счётчик обращений в памяти с фиксированным окном (реализует порт RateLimiter)."""

    def __init__(self) -> None:
        """Создаёт пустой ограничитель."""
        self._windows: dict[str, tuple[float, int]] = {}

    async def hit(self, key: str, limit: int, window_seconds: int) -> RateDecision:
        """Учитывает обращение.

        Args:
            key: Ключ счётчика.
            limit: Максимум обращений за окно.
            window_seconds: Длина окна в секундах.

        Returns:
            Решение с оставшимся временем окна.
        """
        now = time.monotonic()
        expires_at, count = self._windows.get(key, (0.0, 0))
        if expires_at <= now:
            expires_at, count = now + window_seconds, 0
        count += 1
        self._windows[key] = (expires_at, count)
        return RateDecision(allowed=count <= limit, retry_after=max(int(expires_at - now), 1))
