"""Схемы чата: клиентская часть (свой диалог) и менеджерская часть (входящие, карточка клиента)."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.analyze import AnalyzeResponse

ConversationStatus = Literal["new", "in_progress", "waiting_client", "callback", "closed"]
ContactMethod = Literal["phone", "telegram", "whatsapp", "max", "email", "chat"]
Sender = Literal["client", "manager", "system"]
SuggestionState = Literal["none", "pending", "ready", "failed"]

PHONE_MIN_DIGITS = 10
PHONE_MAX_DIGITS = 15
TELEGRAM_RE = re.compile(r"^@?[A-Za-z0-9_]{5,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


class MessageLink(BaseModel):
    """Кнопка-ссылка на страницу сайта под сообщением бота.

    Attributes:
        title: Подпись кнопки.
        url: Адрес страницы сайта.
    """

    title: str
    url: str


class ChatMessageOut(BaseModel):
    """Сообщение диалога, видимое клиенту.

    Attributes:
        id: Идентификатор сообщения (по нему клиент запрашивает только новые).
        sender: Автор: клиент, менеджер или служебное сообщение.
        text: Текст.
        created_at: Время отправки.
        auto: Ответ отправил бот в режиме «менеджер ушёл» (клиенту это показывается).
        actions: Кнопки под сообщением (``contact_methods`` — выбор способа связи).
        links: Кнопки-ссылки на страницы сайта (товары, каталог, доставка).
    """

    id: int
    sender: Sender
    text: str
    created_at: datetime
    auto: bool = False
    actions: list[str] = Field(default_factory=list)
    links: list[MessageLink] = Field(default_factory=list)


class ClientStartIn(BaseModel):
    """Начало диалога.

    Attributes:
        client_name: Имя клиента, если он его назвал.
        text: Первое сообщение клиента (диалог создаётся вместе с ним).
    """

    client_name: str | None = Field(default=None, min_length=1, max_length=100)
    text: str | None = Field(default=None, min_length=1, max_length=2000)


class ClientSessionOut(BaseModel):
    """Состояние диалога для клиента.

    Attributes:
        token: Идентификатор диалога; клиент хранит его, чтобы вернуться в чат.
        status: Статус диалога.
        contact_requested: Клиент уже просил связаться.
        messages: Сообщения диалога.
        bot_mode: Менеджер ушёл, и на сообщения отвечает бот (клиенту показывается, кого ждать).
    """

    token: str
    status: ConversationStatus
    contact_requested: bool
    messages: list[ChatMessageOut]
    bot_mode: bool = False


class ClientMessageIn(BaseModel):
    """Сообщение клиента.

    Attributes:
        text: Текст сообщения.
    """

    text: str = Field(min_length=1, max_length=2000)


class ContactRequestIn(BaseModel):
    """Просьба клиента связаться с ним.

    Attributes:
        name: Как обращаться к клиенту.
        method: Удобный способ связи.
        value: Номер телефона, ник Telegram или адрес почты (для способа ``chat`` не нужен).
        preferred_time: Удобное время связи.
        comment: Что обсудить.
    """

    name: str = Field(min_length=1, max_length=100)
    method: ContactMethod
    value: str | None = Field(default=None, max_length=200)
    preferred_time: str | None = Field(default=None, max_length=60)
    comment: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def check_contact_value(self) -> "ContactRequestIn":
        """Проверяет, что контакт соответствует выбранному способу связи.

        Returns:
            Запрос с очищенным значением контакта.

        Raises:
            ValueError: Контакт не задан или не похож на номер, ник или адрес почты.
        """
        value = (self.value or "").strip()
        digits = re.sub(r"\D", "", value)
        if self.method == "chat":
            value = ""
        elif self.method in {"phone", "whatsapp", "max"}:
            if not PHONE_MIN_DIGITS <= len(digits) <= PHONE_MAX_DIGITS:
                raise ValueError("Укажите номер телефона: от 10 до 15 цифр")
        elif self.method == "telegram":
            if not (TELEGRAM_RE.match(value) or PHONE_MIN_DIGITS <= len(digits) <= PHONE_MAX_DIGITS):
                raise ValueError("Укажите ник Telegram (например, @name) или номер телефона")
        elif not EMAIL_RE.match(value):
            raise ValueError("Укажите адрес электронной почты")
        self.value = value or None
        return self


class ContactRequestOut(BaseModel):
    """Подтверждение приёма запроса на связь.

    Attributes:
        status: Всегда ``accepted``.
    """

    status: Literal["accepted"] = "accepted"


class ClientPollOut(BaseModel):
    """Новые сообщения диалога.

    Attributes:
        status: Текущий статус диалога.
        messages: Сообщения с идентификатором больше запрошенного.
        bot_mode: Менеджер ушёл, и на сообщения отвечает бот.
    """

    status: ConversationStatus
    messages: list[ChatMessageOut]
    bot_mode: bool = False


class ManagerMessageOut(ChatMessageOut):
    """Сообщение диалога в консоли менеджера.

    Attributes:
        suggestion_id: Подсказка ИИ, связанная с сообщением.
        edited: Менеджер изменил текст подсказки перед отправкой.
    """

    suggestion_id: int | None = None
    edited: bool = False


class ConversationSummary(BaseModel):
    """Строка списка входящих.

    Attributes:
        id: Идентификатор диалога.
        client_name: Имя клиента.
        status: Статус диалога.
        unread: Сколько сообщений клиента не прочитано.
        last_message_preview: Начало последнего сообщения.
        last_message_at: Время последнего сообщения.
        contact_method: Способ связи, если клиент просил связаться.
        callback_requested: Клиент просил связаться.
        hot: Клиент готов купить, а менеджер ещё не ответил.
    """

    id: int
    client_name: str | None
    status: ConversationStatus
    unread: int
    last_message_preview: str
    last_message_at: datetime
    contact_method: ContactMethod | None
    callback_requested: bool
    hot: bool = False


class ConversationListOut(BaseModel):
    """Список входящих.

    Attributes:
        items: Диалоги, требующие внимания выше остальных.
        counts: Число диалогов по статусам (без учёта фильтра).
        total: Всего диалогов.
    """

    items: list[ConversationSummary]
    counts: dict[str, int]
    total: int


class ClientCard(BaseModel):
    """Данные клиента в карточке диалога.

    Attributes:
        name: Имя клиента.
        channel: Канал обращения.
        contact_method: Способ связи.
        contact_value: Номер, ник или почта.
        preferred_time: Удобное время связи.
        contact_comment: Комментарий клиента к запросу связи.
        contact_requested_at: Когда клиент просил связаться.
        created_at: Начало диалога.
        messages_count: Сообщений клиента и менеджера.
        client_messages_count: Сообщений клиента.
    """

    name: str | None
    channel: str
    contact_method: ContactMethod | None
    contact_value: str | None
    preferred_time: str | None
    contact_comment: str | None
    contact_requested_at: datetime | None
    created_at: datetime
    messages_count: int
    client_messages_count: int


class ConversationDetail(BaseModel):
    """Диалог целиком для консоли менеджера.

    Attributes:
        id: Идентификатор диалога.
        status: Статус диалога.
        client: Карточка клиента.
        messages: История переписки.
        manager_note: Внутренняя заметка менеджера.
        suggestion_state: Состояние подсказки ИИ к последнему сообщению клиента.
        suggestion: Подсказка ИИ к последнему сообщению клиента.
        client_token: Токен клиентского чата; отдаётся только в демо-режиме, чтобы открыть диалог на экране клиента.
    """

    id: int
    status: ConversationStatus
    client: ClientCard
    messages: list[ManagerMessageOut]
    manager_note: str
    suggestion_state: SuggestionState
    suggestion: AnalyzeResponse | None
    client_token: str | None = None


class ManagerMessageIn(BaseModel):
    """Ответ менеджера клиенту.

    Attributes:
        text: Текст ответа.
        suggestion_id: Подсказка ИИ, на которой основан ответ (нужна, чтобы отследить правки).
    """

    text: str = Field(min_length=1, max_length=2000)
    suggestion_id: int | None = Field(default=None, gt=0)


class StatusIn(BaseModel):
    """Смена статуса диалога.

    Attributes:
        status: Новый статус.
    """

    status: ConversationStatus


class NoteIn(BaseModel):
    """Внутренняя заметка менеджера.

    Attributes:
        note: Текст заметки (пустая строка очищает заметку).
    """

    note: str = Field(max_length=2000)


class AwayModeIn(BaseModel):
    """Переключение режима «менеджер ушёл».

    Attributes:
        enabled: Бот отвечает на все входящие сам.
    """

    enabled: bool


class AwayModeOut(BaseModel):
    """Состояние режима «менеджер ушёл».

    Attributes:
        enabled: Бот отвечает на все входящие сам.
    """

    enabled: bool
