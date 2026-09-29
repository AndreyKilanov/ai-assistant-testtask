"""Подставные зависимости для тестов сервисов и API."""

from typing import Any

from app.core.config import Settings
from app.core.errors import LlmUnavailable, QueueUnavailable
from app.domain.generation import GenerationInput, LlmOutput, LlmResult
from app.domain.knowledge import Hit
from app.domain.ports import WebhookEventRecord
from app.schemas.analyze import AnalyzeRequest, AnalyzeResponse
from app.services.assistant import AssistantService

MAX_HIT = Hit(
    entry_id="product-zeolite-max-67",
    title="Цеолит Макс (120 пакетиков)",
    category="product",
    sensitive=True,
    answer="Цеолит Макс — 120 пакетиков по 2,5 г. Цена: 7 790 ₽.",
    upsell="Предложите Минеральный комплекс.",
    source_url="https://o-complex.com/product/zeolite-max-67/",
    fused_score=0.0328,
    dense_score=0.9,
    promo_price_rub=6590,
)
DELIVERY_HIT = Hit("dostavka-i-oplata:delivery", "Доставка", "delivery", False, "СДЭК.", "", "https://x", 0.0325, 0.84)
KIT_HIT = Hit(
    "product-planirovanie-beremennosti-42",
    "Набор «Планирование беременности»",
    "kit",
    True,
    "Набор.",
    "",
    "https://x",
    0.03,
    0.88,
)
FAR_HIT = Hit("home:loyalty-program", "Лояльность", "loyalty", False, "Баллы.", "", "https://x", 0.0164, 0.7)


class FakeRetriever:
    def __init__(self, hits: list[Hit]) -> None:
        self.hits = hits
        self.calls: list[list[str]] = []

    def search_many(self, queries: list[str], top_k: int = 5) -> list[Hit]:
        self.calls.append(queries)
        return self.hits


class FakeGenerator:
    model_name = "fake-model"

    def __init__(self, result: LlmResult, mode: str = "llm") -> None:
        self.result = result
        self.mode = mode
        self.received: GenerationInput | None = None
        self.calls = 0

    async def generate(self, data: GenerationInput) -> LlmOutput:
        self.calls += 1
        self.received = data
        return LlmOutput(result=self.result, tokens_in=100, tokens_out=50, model=self.model_name)


class FailingGenerator:
    model_name = "fake-model"
    mode = "llm"

    async def generate(self, data: GenerationInput) -> LlmOutput:
        raise LlmUnavailable("Сервис ИИ временно недоступен")


class FakeStore:
    def __init__(self) -> None:
        self.saved: list[AnalyzeResponse] = []

    async def save(self, lead_id: str | None, client_message: str, response: AnalyzeResponse) -> int | None:
        self.saved.append(response)
        return len(self.saved)


class FakeAssistant:
    """Ассистент со счётчиком вызовов и управляемой задержкой (для проверки кеша и слияния запросов)."""

    def __init__(self, response: AnalyzeResponse, delay: float = 0.0) -> None:
        self.response = response
        self.delay = delay
        self.calls = 0

    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        import asyncio

        self.calls += 1
        await asyncio.sleep(self.delay)
        return self.response


class FakeQueue:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.enqueued: list[str] = []

    async def enqueue_webhook(self, event_id: str) -> None:
        if self.fail:
            raise QueueUnavailable("Очередь обработки временно недоступна")
        self.enqueued.append(event_id)


class FakeEvents:
    def __init__(self) -> None:
        self.records: dict[str, WebhookEventRecord] = {}
        self.errors: dict[str, str | None] = {}

    async def create(self, event_id: str, payload: dict[str, Any]) -> bool:
        if event_id in self.records:
            return False
        self.records[event_id] = WebhookEventRecord(event_id, payload, "received")
        return True

    async def get(self, event_id: str) -> WebhookEventRecord | None:
        return self.records.get(event_id)

    async def set_status(self, event_id: str, status: str, error: str | None = None) -> None:
        record = self.records[event_id]
        self.records[event_id] = WebhookEventRecord(event_id, record.payload, status)
        self.errors[event_id] = error

    async def delete(self, event_id: str) -> None:
        self.records.pop(event_id, None)


class FakeCrm:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.notes: list[tuple[str, str]] = []

    async def add_note(self, lead_id: str, text: str) -> None:
        if self.fail:
            raise RuntimeError("CRM недоступна")
        self.notes.append((lead_id, text))


def make_result(**overrides: Any) -> LlmResult:
    data = {
        "analysis": "Клиент спрашивает цену.",
        "reply": "Цеолит Макс стоит 7 790 ₽, с промокодом 6 590 ₽.",
        "upsell_hint": "Предложите Минеральный комплекс.",
        "purchase_intent": "interest",
        "needs_escalation": False,
        "used_entry_ids": ["product-zeolite-max-67"],
    }
    return LlmResult(**{**data, **overrides})


def make_service(
    hits: list[Hit], result: LlmResult, mode: str = "llm"
) -> tuple[AssistantService, FakeRetriever, FakeGenerator]:
    retriever, generator = FakeRetriever(hits), FakeGenerator(result, mode)
    return AssistantService(retriever, generator, Settings(rag_min_dense_score=0.81)), retriever, generator


async def make_response(**overrides: Any) -> AnalyzeResponse:
    service, *_ = make_service([MAX_HIT], make_result(**overrides))
    return await service.analyze(AnalyzeRequest(message="Сколько стоит цеолит Макс?"))


class FailingAssistant:
    async def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        raise LlmUnavailable("Сервис ИИ временно недоступен")


class FakeFeedbackStore:
    def __init__(self, known_ids: set[int]) -> None:
        self.known_ids = known_ids
        self.saved: list[tuple[int, int, str | None, str | None]] = []

    async def save(self, suggestion_id: int, rating: int, comment: str | None, manager_id: str | None) -> int:
        from app.core.errors import SuggestionNotFound

        if suggestion_id not in self.known_ids:
            raise SuggestionNotFound(f"Подсказка {suggestion_id} не найдена")
        self.saved.append((suggestion_id, rating, comment, manager_id))
        return len(self.saved)


class FakeStats:
    async def today(self):
        from app.schemas.stats import StatsResponse

        return StatsResponse(
            date="2026-09-29",
            requests_total=10,
            cache_hits=6,
            llm_calls=4,
            cache_hit_ratio=0.6,
            tokens_in=8000,
            tokens_out=1200,
            avg_latency_llm_ms=2100.0,
            avg_latency_cache_ms=8.0,
            daily_llm_limit=500,
            feedback_positive=3,
            feedback_negative=1,
        )
