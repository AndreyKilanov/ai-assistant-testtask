"""Порты состояния языковой модели: учёт исхода вызова для шапки консоли менеджера."""

from typing import Protocol


class LlmHealthTracker(Protocol):
    """Учёт исходов вызовов модели."""

    async def record_ok(self, model: str) -> None:
        """Отмечает успешный свежий вызов модели.

        Args:
            model: Модель, давшая ответ.
        """
        ...

    async def record_failure(self, state: str) -> None:
        """Отмечает отказ модели.

        Args:
            state: ``rate_limit``, ``budget`` или ``unavailable``.
        """
        ...
