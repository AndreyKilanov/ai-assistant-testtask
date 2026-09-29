import pytest
from pydantic import ValidationError

from app.core.errors import ConversationNotFound, LlmUnavailable
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse
from app.schemas.chat import ContactRequestIn
from app.integrations.away.memory import InMemoryAwayMode
from app.services.links import CATALOG_URL, build_links
from app.services.conversations import (
    CALLBACK_FOLLOW_UP_TEXT,
    CALLBACK_KNOWN_TEXT,
    CALLBACK_TEXT,
    HANDOFF_TEXT,
    ConversationService,
    to_client_message,
)
from tests.fake_conversations import FakeConversationStore, FakeSuggestionReader
from tests.fakes import FailingAssistant, FakeCrm, make_response


class RecordingAssistantStub:
    """Ассистент, запоминающий запросы и выдающий подсказки с растущим идентификатором."""

    def __init__(self, response: AnalyzeResponse, reader: FakeSuggestionReader) -> None:
        self.response = response
        self.reader = reader
        self.requests: list[AnalyzeRequest] = []

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        self.requests.append(request)
        suggestion_id = len(self.requests)
        stored = self.response.model_copy(update={"suggestion_id": suggestion_id})
        self.reader.items[suggestion_id] = stored
        return stored


async def make_service(assistant=None):
    store, reader, crm = FakeConversationStore(), FakeSuggestionReader(), FakeCrm()
    assistant = assistant or RecordingAssistantStub(await make_response(), reader)
    return ConversationService(store, reader, assistant, crm), store, reader, crm, assistant


def contact(**overrides) -> ContactRequestIn:
    data = {"name": "Анна", "method": "telegram", "value": "@anna_test", "preferred_time": "Сегодня"}
    return ContactRequestIn(**{**data, **overrides})


async def test_first_client_message_creates_new_unread_conversation() -> None:
    service, store, *_ = await make_service()

    conversation, message = await service.start("Анна", "Сколько стоит цеолит Макс?")

    assert message is not None and message.suggestion_state == "pending"
    stored = store.conversations[conversation.id]
    assert stored.status == "new" and stored.unread_by_manager == 1
    assert stored.last_message_preview == "Сколько стоит цеолит Макс?"


async def test_conversation_without_text_stays_empty() -> None:
    service, store, *_ = await make_service()

    _, message = await service.start(None)

    assert message is None and store.messages == []


async def test_unknown_token_raises_not_found() -> None:
    service, *_ = await make_service()

    with pytest.raises(ConversationNotFound):
        await service.client_send("0" * 32, "привет")


async def test_client_poll_returns_only_new_messages() -> None:
    service, *_ = await make_service()
    conversation, first = await service.start(None, "Привет")
    await service.client_send(conversation.token, "Ещё вопрос")

    _, newer = await service.client_poll(conversation.token, first.id)

    assert [m.text for m in newer] == ["Ещё вопрос"]


async def test_manager_open_marks_read_and_takes_new_conversation_into_work() -> None:
    service, store, *_ = await make_service()
    conversation, _ = await service.start(None, "Привет")

    detail = await service.detail(conversation.id)

    assert detail.status == "in_progress" and store.conversations[conversation.id].unread_by_manager == 0


async def test_manager_reply_sets_waiting_client_and_keeps_callback() -> None:
    service, store, *_ = await make_service()
    conversation, _ = await service.start(None, "Привет")

    await service.manager_send(conversation.id, "Здравствуйте!", None)
    assert store.conversations[conversation.id].status == "waiting_client"

    await service.request_contact(conversation.token, contact())
    await service.manager_send(conversation.id, "Позвоню сегодня", None)
    assert store.conversations[conversation.id].status == "callback"


async def test_client_message_reopens_closed_conversation_but_keeps_in_progress() -> None:
    service, store, *_ = await make_service()
    conversation, _ = await service.start(None, "Привет")
    await service.set_status(conversation.id, "closed")

    await service.client_send(conversation.token, "А ещё вопрос")
    assert store.conversations[conversation.id].status == "new"

    await service.set_status(conversation.id, "in_progress")
    await service.client_send(conversation.token, "И ещё")
    assert store.conversations[conversation.id].status == "in_progress"


async def test_contact_request_stores_contact_in_card_but_not_in_messages_or_crm_note() -> None:
    service, store, _, crm, _ = await make_service()
    conversation, _ = await service.start(None, "Хочу заказать")

    await service.request_contact(conversation.token, contact(value="@anna_test", comment="Про опт"))

    stored = store.conversations[conversation.id]
    assert stored.status == "callback" and stored.contact_value == "@anna_test" and stored.client_name == "Анна"
    assert stored.contact_requested_at is not None
    assert all("@anna_test" not in message.text for message in store.messages)
    assert crm.notes and "@anna_test" not in crm.notes[0][1] and "Telegram" in crm.notes[0][1]


async def test_suggestion_is_linked_to_message_and_history_excludes_system_and_target() -> None:
    service, store, _, _, assistant = await make_service()
    conversation, first = await service.start(None, "Здравствуйте, интересует цеолит")
    await service.manager_send(conversation.id, "Добрый день!", None)
    await service.request_contact(conversation.token, contact())
    _, second = await service.client_send(conversation.token, "Сколько стоит цеолит Макс?")

    response = await service.generate_suggestion(conversation.id, second.id)

    assert response is not None and (await store.get_message(second.id)).suggestion_state == "ready"
    request = assistant.requests[-1]
    assert request.message == "Сколько стоит цеолит Макс?" and request.lead_id == f"chat-{conversation.id}"
    assert [(t.role, t.text) for t in request.history] == [
        ("client", "Здравствуйте, интересует цеолит"),
        ("manager", "Добрый день!"),
    ]


async def test_failed_suggestion_is_marked_failed_and_not_raised_in_background_mode() -> None:
    service, store, *_ = await make_service(FailingAssistant())
    conversation, message = await service.start(None, "Привет")

    assert await service.generate_suggestion(conversation.id, message.id) is None
    assert (await store.get_message(message.id)).suggestion_state == "failed"

    with pytest.raises(LlmUnavailable):
        await service.generate_suggestion(conversation.id, message.id, raise_errors=True)


async def test_detail_shows_ready_suggestion_for_latest_client_message() -> None:
    service, *_ = await make_service()
    conversation, message = await service.start("Анна", "Привет")
    await service.generate_suggestion(conversation.id, message.id)

    detail = await service.detail(conversation.id)

    assert detail.suggestion_state == "ready" and detail.suggestion is not None
    assert detail.client.name == "Анна" and detail.client.client_messages_count == 1


async def test_detail_reports_pending_then_failed_after_timeout() -> None:
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta

    service, store, *_ = await make_service()
    conversation, message = await service.start(None, "Привет")
    assert (await service.detail(conversation.id)).suggestion_state == "pending"

    old = datetime.now(UTC) - timedelta(minutes=10)
    store.messages[0] = replace(store.messages[0], created_at=old)

    assert (await service.detail(conversation.id)).suggestion_state == "failed"


async def test_edited_flag_reflects_changes_to_suggested_reply() -> None:
    service, store, reader, *_ = await make_service()
    conversation, message = await service.start(None, "Привет")
    suggestion = await service.generate_suggestion(conversation.id, message.id)

    same = await service.manager_send(conversation.id, suggestion.reply, suggestion.suggestion_id)
    changed = await service.manager_send(conversation.id, suggestion.reply + " Оформим?", suggestion.suggestion_id)
    unknown = await service.manager_send(conversation.id, "Текст", 999)

    assert (same.edited, changed.edited, unknown.edited) == (False, True, False)
    assert unknown.suggestion_id is None


async def test_list_orders_attention_first_and_supports_filter_and_search() -> None:
    service, *_ = await make_service()
    quiet, _ = await service.start("Иван", "Спасибо")
    await service.set_status(quiet.id, "waiting_client")
    fresh, _ = await service.start("Мария", "Хочу цеолит")

    everything = await service.list_for_manager(None, None)
    only_new = await service.list_for_manager("new", None)
    found = await service.list_for_manager(None, "цеолит")

    assert [item.id for item in everything.items] == [fresh.id, quiet.id]
    assert everything.counts == {"new": 1, "waiting_client": 1} and everything.total == 2
    assert [item.id for item in only_new.items] == [fresh.id] and [item.id for item in found.items] == [fresh.id]


async def test_note_is_saved_and_client_view_has_no_service_fields() -> None:
    from app.services.conversations import to_client_message

    service, store, *_ = await make_service()
    conversation, message = await service.start(None, "Привет")

    await service.set_note(conversation.id, "  Позвонить после 18:00  ")

    assert store.conversations[conversation.id].manager_note == "Позвонить после 18:00"
    assert set(to_client_message(message).model_dump()) == {"id", "sender", "text", "created_at", "auto", "actions", "links"}


@pytest.mark.parametrize(
    ("method", "value", "valid"),
    [
        ("phone", "+7 913 123-45-67", True),
        ("phone", "12345", False),
        ("whatsapp", "89131234567", True),
        ("telegram", "@anna_test", True),
        ("telegram", "@a", False),
        ("telegram", "+79131234567", True),
        ("email", "anna@example.com", True),
        ("email", "anna@", False),
        ("chat", None, True),
        ("phone", None, False),
    ],
)
def test_contact_value_is_validated_per_method(method: str, value: str | None, valid: bool) -> None:
    if valid:
        assert ContactRequestIn(name="Анна", method=method, value=value).method == method
    else:
        with pytest.raises(ValidationError):
            ContactRequestIn(name="Анна", method=method, value=value)


async def away_service(response_overrides=None, assistant=None):
    store, reader, crm = FakeConversationStore(), FakeSuggestionReader(), FakeCrm()
    assistant = assistant or RecordingAssistantStub(await make_response(**(response_overrides or {})), reader)
    service = ConversationService(store, reader, assistant, crm, InMemoryAwayMode(enabled=True))
    return service, store


async def test_away_mode_off_leaves_the_reply_to_the_manager() -> None:
    service, store, *_ = await make_service()
    conversation, message = await service.start("Анна", "Сколько стоит цеолит Макс?")

    await service.process_client_message(conversation.id, message.id)

    assert [m.sender for m in store.messages] == ["client"]


async def test_away_mode_sends_safe_reply_and_marks_it_as_bot() -> None:
    service, store = await away_service()
    conversation, message = await service.start("Анна", "Сколько стоит цеолит Макс?")

    await service.process_client_message(conversation.id, message.id)

    reply = store.messages[-1]
    assert reply.sender == "manager" and reply.auto and reply.suggestion_id is not None and not reply.edited
    assert store.conversations[conversation.id].status == "waiting_client"


async def test_away_mode_hands_over_risky_answers_without_repeating_the_notice() -> None:
    service, store = await away_service({"needs_escalation": True})
    conversation, first = await service.start("Анна", "Можно ли цеолит при беременности?")

    await service.process_client_message(conversation.id, first.id)
    _, second = await service.client_send(conversation.token, "Так можно или нет?")
    await service.process_client_message(conversation.id, second.id)

    bot = [m for m in store.messages if m.sender == "manager"]
    assert [m.text for m in bot] == [HANDOFF_TEXT] and bot[0].auto and bot[0].suggestion_id is None


async def test_away_mode_answers_ready_to_buy_client_and_keeps_conversation_new_for_the_manager() -> None:
    service, store = await away_service({"purchase_intent": "ready_to_buy"})
    conversation, message = await service.start("Анна", "Хочу заказать цеолит Макс")

    await service.process_client_message(conversation.id, message.id)

    reply = store.messages[-1]
    assert reply.auto and reply.text != HANDOFF_TEXT and reply.suggestion_id is not None
    assert store.conversations[conversation.id].status == "new"


async def test_away_mode_hands_over_when_model_is_unavailable() -> None:
    service, store = await away_service(assistant=FailingAssistant())
    conversation, message = await service.start("Анна", "Сколько стоит цеолит Макс?")

    await service.process_client_message(conversation.id, message.id)

    assert store.messages[-1].text == HANDOFF_TEXT and store.messages[-1].auto


async def test_away_mode_does_not_talk_over_a_manager_who_already_replied() -> None:
    service, store = await away_service()
    conversation, message = await service.start("Анна", "Сколько стоит цеолит Макс?")
    await service.manager_send(conversation.id, "Здравствуйте, уже отвечаю!", None)

    await service.process_client_message(conversation.id, message.id)

    assert [m.sender for m in store.messages] == ["client", "manager"]


async def test_callback_request_marks_conversation_and_bot_asks_for_contact() -> None:
    service, store = await away_service()
    conversation, message = await service.start("Анна", "Пускай позвонят мне")

    await service.process_client_message(conversation.id, message.id)

    reply = store.messages[-1]
    assert store.conversations[conversation.id].status == "callback"
    assert reply.text == CALLBACK_TEXT and reply.auto and reply.suggestion_id is None
    assert to_client_message(reply).actions == ["contact_methods"]
    assert to_client_message(store.messages[0]).actions == []


async def test_callback_request_after_contact_form_does_not_ask_again() -> None:
    service, store = await away_service()
    conversation, _ = await service.start("Анна", None)
    await service.request_contact(conversation.token, contact())
    _, message = await service.client_send(conversation.token, "Позвоните мне, пожалуйста")

    await service.process_client_message(conversation.id, message.id)

    assert store.messages[-1].text == CALLBACK_KNOWN_TEXT


async def test_callback_request_marks_conversation_even_when_manager_is_present() -> None:
    service, store, *_ = await make_service()
    conversation, message = await service.start("Анна", "Перезвоните мне")

    await service.process_client_message(conversation.id, message.id)

    assert store.conversations[conversation.id].status == "callback"
    assert [m.sender for m in store.messages] == ["client"]


async def test_callback_follow_up_question_gets_a_different_answer_with_buttons() -> None:
    service, store = await away_service()
    conversation, first = await service.start("Анна", "Хочу чтобы со мной связались")
    await service.process_client_message(conversation.id, first.id)
    _, second = await service.client_send(conversation.token, "куда звонить будете?")

    await service.process_client_message(conversation.id, second.id)

    bot = [m for m in store.messages if m.sender == "manager"]
    assert [m.text for m in bot] == [CALLBACK_TEXT, CALLBACK_FOLLOW_UP_TEXT]
    assert to_client_message(bot[1]).actions == ["contact_methods"]
    _, third = await service.client_send(conversation.token, "куда звонить будете?")
    await service.process_client_message(conversation.id, third.id)
    assert len([m for m in store.messages if m.sender == "manager"]) == 3


async def test_bot_reply_carries_link_buttons_to_the_products_it_used() -> None:
    service, store = await away_service()
    conversation, message = await service.start("Анна", "Сколько стоит цеолит Макс?")

    await service.process_client_message(conversation.id, message.id)

    links = to_client_message(store.messages[-1]).links
    assert [(link.title, link.url) for link in links] == [
        ("Цеолит Макс (120 пакетиков)", "https://o-complex.com/product/zeolite-max-67/")
    ]


async def test_ready_to_buy_links_say_order_and_fall_back_to_catalog() -> None:
    response = await make_response(purchase_intent="ready_to_buy")

    assert build_links(response)[0]["title"] == "Заказать: Цеолит Макс (120 пакетиков)"
    assert build_links(response.model_copy(update={"sources": []})) == [
        {"title": "Каталог и заказ на сайте", "url": CATALOG_URL}
    ]


async def test_links_ignore_foreign_hosts_and_unused_sources() -> None:
    response = await make_response()
    foreign = response.sources[0].model_copy(update={"source_url": "https://evil.example/product/x/"})
    unused = response.sources[0].model_copy(update={"used": False})

    assert build_links(response.model_copy(update={"sources": [foreign]})) == []
    assert build_links(response.model_copy(update={"sources": [unused]})) == []


async def test_switching_to_bot_answers_messages_that_waited_for_the_manager() -> None:
    store, reader, crm = FakeConversationStore(), FakeSuggestionReader(), FakeCrm()
    assistant = RecordingAssistantStub(await make_response(), reader)
    away = InMemoryAwayMode()
    service = ConversationService(store, reader, assistant, crm, away)
    conversation, message = await service.start("Анна", "Сколько стоит цеолит Макс?")
    await service.process_client_message(conversation.id, message.id)
    assert [m.sender for m in store.messages] == ["client"]

    await away.set_enabled(True)
    await service.answer_backlog()
    await service.answer_backlog()

    assert [m.sender for m in store.messages] == ["client", "manager"] and store.messages[-1].auto
    assert len(assistant.requests) == 1  # готовая подсказка использована повторно


async def test_link_request_without_product_shows_catalog_button() -> None:
    service, store = await away_service({"used_entry_ids": []})
    conversation, message = await service.start("Анна", "дай ссылку на товар")

    await service.process_client_message(conversation.id, message.id)

    assert [link.title for link in to_client_message(store.messages[-1]).links] == ["Каталог на сайте"]


def test_site_link_registry_matches_pages_by_keywords_and_only_own_site() -> None:
    from app.services.links import load_site_links, match_site_links, site_link_urls

    assert all(url.startswith("https://o-complex.com/") for url in site_link_urls())
    assert len(load_site_links()) >= 8
    assert [link["title"] for link in match_site_links("Как можно оплатить заказ?")] == ["Доставка и оплата"]
    assert [link["title"] for link in match_site_links("Где ваши сертификаты и какой адрес?")] == ["Контакты", "Сертификаты"]
    assert match_site_links("Сколько стоит цеолит Макс?") == []


async def test_bot_shows_payment_page_button_for_payment_question_without_model_help() -> None:
    service, store = await away_service({"used_entry_ids": []})
    conversation, message = await service.start("Анна", "как оплатить?")

    await service.process_client_message(conversation.id, message.id)

    assert [link.url for link in to_client_message(store.messages[-1]).links] == [
        "https://o-complex.com/dostavka-i-oplata/"
    ]


async def hot_service(**overrides):
    reader = FakeSuggestionReader()
    assistant = RecordingAssistantStub(await make_response(**overrides), reader)
    service, store, *_ = await make_service(assistant)
    return service, store


async def test_ready_to_buy_suggestion_marks_conversation_hot_until_manager_replies() -> None:
    service, store = await hot_service(purchase_intent="ready_to_buy")
    conversation, message = await service.start("Сергей", "Беру набор Детокс, как оплатить?")

    await service.generate_suggestion(conversation.id, message.id)

    assert store.conversations[conversation.id].hot
    assert (await service.list_for_manager(None, None)).items[0].hot

    await service.manager_send(conversation.id, "Оформите заказ на сайте", None)

    assert not store.conversations[conversation.id].hot


async def test_regular_suggestion_does_not_mark_conversation_hot() -> None:
    service, store = await hot_service(purchase_intent="interest")
    conversation, message = await service.start("Анна", "Сколько стоит цеолит?")

    await service.generate_suggestion(conversation.id, message.id)

    assert not store.conversations[conversation.id].hot


async def test_hot_conversation_is_listed_above_newer_ones_and_closing_removes_the_mark() -> None:
    service, store = await hot_service(purchase_intent="ready_to_buy")
    hot, message = await service.start("Сергей", "Беру набор Детокс")
    await service.generate_suggestion(hot.id, message.id)
    other, _ = await service.start("Мария", "Привет")

    listed = await service.list_for_manager(None, None)
    assert [item.id for item in listed.items] == [hot.id, other.id]

    await service.set_status(hot.id, "closed")

    assert not store.conversations[hot.id].hot
    assert not any(item.hot for item in (await service.list_for_manager(None, None)).items)
