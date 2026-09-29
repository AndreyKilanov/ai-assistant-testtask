import pytest
from fastapi.testclient import TestClient

from app.core.errors import LlmUnavailable, RateLimitExceeded
from app.integrations.llm.health import LlmHealth
from app.schemas.analyze import AnalyzeRequest
from app.services.metering import MeteredAssistant
from tests.fakes import FailingAssistant, FakeAssistant, make_response
from tests.test_api import MANAGER_HEADERS, make_client


def request() -> AnalyzeRequest:
    return AnalyzeRequest(message="Сколько стоит цеолит Макс?")


class Raising:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def analyze(self, req: AnalyzeRequest):
        raise self.error


async def test_state_is_ok_before_any_call_and_shows_configured_models() -> None:
    health = LlmHealth(model="qwen", fallback_model="gpt-oss", prompt_version="v2")

    status = await health.snapshot()

    assert status.state == "ok" and status.model == "qwen" and status.fallback_model == "gpt-oss"
    assert status.last_model is None and status.checked_at is None


async def test_offline_mode_is_reported_regardless_of_history() -> None:
    health = LlmHealth(model="offline", mode="offline")
    await health.record_ok("offline")

    assert (await health.snapshot()).state == "offline"


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (LlmUnavailable("x", "rate_limit"), "rate_limit"),
        (LlmUnavailable("x"), "unavailable"),
        (LlmUnavailable("x", "bad_format"), "unavailable"),
        (RateLimitExceeded("daily", 60, "лимит"), "budget"),
    ],
)
async def test_failures_are_recorded_by_kind_and_success_clears_them(error: Exception, state: str) -> None:
    health = LlmHealth(model="qwen")
    metered = MeteredAssistant(Raising(error), health)

    with pytest.raises((LlmUnavailable, RateLimitExceeded)):
        await metered.analyze(request())
    assert (await health.snapshot()).state == state

    await MeteredAssistant(FakeAssistant(await make_response()), health).analyze(request())
    recovered = await health.snapshot()
    assert recovered.state == "ok" and recovered.last_model == "fake-model"


async def test_cache_hits_do_not_change_the_state() -> None:
    health = LlmHealth(model="qwen")
    await health.record_failure("rate_limit")
    hit = (await make_response()).model_copy(update={"cache_status": "hit"})

    await MeteredAssistant(FakeAssistant(hit), health).analyze(request())

    assert (await health.snapshot()).state == "rate_limit"


async def test_failing_assistant_marks_model_unavailable() -> None:
    health = LlmHealth(model="qwen")

    with pytest.raises(LlmUnavailable):
        await MeteredAssistant(FailingAssistant(), health).analyze(request())

    assert (await health.snapshot()).state == "unavailable"


def test_model_status_endpoint_requires_manager_token() -> None:
    with make_client() as client:
        with TestClient(client.app) as anonymous:
            denied = anonymous.get("/api/manager/model-status")
        allowed = client.get("/api/manager/model-status", headers=MANAGER_HEADERS)

    assert denied.status_code == 401
    assert allowed.status_code == 200 and allowed.json()["state"] == "ok"


async def test_selected_model_is_validated_reset_and_reported() -> None:
    health = LlmHealth(model="qwen", fallback_model="gpt-oss", models=["qwen", "gpt-oss", "gpt-oss-20b"])
    await health.record_ok("qwen")
    await health.record_failure("rate_limit")

    await health.set_selected("gpt-oss-20b")
    chosen = await health.snapshot()
    with pytest.raises(ValueError):
        await health.set_selected("unknown")
    await health.set_selected(None)

    assert chosen.selected == "gpt-oss-20b" and chosen.models == ["qwen", "gpt-oss", "gpt-oss-20b"]
    assert chosen.state == "ok" and chosen.last_model is None  # прежний исход относился к другой модели
    assert await health.get_selected() is None


def test_model_can_be_chosen_over_api_and_unknown_model_is_rejected() -> None:
    with make_client() as client:
        bad = client.put("/api/manager/model", json={"model": "nope"})
        with TestClient(client.app) as anonymous:
            denied = anonymous.put("/api/manager/model", json={"model": None})
        auto = client.put("/api/manager/model", json={"model": None})

    assert bad.status_code == 422 and denied.status_code == 401
    assert auto.status_code == 200 and auto.json()["selected"] is None


async def test_per_model_states_show_limit_countdown_and_expiry() -> None:
    health = LlmHealth(model="a", models=["a", "b", "c", "d"])
    await health.record_model("a", "ok")
    await health.record_model("b", "rate_limit", 600)
    await health.record_model("c", "rate_limit", 60)
    health._per_model["c"]["retry_until"] = "2000-01-01T00:00:00+00:00"  # срок давно прошёл

    states = (await health.snapshot()).per_model

    assert states["a"].state == "ok" and states["a"].checked_at
    assert states["b"].state == "rate_limit" and 590 <= states["b"].retry_in <= 601
    assert states["c"].state == "limit_expired" and states["c"].retry_in is None
    assert states["d"].state == "unknown"
