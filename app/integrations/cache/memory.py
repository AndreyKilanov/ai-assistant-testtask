"""Кеш ответов в памяти процесса: для тестов и локального запуска без Redis."""

import time

from app.schemas.analyze import AnalyzeResponse


class InMemoryResponseCache:
    """Кеш в памяти с временем жизни записей (реализует порт ResponseCache).

    Attributes:
        max_entries: Предел числа записей; при переполнении вытесняется самая старая.
    """

    def __init__(self, max_entries: int = 1000) -> None:
        """Создаёт пустой кеш.

        Args:
            max_entries: Предел числа записей.
        """
        self.max_entries = max_entries
        self._items: dict[str, tuple[float, str]] = {}

    async def get(self, key: str) -> AnalyzeResponse | None:
        """Читает ответ, если он не устарел.

        Args:
            key: Ключ кеша.

        Returns:
            Ответ или None.
        """
        item = self._items.get(key)
        if item is None:
            return None
        expires_at, raw = item
        if expires_at < time.monotonic():
            del self._items[key]
            return None
        return AnalyzeResponse.model_validate_json(raw)

    async def set(self, key: str, response: AnalyzeResponse, ttl_seconds: int) -> None:
        """Записывает ответ.

        Args:
            key: Ключ кеша.
            response: Ответ для сохранения.
            ttl_seconds: Время жизни записи.
        """
        if len(self._items) >= self.max_entries:
            del self._items[next(iter(self._items))]
        self._items[key] = (time.monotonic() + ttl_seconds, response.model_dump_json())
