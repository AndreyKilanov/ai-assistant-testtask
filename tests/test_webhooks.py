import pytest

from app.core.errors import LlmUnavailable, QueueUnavailable
from app.schemas.webhook import AmoWebhookPayload
from app.services.webhooks import WebhookService, format_crm_note
from tests.fakes import FailingAssistant, FakeAssistant, FakeCrm, FakeEvents, FakeQueue, make_response

PAYLOAD = AmoWebhookPayload(event_id="evt-1", lead_id="lead-9", message="Сколько стоит цеолит Макс?")


async def make_service(**overrides) -> tuple[WebhookService, FakeEvents, FakeQueue, FakeCrm, FakeAssistant]:
    events, queue, crm = FakeEvents(), overrides.pop("queue", FakeQueue()), overrides.pop("crm", FakeCrm())
    assistant = overrides.pop("assistant", FakeAssistant(await make_response(purchase_intent="ready_to_buy")))
    return WebhookService(events, queue, assistant, crm), events, queue, crm, assistant


async def test_accept_new_event_enqueues_it() -> None:
    service, events, queue, *_ = await make_service()

    assert await service.accept(PAYLOAD) == "accepted"
    assert queue.enqueued == ["evt-1"] and events.records["evt-1"].status == "received"


async def test_duplicate_delivery_is_not_enqueued_twice() -> None:
    service, _, queue, *_ = await make_service()

    await service.accept(PAYLOAD)
    assert await service.accept(PAYLOAD) == "duplicate"
    assert queue.enqueued == ["evt-1"]


async def test_queue_failure_removes_event_so_redelivery_is_accepted() -> None:
    service, events, *_ = await make_service(queue=FakeQueue(fail=True))

    with pytest.raises(QueueUnavailable):
        await service.accept(PAYLOAD)

    assert "evt-1" not in events.records


async def test_process_writes_note_to_crm_and_marks_processed() -> None:
    service, events, _, crm, assistant = await make_service()
    await service.accept(PAYLOAD)

    await service.process("evt-1")

    assert events.records["evt-1"].status == "processed"
    assert crm.notes[0][0] == "lead-9"
    assert "ПРИОРИТЕТ" in crm.notes[0][1] and "Допродажа" in crm.notes[0][1]
    assert assistant.calls == 1


async def test_process_is_idempotent_for_processed_event() -> None:
    service, _, _, crm, assistant = await make_service()
    await service.accept(PAYLOAD)

    await service.process("evt-1")
    await service.process("evt-1")

    assert assistant.calls == 1 and len(crm.notes) == 1


async def test_process_unknown_event_is_ignored() -> None:
    service, _, _, crm, assistant = await make_service()

    await service.process("нет-такого")

    assert assistant.calls == 0 and crm.notes == []


async def test_llm_failure_marks_retry_then_failed_on_last_attempt() -> None:
    service, events, *_ = await make_service(assistant=FailingAssistant())
    await service.accept(PAYLOAD)

    with pytest.raises(LlmUnavailable):
        await service.process("evt-1", final_attempt=False)
    assert events.records["evt-1"].status == "retry"

    with pytest.raises(LlmUnavailable):
        await service.process("evt-1", final_attempt=True)
    assert events.records["evt-1"].status == "failed"


async def test_crm_failure_marks_failed_and_is_reraised() -> None:
    service, events, *_ = await make_service(crm=FakeCrm(fail=True))
    await service.accept(PAYLOAD)

    with pytest.raises(RuntimeError):
        await service.process("evt-1")

    assert events.records["evt-1"].status == "failed"
    assert "CRM недоступна" in events.errors["evt-1"]


async def test_format_crm_note_lists_used_sources_and_warnings() -> None:
    response = (await make_response()).model_copy(update={"warnings": ["Числа без подтверждения: 4 999"]})

    note = format_crm_note(response)

    assert "Ответ клиенту" in note and "Источники: Цеолит Макс" in note and "Внимание: Числа" in note
