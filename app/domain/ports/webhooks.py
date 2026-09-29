"""Порты вебхуков: журнал событий, очередь фоновых задач и CRM, куда возвращается подсказка."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class WebhookEventRecord:
    """Сохранённое событие вебхука.

    Attributes:
        event_id: Идентификатор события от AmoCRM.
        payload: Тело события.
        status: received, processed, retry или failed.
    """

    event_id: str
    payload: dict[str, Any]
    status: str


class WebhookEventStore(Protocol):
    """Хранилище событий вебхука (идемпотентность и статусы обработки)."""

    async def create(self, event_id: str, payload: dict[str, Any]) -> bool:
        """Сохраняет событие, если его ещё не было.

        Args:
            event_id: Идентификатор события.
            payload: Тело события.

        Returns:
            True, если событие новое; False, если такое уже принималось.
        """
        ...

    async def get(self, event_id: str) -> WebhookEventRecord | None:
        """Возвращает событие.

        Args:
            event_id: Идентификатор события.

        Returns:
            Событие или None.
        """
        ...

    async def set_status(self, event_id: str, status: str, error: str | None = None) -> None:
        """Обновляет статус обработки.

        Args:
            event_id: Идентификатор события.
            status: Новый статус.
            error: Текст ошибки, если есть.
        """
        ...

    async def delete(self, event_id: str) -> None:
        """Удаляет событие, чтобы повторная доставка была принята заново.

        Args:
            event_id: Идентификатор события.
        """
        ...


class JobQueue(Protocol):
    """Очередь фоновых задач."""

    async def enqueue_webhook(self, event_id: str) -> None:
        """Ставит обработку события вебхука в очередь.

        Args:
            event_id: Идентификатор события.

        Raises:
            QueueUnavailable: Очередь недоступна.
        """
        ...


class CrmClient(Protocol):
    """Клиент CRM, куда возвращается подсказка для менеджера."""

    async def add_note(self, lead_id: str, text: str) -> None:
        """Добавляет заметку в сделку.

        Args:
            lead_id: Идентификатор сделки.
            text: Текст заметки.
        """
        ...
