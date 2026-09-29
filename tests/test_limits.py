from datetime import UTC, datetime

import pytest
from prometheus_client import REGISTRY

from app.core.errors import LlmUnavailable, RateLimitExceeded
from app.integrations.ratelimit.memory import InMemoryRateLimiter
from app.schemas.analyze import AnalyzeRequest
from app.services.limits import BudgetedAssistant, seconds_until_utc_midnight
from app.services.metering import MeteredAssistant
from tests.fakes import FailingAssistant, FakeAssistant, make_response


def request() -> AnalyzeRequest:
    return AnalyzeRequest(message="Сколько стоит цеолит Макс?")


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_limiter_blocks_after_limit_and_reports_retry_after() -> None:
    limiter = InMemoryRateLimiter()

    decisions = [await limiter.hit("k", limit=2, window_seconds=30) for _ in range(3)]

    assert [d.allowed for d in decisions] == [True, True, False]
    assert 1 <= decisions[-1].retry_after <= 30


async def test_limiter_counts_keys_independently() -> None:
    limiter = InMemoryRateLimiter()

    await limiter.hit("a", limit=1, window_seconds=30)

    assert (await limiter.hit("b", limit=1, window_seconds=30)).allowed


def test_seconds_until_utc_midnight() -> None:
    assert seconds_until_utc_midnight(datetime(2026, 9, 29, 23, 59, 0, tzinfo=UTC)) == 60
    assert seconds_until_utc_midnight(datetime(2026, 9, 29, 0, 0, 0, tzinfo=UTC)) == 86400


async def test_budgeted_assistant_stops_after_daily_limit() -> None:
    inner = FakeAssistant(await make_response())
    assistant = BudgetedAssistant(inner, InMemoryRateLimiter(), daily_limit=2)

    await assistant.analyze(request())
    await assistant.analyze(request())
    with pytest.raises(RateLimitExceeded) as error:
        await assistant.analyze(request())

    assert error.value.scope == "daily" and inner.calls == 2


async def test_metered_assistant_counts_ok_and_tokens() -> None:
    labels = {"mode": "rag", "cache": "miss", "outcome": "ok"}
    before = sample("assistant_requests_total", **labels)
    tokens_before = sample("llm_tokens_total", direction="in", model="fake-model")

    await MeteredAssistant(FakeAssistant(await make_response())).analyze(request())

    assert sample("assistant_requests_total", **labels) == before + 1
    assert sample("llm_tokens_total", direction="in", model="fake-model") == tokens_before + 100


async def test_metered_assistant_counts_failures_and_reraises() -> None:
    before = sample("assistant_requests_total", mode="rag", cache="none", outcome="llm_unavailable")

    with pytest.raises(LlmUnavailable):
        await MeteredAssistant(FailingAssistant()).analyze(request())

    assert sample("assistant_requests_total", mode="rag", cache="none", outcome="llm_unavailable") == before + 1


async def test_metered_assistant_counts_rate_limited() -> None:
    class Limited:
        async def analyze(self, req: AnalyzeRequest):
            raise RateLimitExceeded("daily", 60, "лимит")

    before = sample("rate_limited_total", scope="daily")

    with pytest.raises(RateLimitExceeded):
        await MeteredAssistant(Limited()).analyze(request())

    assert sample("rate_limited_total", scope="daily") == before + 1
