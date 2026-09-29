"""Репозиторий диалогов и сообщений (таблицы ``conversations`` и ``chat_messages``)."""

import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from sqlalchemy import and_, case, func, or_, select, update

from app.core.errors import ConversationNotFound
from app.db.models import ChatMessage, Conversation
from app.db.session import Sessionmaker
from app.domain.conversations import NEEDS_ATTENTION, ConversationRecord, MessageRecord, status_after_open

PREVIEW_CHARS = 160


def conversation_record(row: Conversation) -> ConversationRecord:
    """Преобразует ORM-модель диалога в неизменяемую запись.

    Args:
        row: Строка таблицы conversations.

    Returns:
        ConversationRecord.
    """
    return ConversationRecord(
        id=row.id,
        token=row.token,
        client_name=row.client_name,
        channel=row.channel,
        status=row.status,
        contact_method=row.contact_method,
        contact_value=row.contact_value,
        preferred_time=row.preferred_time,
        contact_comment=row.contact_comment,
        contact_requested_at=row.contact_requested_at,
        manager_note=row.manager_note,
        unread_by_manager=row.unread_by_manager,
        last_message_preview=row.last_message_preview,
        last_message_at=row.last_message_at,
        created_at=row.created_at,
        hot=row.hot,
    )


def message_record(row: ChatMessage) -> MessageRecord:
    """Преобразует ORM-модель сообщения в неизменяемую запись.

    Args:
        row: Строка таблицы chat_messages.

    Returns:
        MessageRecord.
    """
    return MessageRecord(
        id=row.id,
        conversation_id=row.conversation_id,
        sender=row.sender,
        text=row.text,
        suggestion_id=row.suggestion_id,
        suggestion_state=row.suggestion_state,
        edited=row.edited,
        created_at=row.created_at,
        auto=row.auto,
        links=list(row.links or []),
    )


class ConversationRepository:
    """Хранилище диалогов и сообщений (реализует порт ConversationStore).

    Attributes:
        sessionmaker: Фабрика асинхронных сессий.
    """

    def __init__(self, sessionmaker: Sessionmaker) -> None:
        """Запоминает фабрику сессий.

        Args:
            sessionmaker: Фабрика асинхронных сессий SQLAlchemy.
        """
        self.sessionmaker = sessionmaker

    async def create(self, client_name: str | None) -> ConversationRecord:
        """Создаёт диалог со статусом ``new`` и неугадываемым токеном.

        Args:
            client_name: Имя клиента.

        Returns:
            Созданный диалог.
        """
        now = datetime.now(UTC)
        row = Conversation(
            token=uuid.uuid4().hex,
            client_name=client_name,
            status="new",
            last_message_at=now,
            created_at=now,
            updated_at=now,
        )
        async with self.sessionmaker() as session:
            session.add(row)
            await session.commit()
            return conversation_record(row)

    async def get(self, conversation_id: int) -> ConversationRecord | None:
        """Возвращает диалог по идентификатору.

        Args:
            conversation_id: Идентификатор диалога.

        Returns:
            Диалог или None.
        """
        async with self.sessionmaker() as session:
            row = await session.get(Conversation, conversation_id)
            return None if row is None else conversation_record(row)

    async def get_by_token(self, token: str) -> ConversationRecord | None:
        """Возвращает диалог по клиентскому токену.

        Args:
            token: Токен диалога.

        Returns:
            Диалог или None.
        """
        async with self.sessionmaker() as session:
            row = (await session.execute(select(Conversation).where(Conversation.token == token))).scalar_one_or_none()
            return None if row is None else conversation_record(row)

    async def add_message(
        self,
        conversation_id: int,
        sender: str,
        text: str,
        *,
        status: str | Callable[[str], str] | None = None,
        unread_delta: int = 0,
        suggestion_id: int | None = None,
        suggestion_state: str | None = None,
        edited: bool = False,
        auto: bool = False,
        links: list[dict[str, str]] | None = None,
        update_fields: Mapping[str, object] | None = None,
    ) -> MessageRecord:
        """Добавляет сообщение и обновляет превью, время, непрочитанные и статус диалога в одной транзакции.

        Args:
            conversation_id: Диалог.
            sender: client, manager или system.
            text: Текст.
            status: Новый статус диалога или функция от текущего статуса (вычисляется под блокировкой строки);
                None — не менять.
            unread_delta: На сколько увеличить число непрочитанных менеджером.
            suggestion_id: Связанная подсказка ИИ.
            suggestion_state: Состояние подсказки для сообщения клиента.
            edited: Менеджер изменил подсказку перед отправкой.
            auto: Ответ отправил бот в режиме «менеджер ушёл».
            links: Кнопки-ссылки на страницы сайта.
            update_fields: Дополнительные поля диалога, которые меняются в той же транзакции.

        Returns:
            Созданное сообщение.

        Raises:
            ConversationNotFound: Диалога нет.
        """
        now = datetime.now(UTC)
        async with self.sessionmaker() as session, session.begin():
            conversation = await session.get(Conversation, conversation_id, with_for_update=True)
            if conversation is None:
                raise ConversationNotFound("Диалог не найден")
            if callable(status):
                status = status(conversation.status)
            for name, value in (update_fields or {}).items():
                setattr(conversation, name, value)
            message = ChatMessage(
                conversation_id=conversation_id,
                sender=sender,
                text=text,
                suggestion_id=suggestion_id,
                suggestion_state=suggestion_state,
                edited=edited,
                auto=auto,
                links=links or [],
                created_at=now,
            )
            session.add(message)
            conversation.last_message_preview = " ".join(text.split())[:PREVIEW_CHARS]
            conversation.last_message_at = now
            conversation.updated_at = now
            conversation.unread_by_manager += unread_delta
            if status is not None:
                conversation.status = status
                conversation.closed_at = now if status == "closed" else None
            if (sender == "manager" and not auto) or status == "closed":
                conversation.hot = False  # менеджер ответил или закрыл диалог: срочность снята
            await session.flush()
            return message_record(message)

    async def get_message(self, message_id: int) -> MessageRecord | None:
        """Возвращает сообщение.

        Args:
            message_id: Идентификатор сообщения.

        Returns:
            Сообщение или None.
        """
        async with self.sessionmaker() as session:
            row = await session.get(ChatMessage, message_id)
            return None if row is None else message_record(row)

    async def list_messages(
        self, conversation_id: int, after_id: int = 0, *, before_id: int | None = None, limit: int | None = None
    ) -> list[MessageRecord]:
        """Возвращает сообщения диалога с идентификатором больше ``after_id`` и меньше ``before_id``.

        Args:
            conversation_id: Диалог.
            after_id: Последний уже известный идентификатор.
            before_id: Верхняя граница идентификатора (не включая); None — без границы.
            limit: Сколько последних сообщений из выборки вернуть; None — все.

        Returns:
            Сообщения по возрастанию идентификатора.
        """
        stmt = select(ChatMessage).where(ChatMessage.conversation_id == conversation_id, ChatMessage.id > after_id)
        if before_id is not None:
            stmt = stmt.where(ChatMessage.id < before_id)
        if limit is None:
            stmt = stmt.order_by(ChatMessage.id)
        else:
            stmt = stmt.order_by(ChatMessage.id.desc()).limit(limit)
        async with self.sessionmaker() as session:
            rows = [message_record(row) for row in (await session.execute(stmt)).scalars()]
        return rows if limit is None else rows[::-1]

    async def list_conversations(
        self, status: str | None, query: str | None, limit: int
    ) -> tuple[list[ConversationRecord], dict[str, int]]:
        """Возвращает диалоги для списка входящих и число диалогов по статусам.

        Args:
            status: Фильтр по статусу.
            query: Поиск по имени клиента и началу последнего сообщения.
            limit: Максимум диалогов.

        Returns:
            Диалоги (горячие клиенты выше всех, затем новые и просящие связаться) и счётчики по статусам без учёта
            фильтра.
        """
        hot = case((and_(Conversation.hot.is_(True), Conversation.status != "closed"), 0), else_=1)
        attention = case((Conversation.status.in_(NEEDS_ATTENTION), 0), else_=1)
        stmt = select(Conversation).order_by(hot, attention, Conversation.last_message_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(Conversation.status == status)
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            stmt = stmt.where(
                or_(Conversation.client_name.ilike(pattern), Conversation.last_message_preview.ilike(pattern))
            )
        counts_stmt = select(Conversation.status, func.count()).group_by(Conversation.status)
        async with self.sessionmaker() as session:
            rows = [conversation_record(row) for row in (await session.execute(stmt)).scalars()]
            counts = {name: count for name, count in (await session.execute(counts_stmt)).all()}
        return rows, counts

    async def update(self, conversation_id: int, **fields: object) -> ConversationRecord | None:
        """Обновляет поля диалога.

        Args:
            conversation_id: Диалог.
            **fields: Поля для обновления (статус, заметка, число непрочитанных, данные для связи).

        Returns:
            Обновлённый диалог или None, если его нет.
        """
        now = datetime.now(UTC)
        async with self.sessionmaker() as session, session.begin():
            row = await session.get(Conversation, conversation_id, with_for_update=True)
            if row is None:
                return None
            for name, value in fields.items():
                setattr(row, name, value)
            if "status" in fields:
                row.closed_at = now if fields["status"] == "closed" else None
            row.updated_at = now
            await session.flush()
            return conversation_record(row)

    async def mark_opened(self, conversation_id: int) -> ConversationRecord | None:
        """Отмечает диалог открытым менеджером: сбрасывает непрочитанные, новый диалог берёт в работу.

        Действует под блокировкой строки: сообщение клиента, пришедшее одновременно, не теряется из счётчика.

        Args:
            conversation_id: Диалог.

        Returns:
            Обновлённый диалог или None, если его нет.
        """
        async with self.sessionmaker() as session, session.begin():
            row = await session.get(Conversation, conversation_id, with_for_update=True)
            if row is None:
                return None
            opened_status = status_after_open(row.status)
            if row.unread_by_manager or opened_status != row.status:
                row.unread_by_manager = 0
                row.status = opened_status
                row.updated_at = datetime.now(UTC)
            await session.flush()
            return conversation_record(row)

    async def set_message_suggestion(self, message_id: int, suggestion_id: int | None, state: str) -> None:
        """Привязывает подсказку к сообщению клиента.

        Args:
            message_id: Сообщение клиента.
            suggestion_id: Подсказка (None при сбое).
            state: pending, ready или failed.
        """
        stmt = (
            update(ChatMessage)
            .where(ChatMessage.id == message_id)
            .values(suggestion_id=suggestion_id, suggestion_state=state)
        )
        async with self.sessionmaker() as session:
            await session.execute(stmt)
            await session.commit()

    async def latest_client_message(self, conversation_id: int) -> MessageRecord | None:
        """Возвращает последнее сообщение клиента.

        Args:
            conversation_id: Диалог.

        Returns:
            Сообщение или None.
        """
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id, ChatMessage.sender == "client")
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
        async with self.sessionmaker() as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
            return None if row is None else message_record(row)

    async def unanswered_client_messages(self, since: datetime, limit: int) -> list[tuple[int, int]]:
        """Возвращает диалоги, где последнее сообщение — клиента, без ответа менеджера или бота.

        Args:
            since: Не старше этого момента.
            limit: Максимум диалогов.

        Returns:
            Пары (идентификатор диалога, идентификатор сообщения клиента) от старых к новым.
        """
        last = (
            select(func.max(ChatMessage.id).label("message_id"))
            .where(ChatMessage.sender.in_(("client", "manager")), ChatMessage.created_at >= since)
            .group_by(ChatMessage.conversation_id)
            .subquery()
        )
        stmt = (
            select(ChatMessage.conversation_id, ChatMessage.id)
            .join(last, ChatMessage.id == last.c.message_id)
            .where(ChatMessage.sender == "client", ChatMessage.created_at >= since)
            .order_by(ChatMessage.id)
            .limit(limit)
        )
        async with self.sessionmaker() as session:
            return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]

    async def count_messages(self, conversation_id: int) -> tuple[int, int]:
        """Считает сообщения диалога.

        Args:
            conversation_id: Диалог.

        Returns:
            Пара (сообщений клиента и менеджера, сообщений клиента).
        """
        stmt = select(
            func.count().filter(ChatMessage.sender.in_(("client", "manager"))),
            func.count().filter(ChatMessage.sender == "client"),
        ).where(ChatMessage.conversation_id == conversation_id)
        async with self.sessionmaker() as session:
            both, client = (await session.execute(stmt)).one()
        return both, client
