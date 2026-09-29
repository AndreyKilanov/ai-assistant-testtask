"""Заглушка AmoCRM.

Реальная интеграция не входит в объём прототипа. Заглушка не выполняет сетевых вызовов и не изображает соединение:
она лишь фиксирует в логе, что заметка была бы отправлена. Для подключения настоящего AmoCRM достаточно
реализовать порт ``CrmClient`` (метод ``add_note``) и подставить его в ``app.bootstrap``.
"""

import logging
from collections import deque

logger = logging.getLogger(__name__)

RECENT_NOTES_LIMIT = 50


class StubCrmClient:
    """Заглушка клиента CRM (реализует порт CrmClient).

    Attributes:
        recent_notes: Последние «отправленные» заметки (лид, текст) для отладки и тестов; в CRM они не уходят.
    """

    def __init__(self) -> None:
        """Создаёт заглушку с пустой историей."""
        self.recent_notes: deque[tuple[str, str]] = deque(maxlen=RECENT_NOTES_LIMIT)

    async def add_note(self, lead_id: str, text: str) -> None:
        """Фиксирует заметку в логе; в AmoCRM ничего не отправляется.

        Args:
            lead_id: Идентификатор сделки.
            text: Текст заметки.
        """
        self.recent_notes.append((lead_id, text))
        logger.info(
            "[CRM-заглушка] заметка для сделки %s НЕ отправлена в AmoCRM (интеграция не подключена):\n%s", lead_id, text
        )
