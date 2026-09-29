"""Сценарии диалогов: клиентский чат, входящие менеджера, запрос связи и подсказки ИИ."""

import logging
from datetime import UTC, datetime, timedelta

from app.core.errors import ConversationNotFound, LlmUnavailable, RateLimitExceeded
from app.core.metrics import CHAT_MESSAGES, CONTACT_REQUESTS
from app.domain.conversation_ports import AwayModeStore, ConversationStore, SuggestionReader
from app.domain.conversations import (
    PENDING_TIMEOUT_SECONDS,
    ConversationRecord,
    MessageRecord,
    status_after_client_message,
    status_after_manager_message,
    status_after_open,
)
from app.domain.guardrails import is_callback_request, is_link_request
from app.domain.ports import Assistant, CrmClient
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse, DialogTurn
from app.schemas.chat import (
    ChatMessageOut,
    ClientCard,
    ContactRequestIn,
    ConversationDetail,
    ConversationListOut,
    ConversationSummary,
    ManagerMessageOut,
    MessageLink,
    SuggestionState,
)
from app.integrations.away.memory import InMemoryAwayMode
from app.services.caching import normalize_text
from app.services.links import build_links

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 20
LIST_LIMIT = 100
BACKLOG_HOURS = 24
BACKLOG_LIMIT = 20
CALLBACK_TEXT = (
    "Конечно, передал менеджеру вашу просьбу. Выберите, как вам удобнее связаться, и оставьте контакт: "
    "менеджер свяжется с вами сам."
)
CALLBACK_FOLLOW_UP_TEXT = (
    "Позвонит менеджер, на тот номер, который вы оставите. Выберите способ связи ниже и заполните форму — "
    "так он точно вас найдёт."
)
CALLBACK_KNOWN_TEXT = "Ваша просьба уже у менеджера: он свяжется с вами по оставленному контакту, как только сможет."
CALLBACK_WAIT_TEXT = "Точное время назвать не могу: менеджер позвонит, как только освободится. Контакт у него уже есть."
CALLBACK_WITH_BUTTONS = {CALLBACK_TEXT, CALLBACK_FOLLOW_UP_TEXT}
HANDOFF_TEXT = (
    "Тут мне лучше не гадать: я передал ваше сообщение менеджеру, он ответит здесь, как только вернётся. "
    "Если удобнее, оставьте контакт через кнопку «Связаться с менеджером»."
)
CONTACT_LABELS = {
    "phone": "телефон",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "max": "Max",
    "email": "электронная почта",
    "chat": "ответ в этом чате",
}


def to_client_message(message: MessageRecord) -> ChatMessageOut:
    """Преобразует сообщение в вид, безопасный для клиента (без служебных полей).

    Args:
        message: Сообщение диалога.

    Returns:
        Сообщение для клиентского экрана.
    """
    return ChatMessageOut(
        id=message.id,
        sender=message.sender,
        text=message.text,
        created_at=message.created_at,
        auto=message.auto,
        actions=["contact_methods"] if message.auto and message.text in CALLBACK_WITH_BUTTONS else [],
        links=[MessageLink(**link) for link in message.links],
    )


def to_manager_message(message: MessageRecord) -> ManagerMessageOut:
    """Преобразует сообщение в вид для консоли менеджера.

    Args:
        message: Сообщение диалога.

    Returns:
        Сообщение с идентификатором подсказки и признаком правки.
    """
    return ManagerMessageOut(
        id=message.id,
        sender=message.sender,
        text=message.text,
        created_at=message.created_at,
        auto=message.auto,
        suggestion_id=message.suggestion_id,
        edited=message.edited,
    )


def to_summary(conversation: ConversationRecord) -> ConversationSummary:
    """Строит строку списка входящих.

    Args:
        conversation: Диалог.

    Returns:
        Краткое описание диалога.
    """
    return ConversationSummary(
        id=conversation.id,
        client_name=conversation.client_name,
        status=conversation.status,
        unread=conversation.unread_by_manager,
        last_message_preview=conversation.last_message_preview,
        last_message_at=conversation.last_message_at,
        contact_method=conversation.contact_method,
        callback_requested=conversation.contact_requested_at is not None,
        hot=conversation.hot and conversation.status != "closed",
    )


class ConversationService:
    """Ведёт диалоги клиентов с менеджерами и готовит подсказки ИИ к сообщениям клиентов.

    Attributes:
        store: Хранилище диалогов и сообщений.
        suggestions: Чтение сохранённых подсказок.
        assistant: Ассистент, готовящий подсказку (с кешем, бюджетом, записью и метриками).
        crm: Клиент CRM для заметки о запросе связи.
        away: Общий режим «менеджер ушёл»: пока он включён, на сообщения клиентов отвечает бот.
    """

    def __init__(
        self,
        store: ConversationStore,
        suggestions: SuggestionReader,
        assistant: Assistant,
        crm: CrmClient,
        away: AwayModeStore | None = None,
    ) -> None:
        """Собирает сервис из зависимостей.

        Args:
            store: Хранилище диалогов и сообщений.
            suggestions: Чтение сохранённых подсказок.
            assistant: Ассистент, готовящий подсказку.
            crm: Клиент CRM.
            away: Хранилище режима «менеджер ушёл» (по умолчанию — в памяти, выключен).
        """
        self.away = away or InMemoryAwayMode()
        self.store = store
        self.suggestions = suggestions
        self.assistant = assistant
        self.crm = crm

    async def _by_token(self, token: str) -> ConversationRecord:
        """Находит диалог по клиентскому токену.

        Args:
            token: Токен диалога.

        Returns:
            Диалог.

        Raises:
            ConversationNotFound: Диалога с таким токеном нет.
        """
        conversation = await self.store.get_by_token(token)
        if conversation is None:
            raise ConversationNotFound("Диалог не найден")
        return conversation

    async def _by_id(self, conversation_id: int) -> ConversationRecord:
        """Находит диалог по идентификатору.

        Args:
            conversation_id: Идентификатор диалога.

        Returns:
            Диалог.

        Raises:
            ConversationNotFound: Диалога с таким идентификатором нет.
        """
        conversation = await self.store.get(conversation_id)
        if conversation is None:
            raise ConversationNotFound("Диалог не найден")
        return conversation

    async def start(
        self, client_name: str | None, first_text: str | None = None
    ) -> tuple[ConversationRecord, MessageRecord | None]:
        """Создаёт диалог; если есть первое сообщение, сразу добавляет его.

        Диалог создаётся лениво (с первым сообщением или запросом связи), чтобы во входящих не копились пустые чаты.

        Args:
            client_name: Имя клиента.
            first_text: Первое сообщение клиента.

        Returns:
            Диалог и первое сообщение (None, если его не было).
        """
        conversation = await self.store.create(client_name)
        if first_text is None:
            return conversation, None
        _, message = await self.client_send(conversation.token, first_text)
        return conversation, message

    async def client_send(self, token: str, text: str) -> tuple[ConversationRecord, MessageRecord]:
        """Принимает сообщение клиента.

        Args:
            token: Токен диалога.
            text: Текст сообщения.

        Returns:
            Диалог и добавленное сообщение (подсказку ИИ к нему нужно подготовить отдельно).

        Raises:
            ConversationNotFound: Диалога с таким токеном нет.
        """
        conversation = await self._by_token(token)
        message = await self.store.add_message(
            conversation.id,
            "client",
            text.strip(),
            status=status_after_client_message(conversation.status),
            unread_delta=1,
            suggestion_state="pending",
        )
        CHAT_MESSAGES.labels("client").inc()
        return conversation, message

    async def client_poll(self, token: str, after_id: int) -> tuple[ConversationRecord, list[MessageRecord]]:
        """Возвращает диалог и новые сообщения для клиентского экрана.

        Args:
            token: Токен диалога.
            after_id: Последний известный клиенту идентификатор сообщения.

        Returns:
            Диалог и сообщения с большим идентификатором.

        Raises:
            ConversationNotFound: Диалога с таким токеном нет.
        """
        conversation = await self._by_token(token)
        return conversation, await self.store.list_messages(conversation.id, after_id)

    async def request_contact(self, token: str, payload: ContactRequestIn) -> ConversationRecord:
        """Принимает просьбу клиента связаться с ним и передаёт её менеджеру.

        Контакт сохраняется только в карточке диалога; в переписку и в заметку CRM он не попадает, чтобы не расходиться
        по логам и не уходить в запросы к модели.

        Args:
            token: Токен диалога.
            payload: Данные для связи.

        Returns:
            Обновлённый диалог со статусом ``callback``.

        Raises:
            ConversationNotFound: Диалога с таким токеном нет.
        """
        conversation = await self._by_token(token)
        updated = await self.store.update(
            conversation.id,
            client_name=payload.name.strip(),
            contact_method=payload.method,
            contact_value=payload.value,
            preferred_time=payload.preferred_time,
            contact_comment=payload.comment,
            contact_requested_at=datetime.now(UTC),
            status="callback",
        )
        when = f", удобное время: {payload.preferred_time}" if payload.preferred_time else ""
        await self.store.add_message(
            conversation.id,
            "system",
            f"Запрос на связь передан менеджеру. Способ: {CONTACT_LABELS[payload.method]}{when}.",
            unread_delta=1,
        )
        CONTACT_REQUESTS.labels(payload.method).inc()
        await self.crm.add_note(
            f"chat-{conversation.id}",
            f"Клиент просит связаться (способ: {CONTACT_LABELS[payload.method]}). Контакты — в карточке диалога.",
        )
        return updated or conversation

    async def list_for_manager(self, status: str | None, query: str | None) -> ConversationListOut:
        """Возвращает входящие для менеджера.

        Args:
            status: Фильтр по статусу.
            query: Поиск по имени клиента и началу последнего сообщения.

        Returns:
            Список диалогов (требующие внимания выше) и счётчики по статусам.
        """
        rows, counts = await self.store.list_conversations(status, (query or "").strip() or None, LIST_LIMIT)
        return ConversationListOut(items=[to_summary(row) for row in rows], counts=counts, total=sum(counts.values()))

    async def detail(self, conversation_id: int, expose_client_token: bool = False) -> ConversationDetail:
        """Возвращает диалог целиком и отмечает его прочитанным.

        Args:
            conversation_id: Идентификатор диалога.
            expose_client_token: Добавить токен клиентского чата (нужен только демо-режиму).

        Returns:
            История переписки, карточка клиента и подсказка ИИ к последнему сообщению клиента.

        Raises:
            ConversationNotFound: Диалога с таким идентификатором нет.
        """
        conversation = await self._by_id(conversation_id)
        opened_status = status_after_open(conversation.status)
        if conversation.unread_by_manager or opened_status != conversation.status:
            conversation = (
                await self.store.update(conversation_id, unread_by_manager=0, status=opened_status) or conversation
            )

        messages = await self.store.list_messages(conversation_id)
        both, client_count = await self.store.count_messages(conversation_id)
        latest = await self.store.latest_client_message(conversation_id)
        state, suggestion = await self._suggestion_for(latest)
        return ConversationDetail(
            id=conversation.id,
            status=conversation.status,
            client=ClientCard(
                name=conversation.client_name,
                channel=conversation.channel,
                contact_method=conversation.contact_method,
                contact_value=conversation.contact_value,
                preferred_time=conversation.preferred_time,
                contact_comment=conversation.contact_comment,
                contact_requested_at=conversation.contact_requested_at,
                created_at=conversation.created_at,
                messages_count=both,
                client_messages_count=client_count,
            ),
            messages=[to_manager_message(message) for message in messages],
            manager_note=conversation.manager_note,
            suggestion_state=state,
            suggestion=suggestion,
            client_token=conversation.token if expose_client_token else None,
        )

    async def _suggestion_for(self, message: MessageRecord | None) -> tuple[SuggestionState, AnalyzeResponse | None]:
        """Определяет состояние подсказки к сообщению клиента и загружает её.

        Args:
            message: Последнее сообщение клиента.

        Returns:
            Пара (состояние, подсказка). Зависшая обработка (сервис перезапускался) считается сбоем.
        """
        if message is None or message.suggestion_state is None:
            return "none", None
        if message.suggestion_state == "pending":
            age = (datetime.now(UTC) - message.created_at).total_seconds()
            return ("failed" if age > PENDING_TIMEOUT_SECONDS else "pending"), None
        if message.suggestion_state == "failed" or message.suggestion_id is None:
            return "failed", None
        suggestion = await self.suggestions.get(message.suggestion_id)
        return ("ready", suggestion) if suggestion else ("failed", None)

    async def manager_send(self, conversation_id: int, text: str, suggestion_id: int | None) -> MessageRecord:
        """Отправляет ответ менеджера клиенту.

        Если ответ основан на подсказке ИИ, сохраняется связь с ней и признак правки текста: по доле неизменённых
        подсказок видно, насколько они полезны.

        Args:
            conversation_id: Идентификатор диалога.
            text: Текст ответа.
            suggestion_id: Подсказка ИИ, на которой основан ответ.

        Returns:
            Добавленное сообщение.

        Raises:
            ConversationNotFound: Диалога с таким идентификатором нет.
        """
        conversation = await self._by_id(conversation_id)
        edited = False
        if suggestion_id is not None:
            suggestion = await self.suggestions.get(suggestion_id)
            if suggestion is None:
                suggestion_id = None
            else:
                edited = normalize_text(text) != normalize_text(suggestion.reply)
        message = await self.store.add_message(
            conversation_id,
            "manager",
            text.strip(),
            status=status_after_manager_message(conversation.status),
            suggestion_id=suggestion_id,
            edited=edited,
        )
        CHAT_MESSAGES.labels("manager").inc()
        return message

    async def set_status(self, conversation_id: int, status: str) -> ConversationRecord:
        """Меняет статус диалога.

        Args:
            conversation_id: Идентификатор диалога.
            status: Новый статус.

        Returns:
            Обновлённый диалог.

        Raises:
            ConversationNotFound: Диалога с таким идентификатором нет.
        """
        fields: dict[str, object] = {"status": status}
        if status == "closed":
            fields["hot"] = False
        updated = await self.store.update(conversation_id, **fields)
        if updated is None:
            raise ConversationNotFound("Диалог не найден")
        return updated

    async def set_note(self, conversation_id: int, note: str) -> ConversationRecord:
        """Сохраняет внутреннюю заметку менеджера.

        Args:
            conversation_id: Идентификатор диалога.
            note: Текст заметки.

        Returns:
            Обновлённый диалог.

        Raises:
            ConversationNotFound: Диалога с таким идентификатором нет.
        """
        updated = await self.store.update(conversation_id, manager_note=note.strip())
        if updated is None:
            raise ConversationNotFound("Диалог не найден")
        return updated

    async def generate_suggestion(
        self, conversation_id: int, message_id: int | None = None, *, raise_errors: bool = False, refresh: bool = False
    ) -> AnalyzeResponse | None:
        """Готовит подсказку ИИ к сообщению клиента и привязывает её к сообщению.

        Args:
            conversation_id: Идентификатор диалога.
            message_id: Сообщение клиента (по умолчанию — последнее).
            raise_errors: Пробрасывать ли ошибки модели и лимитов (для ручного запроса); в фоне они только
                логируются, а сообщение получает состояние ``failed``.
            refresh: Не брать ответ из кеша (ручное обновление подсказки).

        Returns:
            Подготовленная подсказка или None, если её не удалось получить.

        Raises:
            LlmUnavailable: Модель недоступна (только при ``raise_errors``).
            RateLimitExceeded: Исчерпан дневной бюджет (только при ``raise_errors``).
        """
        target = (
            await self.store.get_message(message_id)
            if message_id is not None
            else await self.store.latest_client_message(conversation_id)
        )
        if target is None or target.conversation_id != conversation_id or target.sender != "client":
            return None
        earlier = [m for m in await self.store.list_messages(conversation_id) if m.id < target.id]
        history = [DialogTurn(role=m.sender, text=m.text) for m in earlier if m.sender in {"client", "manager"}]
        request = AnalyzeRequest(
            message=target.text, history=history[-HISTORY_LIMIT:], lead_id=f"chat-{conversation_id}", refresh=refresh
        )
        await self.store.set_message_suggestion(target.id, None, "pending")
        try:
            response = await self.assistant.analyze(request)
        except (LlmUnavailable, RateLimitExceeded) as exc:
            await self.store.set_message_suggestion(target.id, None, "failed")
            logger.warning("Подсказка к сообщению %s не подготовлена: %s", target.id, exc)
            if raise_errors:
                raise
            return None
        except Exception:
            await self.store.set_message_suggestion(target.id, None, "failed")
            logger.exception("Сбой при подготовке подсказки к сообщению %s", target.id)
            if raise_errors:
                raise
            return None
        if response.suggestion_id is None:
            await self.store.set_message_suggestion(target.id, None, "failed")
            return None
        await self.store.set_message_suggestion(target.id, response.suggestion_id, "ready")
        latest = await self.store.latest_client_message(conversation_id)
        if response.priority and latest is not None and latest.id == target.id:
            await self.store.update(conversation_id, hot=True)
        return response

    async def process_client_message(
        self, conversation_id: int, message_id: int, *, reuse_suggestion: bool = False
    ) -> None:
        """Готовит подсказку к сообщению клиента и, если менеджер ушёл, отвечает клиенту сам.

        Бот отправляет ответ модели только когда он безопасен: база знаний нашла опору, нет предупреждений проверок,
        нет эскалации (здоровье, врач) и клиент не «готов купить» (такого клиента должен вести человек). Иначе клиент
        получает нейтральное сообщение о передаче менеджеру, а подсказка ждёт менеджера в консоли как обычно.

        Args:
            conversation_id: Идентификатор диалога.
            message_id: Сообщение клиента.
            reuse_suggestion: Взять уже готовую подсказку к сообщению, а не генерировать новую (разбор очереди).
        """
        target = await self.store.get_message(message_id)
        response = None
        if reuse_suggestion and target is not None and target.suggestion_state == "ready" and target.suggestion_id:
            response = await self.suggestions.get(target.suggestion_id)
        if response is None:
            response = await self.generate_suggestion(conversation_id, message_id)
        try:
            target = await self.store.get_message(message_id)
            conversation = await self.store.get(conversation_id)
            follow_up = conversation is not None and conversation.status == "callback"
            callback = target is not None and is_callback_request(target.text, follow_up)
            if callback:
                await self.store.update(conversation_id, status="callback")
            if not await self.away.is_enabled():
                return
            await self._auto_reply(conversation_id, message_id, response, callback)
        except Exception:
            logger.exception("Сбой автоответа в диалоге %s", conversation_id)

    async def _auto_reply(
        self, conversation_id: int, message_id: int, response: AnalyzeResponse | None, callback: bool = False
    ) -> None:
        """Отправляет клиенту ответ бота или сообщение о передаче менеджеру.

        Args:
            conversation_id: Идентификатор диалога.
            message_id: Сообщение клиента, на которое отвечаем.
            response: Подсказка к сообщению (None, если её не удалось подготовить).
            callback: Клиент просит, чтобы ему позвонили: вместо ответа модели отправляется фиксированный ответ.
        """
        conversation = await self.store.get(conversation_id)
        if conversation is None:
            return
        messages = await self.store.list_messages(conversation_id)
        client_indexes = [i for i, m in enumerate(messages) if m.sender == "client"]
        target_index = next((i for i, m in enumerate(messages) if m.id == message_id), None)
        if target_index is None or target_index != client_indexes[-1]:
            return  # клиент уже написал ещё раз: ответим на последнее сообщение
        if any(m.sender == "manager" for m in messages[target_index + 1 :]):
            return  # менеджер ответил сам, пока готовилась подсказка
        previous = next((m for m in reversed(messages[:target_index]) if m.sender != "system"), None)
        said = previous.text if previous is not None and previous.auto else None
        contact_known = conversation.contact_requested_at is not None
        fixed = None
        if callback:
            # клиент переспрашивает («куда звонить?»): второй раз тот же текст не повторяем
            if contact_known:
                first, again = CALLBACK_KNOWN_TEXT, CALLBACK_WAIT_TEXT
            else:
                first, again = CALLBACK_TEXT, CALLBACK_FOLLOW_UP_TEXT
            fixed = again if said == first else first
        elif response is None or response.suggestion_id is None or not self._is_safe_for_auto(response):
            fixed = HANDOFF_TEXT
        if fixed is None:
            text, suggestion_id = response.reply, response.suggestion_id
        else:
            if said == fixed:
                return  # клиента уже предупредили
            text, suggestion_id = fixed, None
        # Горячий клиент остаётся «новым», чтобы менеджер увидел его первым, когда вернётся
        hot = (
            not callback
            and conversation.status != "callback"
            and response is not None
            and response.purchase_intent == "ready_to_buy"
        )
        await self.store.add_message(
            conversation_id,
            "manager",
            text,
            status="new" if hot else status_after_manager_message(conversation.status),
            suggestion_id=suggestion_id,
            auto=True,
            links=build_links(response, is_link_request(messages[target_index].text), messages[target_index].text)
            if fixed is None and response is not None
            else None,
        )
        CHAT_MESSAGES.labels("manager").inc()

    @staticmethod
    def _is_safe_for_auto(response: AnalyzeResponse) -> bool:
        """Проверяет, что подсказку можно отправить клиенту без человека.

        Args:
            response: Подсказка ИИ.

        Returns:
            True, если ответ основан на базе знаний и в нём нет замечаний проверок (числа без опоры, тема здоровья) и
            пометки «нужен менеджер».
        """
        return response.mode == "rag" and not response.needs_escalation and not response.warnings

    async def answer_backlog(self) -> None:
        """Отвечает на сообщения клиентов, которые ждали менеджера, когда включили режим «Ассистент».

        Берёт диалоги, где последнее сообщение — клиента, не старше суток; готовую подсказку использует повторно, чтобы не
        тратить запросы к модели. Если менеджер вернулся, пока идёт разбор, останавливается.
        """
        since = datetime.now(UTC) - timedelta(hours=BACKLOG_HOURS)
        for conversation_id, message_id in await self.store.unanswered_client_messages(since, BACKLOG_LIMIT):
            if not await self.away.is_enabled():
                return
            await self.process_client_message(conversation_id, message_id, reuse_suggestion=True)
