"""Сущности диалогов и правила смены статусов."""

from dataclasses import dataclass, field
from datetime import datetime

NEEDS_ATTENTION = ("new", "callback")
PENDING_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class ConversationRecord:
    """Диалог клиента с менеджером.

    Attributes:
        id: Идентификатор.
        token: Неугадываемый идентификатор для клиента.
        client_name: Имя клиента.
        channel: Канал обращения.
        status: Статус диалога.
        contact_method: Способ связи.
        contact_value: Номер, ник или почта.
        preferred_time: Удобное время связи.
        contact_comment: Комментарий к запросу связи.
        contact_requested_at: Когда клиент просил связаться.
        manager_note: Внутренняя заметка менеджера.
        unread_by_manager: Непрочитанные менеджером сообщения клиента.
        last_message_preview: Начало последнего сообщения.
        last_message_at: Время последнего сообщения.
        created_at: Начало диалога.
        hot: Клиент готов купить, а менеджер ещё не ответил.
    """

    id: int
    token: str
    client_name: str | None
    channel: str
    status: str
    contact_method: str | None
    contact_value: str | None
    preferred_time: str | None
    contact_comment: str | None
    contact_requested_at: datetime | None
    manager_note: str
    unread_by_manager: int
    last_message_preview: str
    last_message_at: datetime
    created_at: datetime
    hot: bool = False


@dataclass(frozen=True)
class MessageRecord:
    """Сообщение диалога.

    Attributes:
        id: Идентификатор.
        conversation_id: Диалог.
        sender: client, manager или system.
        text: Текст.
        suggestion_id: Связанная подсказка ИИ.
        suggestion_state: pending, ready или failed (для сообщений клиента).
        edited: Менеджер изменил подсказку перед отправкой.
        created_at: Время отправки.
        auto: Ответ отправил бот в режиме «менеджер ушёл».
        links: Кнопки-ссылки на страницы сайта: список ``{title, url}``.
    """

    id: int
    conversation_id: int
    sender: str
    text: str
    suggestion_id: int | None
    suggestion_state: str | None
    edited: bool
    created_at: datetime
    auto: bool = False
    links: list[dict[str, str]] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)


def status_after_client_message(current: str) -> str:
    """Определяет статус после сообщения клиента.

    Диалоги «в работе» и «просит связаться» остаются на месте; остальные (в том числе закрытые) снова становятся
    новыми, чтобы сообщение не потерялось.

    Args:
        current: Текущий статус.

    Returns:
        Новый статус.
    """
    return current if current in {"in_progress", "callback"} else "new"


def status_after_manager_message(current: str) -> str:
    """Определяет статус после ответа менеджера.

    Args:
        current: Текущий статус.

    Returns:
        ``callback`` остаётся (связь ещё нужно организовать), остальные становятся «ждём клиента».
    """
    return "callback" if current == "callback" else "waiting_client"


def status_after_open(current: str) -> str:
    """Определяет статус после того, как менеджер открыл диалог.

    Args:
        current: Текущий статус.

    Returns:
        ``in_progress`` для нового диалога, иначе прежний статус.
    """
    return "in_progress" if current == "new" else current
