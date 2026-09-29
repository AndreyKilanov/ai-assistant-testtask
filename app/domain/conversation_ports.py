"""Порты диалогов: хранилище диалогов и сообщений, чтение сохранённых подсказок."""

from datetime import datetime
from typing import Protocol

from app.domain.conversations import ConversationRecord, MessageRecord
from app.schemas.analyze import AnalyzeResponse


class SuggestionReader(Protocol):
    """Чтение сохранённых подсказок."""

    async def get(self, suggestion_id: int) -> AnalyzeResponse | None:
        """Возвращает сохранённую подсказку в виде ответа API.

        Args:
            suggestion_id: Идентификатор подсказки.

        Returns:
            Подсказка или None, если её нет.
        """
        ...


class ConversationStore(Protocol):
    """Хранилище диалогов и сообщений."""

    async def create(self, client_name: str | None) -> ConversationRecord:
        """Создаёт диалог со статусом ``new``.

        Args:
            client_name: Имя клиента.

        Returns:
            Созданный диалог.
        """
        ...

    async def get(self, conversation_id: int) -> ConversationRecord | None:
        """Возвращает диалог по идентификатору.

        Args:
            conversation_id: Идентификатор диалога.

        Returns:
            Диалог или None.
        """
        ...

    async def get_by_token(self, token: str) -> ConversationRecord | None:
        """Возвращает диалог по клиентскому токену.

        Args:
            token: Токен диалога.

        Returns:
            Диалог или None.
        """
        ...

    async def add_message(
        self,
        conversation_id: int,
        sender: str,
        text: str,
        *,
        status: str | None = None,
        unread_delta: int = 0,
        suggestion_id: int | None = None,
        suggestion_state: str | None = None,
        edited: bool = False,
        auto: bool = False,
        links: list[dict[str, str]] | None = None,
    ) -> MessageRecord:
        """Добавляет сообщение и обновляет диалог (превью, время, непрочитанные, статус).

        Args:
            conversation_id: Диалог.
            sender: client, manager или system.
            text: Текст.
            status: Новый статус диалога (None — не менять).
            unread_delta: На сколько увеличить число непрочитанных менеджером.
            suggestion_id: Связанная подсказка ИИ.
            suggestion_state: Состояние подсказки для сообщения клиента.
            edited: Менеджер изменил подсказку перед отправкой.
            auto: Ответ отправил бот в режиме «менеджер ушёл».
            links: Кнопки-ссылки на страницы сайта.

        Returns:
            Созданное сообщение.
        """
        ...

    async def get_message(self, message_id: int) -> MessageRecord | None:
        """Возвращает сообщение.

        Args:
            message_id: Идентификатор сообщения.

        Returns:
            Сообщение или None.
        """
        ...

    async def list_messages(self, conversation_id: int, after_id: int = 0) -> list[MessageRecord]:
        """Возвращает сообщения диалога с идентификатором больше ``after_id``.

        Args:
            conversation_id: Диалог.
            after_id: Последний уже известный идентификатор.

        Returns:
            Сообщения по возрастанию идентификатора.
        """
        ...

    async def list_conversations(
        self, status: str | None, query: str | None, limit: int
    ) -> tuple[list[ConversationRecord], dict[str, int]]:
        """Возвращает диалоги для списка входящих и число диалогов по статусам.

        Args:
            status: Фильтр по статусу.
            query: Поиск по имени клиента и началу последнего сообщения.
            limit: Максимум диалогов.

        Returns:
            Диалоги (требующие внимания выше) и счётчики по статусам без учёта фильтра.
        """
        ...

    async def update(self, conversation_id: int, **fields: object) -> ConversationRecord | None:
        """Обновляет поля диалога.

        Args:
            conversation_id: Диалог.
            **fields: Поля для обновления.

        Returns:
            Обновлённый диалог или None, если его нет.
        """
        ...

    async def set_message_suggestion(self, message_id: int, suggestion_id: int | None, state: str) -> None:
        """Привязывает подсказку к сообщению клиента.

        Args:
            message_id: Сообщение клиента.
            suggestion_id: Подсказка (None при сбое).
            state: pending, ready или failed.
        """
        ...

    async def latest_client_message(self, conversation_id: int) -> MessageRecord | None:
        """Возвращает последнее сообщение клиента.

        Args:
            conversation_id: Диалог.

        Returns:
            Сообщение или None.
        """
        ...

    async def unanswered_client_messages(self, since: datetime, limit: int) -> list[tuple[int, int]]:
        """Возвращает диалоги, где последнее сообщение — клиента, без ответа менеджера или бота.

        Args:
            since: Не старше этого момента.
            limit: Максимум диалогов.

        Returns:
            Пары (идентификатор диалога, идентификатор сообщения клиента) от старых к новым.
        """
        ...

    async def count_messages(self, conversation_id: int) -> tuple[int, int]:
        """Считает сообщения диалога.

        Args:
            conversation_id: Диалог.

        Returns:
            Пара (сообщений клиента и менеджера, сообщений клиента).
        """
        ...


class AwayModeStore(Protocol):
    """Общий переключатель «менеджер ушёл: бот отвечает клиентам сам»."""

    async def is_enabled(self) -> bool:
        """Возвращает, включён ли режим.

        Returns:
            True, если бот отвечает клиентам сам.
        """
        ...

    async def set_enabled(self, enabled: bool) -> None:
        """Включает или выключает режим.

        Args:
            enabled: Новое состояние.
        """
        ...
