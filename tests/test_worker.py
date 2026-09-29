from types import SimpleNamespace

import pytest
from arq.worker import Retry

from app.core.errors import LlmUnavailable, RateLimitExceeded
from app.schemas.webhook import AmoWebhookPayload
from app.services.webhooks import WebhookService
from app.workers.arq_worker import RETRY_BASE_SECONDS, process_webhook
from tests.fakes import FakeCrm, FakeEvents, FakeQueue

PAYLOAD = AmoWebhookPayload(event_id="evt-1", lead_id="lead-9", message="Сколько стоит цеолит Макс?")


class RaisingAssistant:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def analyze(self, request):
        raise self.error


async def make_ctx(error: Exception, attempt: int) -> tuple[dict, FakeEvents]:
    events = FakeEvents()
    webhooks = WebhookService(events, FakeQueue(), RaisingAssistant(error), FakeCrm())
    await webhooks.accept(PAYLOAD)
    container = SimpleNamespace(settings=SimpleNamespace(webhook_max_tries=3), webhooks=webhooks)
    return {"container": container, "job_try": attempt}, events


async def test_exhausted_budget_defers_the_retry_until_it_frees_up() -> None:
    ctx, events = await make_ctx(RateLimitExceeded("daily", 3600, "Достигнут дневной лимит"), attempt=1)

    with pytest.raises(Retry) as retry:
        await process_webhook(ctx, "evt-1")

    assert retry.value.defer_score == 3600 * 1000
    assert events.records["evt-1"].status == "retry"


async def test_unavailable_model_retries_with_growing_delay() -> None:
    ctx, _ = await make_ctx(LlmUnavailable("недоступна"), attempt=2)

    with pytest.raises(Retry) as retry:
        await process_webhook(ctx, "evt-1")

    assert retry.value.defer_score == RETRY_BASE_SECONDS * 2 * 1000


async def test_last_attempt_reraises_and_marks_the_event_failed() -> None:
    ctx, events = await make_ctx(RateLimitExceeded("daily", 3600, "Достигнут дневной лимит"), attempt=3)

    with pytest.raises(RateLimitExceeded):
        await process_webhook(ctx, "evt-1")

    assert events.records["evt-1"].status == "failed"
