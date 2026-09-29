import asyncio

import pytest

from app.core.errors import LlmUnavailable
from app.integrations.cache.memory import InMemoryResponseCache
from app.schemas.analyze import AnalyzeRequest, DialogTurn
from app.services.caching import CachingAssistant, build_cache_key, normalize_text
from app.services.recording import RecordingAssistant
from tests.fakes import FakeAssistant, FakeStore, make_response


def make_caching(inner: FakeAssistant, ttl: int = 60, turns: int = 2) -> CachingAssistant:
    return CachingAssistant(inner, InMemoryResponseCache(), namespace="v1:m:kb1", ttl_seconds=ttl, history_turns=turns)


def request(message: str, history: list[DialogTurn] | None = None, **extra) -> AnalyzeRequest:
    return AnalyzeRequest(message=message, history=history or [], **extra)


def test_normalize_text_ignores_case_spaces_and_trailing_punctuation() -> None:
    assert normalize_text("  Сколько   СТОИТ цеолит?!") == normalize_text("сколько стоит цеолит")


def test_cache_key_ignores_lead_id_but_not_mode_or_namespace() -> None:
    base = build_cache_key(request("Цена?", lead_id="1"), "ns", 2)

    assert base == build_cache_key(request("цена", lead_id="2"), "ns", 2)
    assert base != build_cache_key(request("Цена?", mode="no_rag"), "ns", 2)
    assert base != build_cache_key(request("Цена?"), "other-ns", 2)


def test_cache_key_uses_only_recent_history_turns() -> None:
    old = DialogTurn(role="client", text="Давнее сообщение")
    recent = [DialogTurn(role="client", text="Вопрос"), DialogTurn(role="manager", text="Ответ")]

    assert build_cache_key(request("Цена?", [old, *recent]), "ns", 2) == build_cache_key(
        request("Цена?", recent), "ns", 2
    )


def test_spammer_repeating_same_question_gets_same_key_despite_growing_history() -> None:
    q = DialogTurn(role="client", text="Сколько стоит цеолит?")
    a = DialogTurn(role="manager", text="Скоро отвечу")
    short = [q, a]
    long = [q, a, q, a, q, a]

    assert build_cache_key(request("Сколько стоит цеолит?", short), "ns", 2) == build_cache_key(
        request("Сколько стоит цеолит?", long), "ns", 2
    )


async def test_second_identical_question_is_served_from_cache() -> None:
    inner = FakeAssistant(await make_response())
    assistant = make_caching(inner)

    first = await assistant.analyze(request("Сколько стоит цеолит Макс?"))
    second = await assistant.analyze(request("сколько стоит цеолит макс"))

    assert inner.calls == 1
    assert first.cache_status == "miss" and second.cache_status == "hit"
    assert second.reply == first.reply
    assert second.usage.tokens_in == 0 and second.usage.tokens_out == 0


async def test_refresh_skips_cache_calls_model_again_and_updates_the_cache() -> None:
    inner = FakeAssistant(await make_response())
    assistant = make_caching(inner)

    await assistant.analyze(request("Сколько стоит цеолит Макс?"))
    refreshed = await assistant.analyze(request("Сколько стоит цеолит Макс?", refresh=True))
    after = await assistant.analyze(request("Сколько стоит цеолит Макс?"))

    assert inner.calls == 2
    assert refreshed.cache_status == "miss" and after.cache_status == "hit"


async def test_different_question_is_not_served_from_cache() -> None:
    inner = FakeAssistant(await make_response())
    assistant = make_caching(inner)

    await assistant.analyze(request("Сколько стоит цеолит Макс?"))
    await assistant.analyze(request("Есть ли доставка?"))

    assert inner.calls == 2


async def test_concurrent_identical_requests_call_model_once() -> None:
    inner = FakeAssistant(await make_response(), delay=0.05)
    assistant = make_caching(inner)

    results = await asyncio.gather(*(assistant.analyze(request("Сколько стоит цеолит Макс?")) for _ in range(5)))

    assert inner.calls == 1
    assert sorted(r.cache_status for r in results) == ["hit"] * 4 + ["miss"]


async def test_errors_are_not_cached() -> None:
    class Flaky:
        calls = 0

        async def analyze(self, req: AnalyzeRequest):
            self.calls += 1
            if self.calls == 1:
                raise LlmUnavailable("недоступно")
            return await make_response()

    inner = Flaky()
    assistant = make_caching(inner)

    with pytest.raises(LlmUnavailable):
        await assistant.analyze(request("Сколько стоит цеолит Макс?"))
    retry = await assistant.analyze(request("Сколько стоит цеолит Макс?"))

    assert inner.calls == 2 and retry.cache_status == "miss"


async def test_expired_entry_is_regenerated() -> None:
    inner = FakeAssistant(await make_response())
    assistant = make_caching(inner, ttl=0)

    await assistant.analyze(request("Сколько стоит цеолит Макс?"))
    await asyncio.sleep(0.01)
    await assistant.analyze(request("Сколько стоит цеолит Макс?"))

    assert inner.calls == 2


async def test_recording_assistant_saves_cache_hits_with_own_ids() -> None:
    store = FakeStore()
    inner = FakeAssistant(await make_response())
    assistant = RecordingAssistant(make_caching(inner), store)

    first = await assistant.analyze(request("Сколько стоит цеолит Макс?", lead_id="42"))
    second = await assistant.analyze(request("Сколько стоит цеолит Макс?", lead_id="43"))

    assert (first.suggestion_id, second.suggestion_id) == (1, 2)
    assert [saved.cache_status for saved in store.saved] == ["miss", "hit"]
    assert inner.calls == 1
