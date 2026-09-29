import httpx
import pytest
from groq import APIError

from app.core.config import Settings
from app.core.errors import LlmUnavailable
from app.domain.generation import GenerationInput, LlmResult
from app.integrations.llm.groq import GroqGenerator

RESULT = LlmResult(
    analysis="Клиент спрашивает цену.",
    reply="Цеолит Макс — 7 790 ₽.",
    upsell_hint="Предложите Минеральный комплекс.",
    purchase_intent="interest",
    needs_escalation=False,
    used_entry_ids=[],
)
DATA = GenerationInput(system="s", user="u", hits=[])


class FakeUsage:
    usage_metadata = {"input_tokens": 120, "output_tokens": 30}


class OkChain:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        return {"raw": FakeUsage(), "parsed": RESULT, "parsing_error": None}


class ApiErrorChain:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        raise APIError("лимит токенов на сутки исчерпан", request=httpx.Request("POST", "http://groq.test"), body=None)


class BadFormatChain:
    async def ainvoke(self, messages):
        return {"raw": FakeUsage(), "parsed": None, "parsing_error": ValueError("не JSON")}


def make(*chains) -> GroqGenerator:
    return GroqGenerator(Settings(groq_model="primary"), chains=list(chains))


async def test_primary_model_answers_when_available() -> None:
    primary, fallback = OkChain(), OkChain()

    output = await make(("primary", primary), ("fallback", fallback)).generate(DATA)

    assert output.model == "primary" and (primary.calls, fallback.calls) == (1, 0)
    assert (output.tokens_in, output.tokens_out) == (120, 30)


async def test_falls_back_when_primary_daily_limit_is_exhausted() -> None:
    primary, fallback = ApiErrorChain(), OkChain()

    output = await make(("primary", primary), ("fallback", fallback)).generate(DATA)

    assert output.model == "fallback" and (primary.calls, fallback.calls) == (1, 1)


async def test_falls_back_when_primary_returns_wrong_format() -> None:
    output = await make(("primary", BadFormatChain()), ("fallback", OkChain())).generate(DATA)

    assert output.model == "fallback"


async def test_raises_when_all_models_fail() -> None:
    with pytest.raises(LlmUnavailable, match="временно недоступен"):
        await make(("primary", ApiErrorChain()), ("fallback", ApiErrorChain())).generate(DATA)


async def test_raises_format_error_when_only_format_is_wrong() -> None:
    with pytest.raises(LlmUnavailable, match="неожиданном формате"):
        await make(("primary", BadFormatChain())).generate(DATA)


def test_default_fallback_model_is_configured() -> None:
    assert Settings().groq_fallback_model == "openai/gpt-oss-120b"


async def test_selected_model_answers_first_and_others_stay_as_fallbacks() -> None:
    primary, second, third = OkChain(), OkChain(), ApiErrorChain()
    generator = make(("primary", primary), ("second", second), ("third", third))

    async def choose() -> str:
        return "third"

    generator.selector = choose
    output = await generator.generate(DATA)

    assert output.model == "primary"  # выбранная третья исчерпана, ответила первая из оставшихся
    assert (third.calls, primary.calls, second.calls) == (1, 1, 0)
    assert generator.model_names == ["primary", "second", "third"]


async def test_default_order_is_used_when_nothing_is_selected() -> None:
    primary, second = OkChain(), OkChain()
    generator = make(("primary", primary), ("second", second))

    async def nothing() -> None:
        return None

    generator.selector = nothing

    assert (await generator.generate(DATA)).model == "primary"


def test_parse_retry_after_understands_groq_messages() -> None:
    from app.integrations.llm.groq import parse_retry_after

    assert parse_retry_after("Limit 200000. Please try again in 10m43.248s. Need more tokens?") == 644
    assert parse_retry_after("try again in 1h2m3s") == 3724
    assert parse_retry_after("try again in 5.5s") == 6
    assert parse_retry_after("что-то другое") is None


async def test_each_model_outcome_is_reported() -> None:
    generator = make(("primary", ApiErrorChain()), ("bad", BadFormatChain()), ("good", OkChain()))
    reports: list[tuple[str, str]] = []

    async def reporter(model: str, state: str, retry_after: int | None) -> None:
        reports.append((model, state))

    generator.reporter = reporter
    await generator.generate(DATA)

    assert reports == [("primary", "unavailable"), ("bad", "bad_format"), ("good", "ok")]
