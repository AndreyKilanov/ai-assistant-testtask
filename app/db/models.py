"""ORM-модели приложения.

Фрагменты базы знаний с векторами хранит LlamaIndex в собственной таблице ``data_kb_chunks``
(создаётся на этапе RAG); здесь описаны остальные таблицы.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Базовый класс всех моделей."""


class KbDocument(Base):
    """Запись базы знаний и хеш её содержимого для пропуска повторной индексации.

    Attributes:
        slug: Стабильный идентификатор записи из knowledge_base.json.
        title: Заголовок записи.
        category: Категория (товар, набор, доставка и т.д.).
        source_url: Страница сайта, из которой получена запись.
        content_hash: SHA-256 текста записи; изменился хеш — запись нужно переиндексировать.
        sensitive: Тема здоровья: ответ требует осторожной формулировки.
    """

    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(50))
    source_url: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64))
    sensitive: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebhookEvent(Base):
    """Принятое событие вебхука; уникальный event_id даёт идемпотентность при повторной доставке.

    Attributes:
        event_id: Идентификатор события от AmoCRM.
        payload: Тело вебхука как есть.
        status: received, processed, retry или failed.
        error: Текст последней ошибки обработки.
        processed_at: Время успешной обработки.
    """

    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="received")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Suggestion(Base):
    """Сгенерированная подсказка: ответ клиенту и совет менеджеру, с метриками вызова модели.

    Attributes:
        lead_id: Идентификатор сделки в AmoCRM (или демо-диалога).
        client_message: Сообщение клиента, на которое дан ответ.
        reply: Вежливый ответ клиенту.
        upsell_hint: Подсказка менеджеру по допродаже.
        analysis: Скрытое рассуждение модели (только для отладки).
        sources: Идентификаторы и оценки использованных фрагментов базы.
        priority: Признак приоритетной подсказки (клиент выражает намерение купить).
        purchase_intent: none, interest или ready_to_buy.
        needs_escalation: Нужен менеджер или врач.
        warnings: Замечания проверок ответа.
        mode: rag, no_rag или offline.
        cache_hit: Ответ отдан из кеша без вызова модели.
    """

    __tablename__ = "suggestions"
    __table_args__ = (Index("ix_suggestions_created_at", "created_at"), Index("ix_suggestions_lead_id", "lead_id"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lead_id: Mapped[str | None] = mapped_column(String(100))
    client_message: Mapped[str] = mapped_column(Text)
    reply: Mapped[str] = mapped_column(Text)
    upsell_hint: Mapped[str] = mapped_column(Text)
    analysis: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    priority: Mapped[bool] = mapped_column(default=False)
    purchase_intent: Mapped[str] = mapped_column(String(20), default="none")
    needs_escalation: Mapped[bool] = mapped_column(default=False)
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    mode: Mapped[str] = mapped_column(String(20))
    cache_hit: Mapped[bool] = mapped_column(default=False)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Feedback(Base):
    """Оценка менеджера подсказки для последующей правки промптов и базы знаний.

    Attributes:
        suggestion_id: Оцениваемая подсказка.
        rating: 1 (полезно) или -1 (не полезно).
        comment: Комментарий менеджера.
        manager_id: Идентификатор менеджера в AmoCRM.
    """

    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("rating IN (-1, 1)", name="ck_feedback_rating"),
        Index("ix_feedback_suggestion_id", "suggestion_id"),
        Index(
            "uq_feedback_suggestion_manager",
            "suggestion_id",
            "manager_id",
            unique=True,
            postgresql_where=text("manager_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    suggestion_id: Mapped[int] = mapped_column(ForeignKey("suggestions.id", ondelete="CASCADE"))
    rating: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    manager_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Conversation(Base):
    """Диалог клиента с менеджером: данные клиента, статус и служебные поля для входящих.

    Attributes:
        token: Неугадываемый идентификатор, по которому клиент возвращается в свой чат.
        client_name: Имя клиента.
        channel: Канал обращения (web).
        status: new, in_progress, waiting_client, callback или closed.
        contact_method: Способ связи, выбранный клиентом (phone, telegram, whatsapp, max, email, chat).
        contact_value: Номер, ник или адрес почты для связи.
        preferred_time: Удобное время связи.
        contact_comment: Комментарий клиента к запросу связи.
        contact_requested_at: Когда клиент попросил связаться.
        manager_note: Внутренняя заметка менеджера (клиент её не видит).
        unread_by_manager: Сколько сообщений клиента менеджер ещё не открыл.
        last_message_preview: Начало последнего сообщения для списка входящих.
        last_message_at: Время последнего сообщения.
        hot: Клиент готов купить, а менеджер ещё не ответил: диалог помечается в списке и поднимается выше.
    """

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_status_last", "status", "last_message_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    token: Mapped[str] = mapped_column(String(32), unique=True)
    client_name: Mapped[str | None] = mapped_column(String(100))
    channel: Mapped[str] = mapped_column(String(20), default="web")
    status: Mapped[str] = mapped_column(String(20), default="new")
    contact_method: Mapped[str | None] = mapped_column(String(20))
    contact_value: Mapped[str | None] = mapped_column(String(200))
    preferred_time: Mapped[str | None] = mapped_column(String(60))
    contact_comment: Mapped[str | None] = mapped_column(Text)
    contact_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manager_note: Mapped[str] = mapped_column(Text, default="")
    unread_by_manager: Mapped[int] = mapped_column(Integer, default=0)
    last_message_preview: Mapped[str] = mapped_column(String(160), default="")
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    hot: Mapped[bool] = mapped_column(default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatMessage(Base):
    """Сообщение диалога.

    Attributes:
        conversation_id: Диалог, которому принадлежит сообщение.
        sender: client, manager или system.
        text: Текст сообщения.
        suggestion_id: Для сообщения клиента — подсказка, подготовленная ИИ; для сообщения менеджера — подсказка,
            на которой основан ответ.
        suggestion_state: Для сообщения клиента: pending, ready или failed.
        edited: Менеджер изменил текст подсказки перед отправкой.
        auto: Ответ отправил бот в режиме «менеджер ушёл», а не менеджер.
        links: Кнопки-ссылки на страницы сайта под сообщением бота: список ``{title, url}``.
    """

    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_conversation", "conversation_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    sender: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    suggestion_id: Mapped[int | None] = mapped_column(ForeignKey("suggestions.id", ondelete="SET NULL"))
    suggestion_state: Mapped[str | None] = mapped_column(String(10))
    edited: Mapped[bool] = mapped_column(default=False)
    auto: Mapped[bool] = mapped_column(default=False, server_default=false())
    links: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
