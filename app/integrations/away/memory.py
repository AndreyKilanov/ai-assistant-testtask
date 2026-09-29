"""Режим «менеджер ушёл» в памяти процесса: для тестов и локального запуска без Redis."""


class InMemoryAwayMode:
    """Флаг режима в памяти (реализует порт AwayModeStore)."""

    def __init__(self, enabled: bool = False) -> None:
        """Создаёт флаг.

        Args:
            enabled: Начальное состояние режима.
        """
        self._enabled = enabled

    async def is_enabled(self) -> bool:
        """Возвращает, включён ли режим.

        Returns:
            True, если бот отвечает клиентам сам.
        """
        return self._enabled

    async def set_enabled(self, enabled: bool) -> None:
        """Включает или выключает режим.

        Args:
            enabled: Новое состояние.
        """
        self._enabled = enabled
