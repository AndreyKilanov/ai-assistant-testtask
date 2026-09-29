from fastapi.testclient import TestClient

from app.bootstrap import Container
from app.core.config import Settings
from app.integrations.ratelimit.memory import InMemoryRateLimiter
from app.main import create_app
from app.services.assistant import AssistantService
from app.services.conversations import ConversationService
from app.services.feedback import FeedbackService
from app.services.limits import BudgetedAssistant
from app.services.metering import MeteredAssistant
from app.services.recording import RecordingAssistant
from app.services.webhooks import WebhookService
from tests.fake_conversations import FakeConversationStore, FakeSuggestionReader
from tests.fakes import (
    MAX_HIT,
    FailingGenerator,
    FakeCrm,
    FakeEvents,
    FakeFeedbackStore,
    FakeQueue,
    FakeRetriever,
    FakeStats,
    FakeStore,
    make_result,
    make_service,
)

SECRET = "test-secret"
MANAGER = "test-manager"
MANAGER_HEADERS = {"X-Manager-Token": MANAGER}
WEBHOOK = {"event_id": "evt-1", "lead_id": "42", "message": "Сколько стоит цеолит Макс?"}


def make_container(
    generator_fails: bool = False, queue: FakeQueue | None = None, **settings_overrides
) -> tuple[Container, FakeQueue, FakeCrm]:
    settings = Settings(
        webhook_secret=SECRET,
        manager_token=MANAGER,
        rag_min_dense_score=0.81,
        **{"demo_mode": False, **settings_overrides},
    )
    if generator_fails:
        core = AssistantService(FakeRetriever([MAX_HIT]), FailingGenerator(), settings)
    else:
        core, *_ = make_service([MAX_HIT], make_result())
    limiter = InMemoryRateLimiter()
    budgeted = BudgetedAssistant(core, limiter, settings.daily_request_limit)
    suggestion_store = FakeStore()
    assistant = MeteredAssistant(RecordingAssistant(budgeted, suggestion_store))
    queue, crm = queue or FakeQueue(), FakeCrm()
    container = Container(
        settings=settings,
        assistant=assistant,
        webhooks=WebhookService(FakeEvents(), queue, assistant, crm),
        rate_limiter=limiter,
        feedback=FeedbackService(FakeFeedbackStore({1, 2, 3})),
        stats=FakeStats(),
        conversations=ConversationService(
            FakeConversationStore(), FakeSuggestionReader(suggestion_store), assistant, crm
        ),
    )
    return container, queue, crm


def make_client(**kwargs) -> TestClient:
    container, *_ = make_container(**kwargs)
    return TestClient(create_app(container), headers=MANAGER_HEADERS)


def test_health() -> None:
    with make_client() as client:
        assert client.get("/health").json()["status"] == "ok"


def test_analyze_returns_two_blocks_sources_and_suggestion_id() -> None:
    with make_client() as client:
        response = client.post("/api/analyze", json={"message": "Сколько стоит цеолит Макс?", "lead_id": "42"})

    body = response.json()
    assert response.status_code == 200
    assert body["reply"] and body["upsell_hint"] and body["suggestion_id"] == 1
    assert body["sources"][0]["entry_id"] == "product-zeolite-max-67"
    assert body["usage"]["tokens_in"] == 100 and body["cache_status"] == "miss"


def test_analyze_validation_errors() -> None:
    with make_client() as client:
        assert client.post("/api/analyze", json={"message": ""}).status_code == 422
        assert client.post("/api/analyze", json={"message": "а" * 2001}).status_code == 422
        bad_role = {"message": "Привет", "history": [{"role": "admin", "text": "x"}]}
        assert client.post("/api/analyze", json=bad_role).status_code == 422
        too_long = {"message": "Привет", "history": [{"role": "client", "text": "x"}] * 21}
        assert client.post("/api/analyze", json=too_long).status_code == 422


def test_llm_unavailable_returns_503_with_retry_after() -> None:
    with make_client(generator_fails=True) as client:
        response = client.post("/api/analyze", json={"message": "Сколько стоит цеолит Макс?"})

    assert response.status_code == 503
    assert response.headers["retry-after"] == "20"
    assert "недоступен" in response.json()["detail"]


def test_webhook_requires_secret() -> None:
    with make_client() as client:
        assert client.post("/webhook/amocrm", json=WEBHOOK).status_code == 401
        assert client.post("/webhook/amocrm", json=WEBHOOK, headers={"X-Webhook-Secret": "wrong"}).status_code == 401


def test_webhook_accepts_then_reports_duplicate() -> None:
    container, queue, _ = make_container()
    headers = {"X-Webhook-Secret": SECRET}

    with TestClient(create_app(container)) as client:
        first = client.post("/webhook/amocrm", json=WEBHOOK, headers=headers)
        second = client.post("/webhook/amocrm", json=WEBHOOK, headers=headers)

    assert (first.status_code, first.json()["status"]) == (202, "accepted")
    assert (second.status_code, second.json()["status"]) == (200, "duplicate")
    assert queue.enqueued == ["evt-1"]


def test_webhook_validates_payload() -> None:
    headers = {"X-Webhook-Secret": SECRET}
    with make_client() as client:
        assert (
            client.post("/webhook/amocrm", json={**WEBHOOK, "event_id": "плохой id!"}, headers=headers).status_code
            == 422
        )
        assert client.post("/webhook/amocrm", json={**WEBHOOK, "message": ""}, headers=headers).status_code == 422


def test_webhook_returns_503_when_queue_is_down() -> None:
    with make_client(queue=FakeQueue(fail=True)) as client:
        response = client.post("/webhook/amocrm", json=WEBHOOK, headers={"X-Webhook-Secret": SECRET})

    assert response.status_code == 503 and response.headers["retry-after"] == "20"


def test_client_rate_limit_returns_429_with_retry_after() -> None:
    body = {"message": "Сколько стоит цеолит Макс?", "lead_id": "spammer"}
    with make_client(client_rate_limit_per_minute=2) as client:
        codes = [client.post("/api/analyze", json=body).status_code for _ in range(3)]
        limited = client.post("/api/analyze", json=body)

    assert codes == [200, 200, 429]
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1


def test_rate_limit_is_per_lead() -> None:
    with make_client(client_rate_limit_per_minute=1) as client:
        first = client.post("/api/analyze", json={"message": "Цена цеолита?", "lead_id": "a"})
        other = client.post("/api/analyze", json={"message": "Цена цеолита?", "lead_id": "b"})
        again = client.post("/api/analyze", json={"message": "Цена цеолита?", "lead_id": "a"})

    assert (first.status_code, other.status_code, again.status_code) == (200, 200, 429)


def test_daily_budget_exhausted_returns_429() -> None:
    with make_client(daily_request_limit=1) as client:
        first = client.post("/api/analyze", json={"message": "Цена цеолита?"})
        second = client.post("/api/analyze", json={"message": "Есть ли доставка?"})

    assert first.status_code == 200
    assert second.status_code == 429 and "дневной лимит" in second.json()["detail"].lower()


def test_feedback_saved_and_unknown_suggestion_is_404() -> None:
    with make_client() as client:
        ok = client.post("/api/feedback", json={"suggestion_id": 1, "rating": -1, "comment": "Неверная цена"})
        missing = client.post("/api/feedback", json={"suggestion_id": 999, "rating": 1})

    assert ok.status_code == 200 and ok.json() == {"feedback_id": 1, "status": "saved"}
    assert missing.status_code == 404


def test_feedback_validation() -> None:
    with make_client() as client:
        assert client.post("/api/feedback", json={"suggestion_id": 1, "rating": 5}).status_code == 422
        assert client.post("/api/feedback", json={"suggestion_id": 0, "rating": 1}).status_code == 422
        assert (
            client.post("/api/feedback", json={"suggestion_id": 1, "rating": 1, "comment": "я" * 1001}).status_code
            == 422
        )


def test_stats_endpoint() -> None:
    with make_client() as client:
        body = client.get("/api/stats").json()

    assert body["requests_total"] == 10 and body["cache_hit_ratio"] == 0.6 and body["daily_llm_limit"] == 500


def test_metrics_endpoint_exposes_prometheus_text() -> None:
    with make_client() as client:
        client.post("/api/analyze", json={"message": "Сколько стоит цеолит Макс?"})
        text = client.get("/metrics").text

    assert "assistant_requests_total" in text and "llm_tokens_total" in text


def test_client_and_manager_pages_and_assets_are_served() -> None:
    with make_client() as client:
        client_page = client.get("/")
        manager_page = client.get("/manager")
        assets = [
            client.get(path)
            for path in ("/static/common.js", "/static/client.js", "/static/manager.js", "/static/styles.css")
        ]

    assert client_page.status_code == 200 and "Онлайн-консультант" in client_page.text
    assert manager_page.status_code == 200 and "Консоль менеджера" in manager_page.text
    assert all(asset.status_code == 200 for asset in assets)
    unsafe = (".innerHTML", ".outerHTML", "insertAdjacentHTML", "document.write")
    assert not any(marker in asset.text for asset in assets if asset.url.path.endswith(".js") for marker in unsafe)
    assert "Подсказка ИИ" not in client_page.text and "manager.js" not in client_page.text
    assert 'id="new-chat"' in client_page.text and 'id="new-chat-dialog"' in client_page.text


def test_fonts_have_font_mime_type_and_long_cache_while_scripts_revalidate() -> None:
    with make_client() as client:
        font = client.get("/static/fonts/inter-cyrillic-wght-normal.woff2")
        script = client.get("/static/common.js")
        page = client.get("/")

    assert font.status_code == 200 and font.headers["content-type"] == "font/woff2"
    assert "immutable" in font.headers["cache-control"]
    assert script.headers["cache-control"] == "no-cache" and page.headers["cache-control"] == "no-cache"


def test_all_font_subsets_referenced_by_css_exist() -> None:
    import re

    with make_client() as client:
        css = client.get("/static/styles.css").text
        urls = re.findall(r'url\("(/static/fonts/[^"]+)"\)', css)

        assert len(urls) == 3
        assert all(client.get(url).status_code == 200 for url in urls)


def test_ai_and_manager_endpoints_require_manager_token() -> None:
    container, *_ = make_container()
    with TestClient(create_app(container)) as anonymous:
        checks = [
            anonymous.post("/api/analyze", json={"message": "Привет"}),
            anonymous.post("/api/feedback", json={"suggestion_id": 1, "rating": 1}),
            anonymous.get("/api/stats"),
            anonymous.get("/api/manager/conversations"),
            anonymous.get("/api/manager/session"),
        ]
        wrong = anonymous.get("/api/manager/session", headers={"X-Manager-Token": "wrong"})
        allowed = anonymous.get("/api/manager/session", headers=MANAGER_HEADERS)

    assert [r.status_code for r in checks] == [401] * 5
    assert wrong.status_code == 401 and allowed.status_code == 200


def test_client_chat_flow_end_to_end_with_manager_reply() -> None:
    container, *_ = make_container()
    with TestClient(create_app(container)) as public:
        started = public.post(
            "/api/chat/conversations", json={"client_name": "Анна", "text": "Сколько стоит цеолит Макс?"}
        )
        token = started.json()["token"]
        listing = public.get(f"/api/chat/conversations/{token}/messages?after=0").json()

        manager = TestClient(create_app(container), headers=MANAGER_HEADERS)
        with manager:
            inbox = manager.get("/api/manager/conversations").json()
            conversation_id = inbox["items"][0]["id"]
            detail = manager.get(f"/api/manager/conversations/{conversation_id}").json()
            reply = manager.post(
                f"/api/manager/conversations/{conversation_id}/messages", json={"text": "Здравствуйте! 7 790 ₽."}
            )
            client_view = public.get(f"/api/chat/conversations/{token}/messages?after=0").json()

    assert started.status_code == 201 and len(token) == 32
    assert [m["sender"] for m in listing["messages"]] == ["client"] and set(listing["messages"][0]) == {
        "id",
        "sender",
        "text",
        "created_at",
        "auto",
        "actions",
        "links",
    }
    assert inbox["items"][0]["unread"] == 1 and inbox["items"][0]["status"] == "new"
    assert detail["status"] == "in_progress" and detail["client"]["name"] == "Анна"
    assert detail["suggestion_state"] == "ready" and detail["suggestion"]["reply"]
    assert reply.status_code == 201 and reply.json()["sender"] == "manager"
    assert [m["sender"] for m in client_view["messages"]] == ["client", "manager"]
    assert client_view["status"] == "waiting_client"
    assert "suggestion" not in str(client_view) and "upsell" not in str(client_view)


def test_client_cannot_read_other_conversation_and_bad_tokens_are_rejected() -> None:
    with make_client() as client:
        unknown = client.get(f"/api/chat/conversations/{'0' * 32}")
        malformed = client.get("/api/chat/conversations/not-a-token")
        empty = client.post("/api/chat/conversations", json={"text": ""})

    assert unknown.status_code == 404 and malformed.status_code == 422 and empty.status_code == 422


def test_contact_request_marks_callback_and_validates_contact() -> None:
    with make_client() as client:
        token = client.post("/api/chat/conversations", json={"text": "Хочу заказать"}).json()["token"]
        bad = client.post(
            f"/api/chat/conversations/{token}/contact-request", json={"name": "Анна", "method": "email", "value": "нет"}
        )
        ok = client.post(
            f"/api/chat/conversations/{token}/contact-request",
            json={"name": "Анна", "method": "telegram", "value": "@anna_test", "preferred_time": "Сегодня"},
        )
        card = client.get("/api/manager/conversations/1").json()
        session = client.get(f"/api/chat/conversations/{token}").json()

    assert bad.status_code == 422 and ok.status_code == 200
    assert card["status"] == "callback" and card["client"]["contact_value"] == "@anna_test"
    assert session["contact_requested"] is True and "@anna_test" not in str(session)


def test_manager_can_change_status_write_note_and_regenerate_suggestion() -> None:
    with make_client() as client:
        client.post("/api/chat/conversations", json={"text": "Привет"})
        status_changed = client.post("/api/manager/conversations/1/status", json={"status": "closed"})
        bad_status = client.post("/api/manager/conversations/1/status", json={"status": "выдуманный"})
        noted = client.put("/api/manager/conversations/1/note", json={"note": "Перезвонить"})
        regenerated = client.post("/api/manager/conversations/1/suggestion")
        missing = client.get("/api/manager/conversations/999")

    assert status_changed.json()["status"] == "closed" and bad_status.status_code == 422
    assert noted.status_code == 200 and regenerated.json()["reply"]
    assert missing.status_code == 404


def test_client_chat_is_rate_limited_per_conversation() -> None:
    with make_client(client_rate_limit_per_minute=2) as client:
        token = client.post("/api/chat/conversations", json={"text": "1"}).json()["token"]
        codes = [
            client.post(f"/api/chat/conversations/{token}/messages", json={"text": "вопрос"}).status_code
            for _ in range(3)
        ]

    assert codes == [201, 201, 429]


def test_demo_mode_is_off_by_default_and_hides_manager_token() -> None:
    with make_client() as client:
        config = client.get("/api/demo/config")
        session = client.post("/api/demo/manager-session")

    assert config.json() == {"enabled": False}
    assert session.status_code == 404 and MANAGER not in session.text


def test_demo_mode_gives_manager_session_and_config() -> None:
    with make_client(demo_mode=True) as client:
        config = client.get("/api/demo/config")
        session = client.post("/api/demo/manager-session")
        with TestClient(client.app) as anonymous:
            works = anonymous.get("/api/manager/session", headers={"X-Manager-Token": session.json()["token"]})

    assert config.json() == {"enabled": True}
    assert session.status_code == 200 and works.status_code == 200


def test_manager_detail_exposes_client_token_only_in_demo_mode() -> None:
    for demo in (False, True):
        with make_client(demo_mode=demo) as client:
            token = client.post("/api/chat/conversations", json={"text": "Привет"}).json()["token"]
            detail = client.get("/api/manager/conversations/1").json()

        assert detail["client_token"] == (token if demo else None)


def test_demo_switcher_is_wired_into_both_pages_and_navigates_with_plain_links() -> None:
    with make_client() as client:
        client_page, manager_page = client.get("/").text, client.get("/manager").text
        script = client.get("/static/demo.js").text

    assert "/static/demo.js" in client_page and "/static/demo.js" in manager_page
    assert "href: view.path" in script and 'path: "/manager"' in script and 'path: "/"' in script
    assert 'id="login"' not in manager_page and 'id="demo-login"' not in manager_page


def test_away_mode_toggle_is_manager_only_and_bot_answers_clients() -> None:
    with make_client() as client:
        with TestClient(client.app) as anonymous:
            denied = anonymous.put("/api/manager/away", json={"enabled": True})
        before = client.get("/api/manager/away").json()
        turned_on = client.put("/api/manager/away", json={"enabled": True}).json()
        started = client.post("/api/chat/conversations", json={"text": "Сколько стоит цеолит Макс?"}).json()
        token = started["token"]
        poll = client.get(f"/api/chat/conversations/{token}/messages?after=0").json()
        messages = poll["messages"]
        turned_off = client.put("/api/manager/away", json={"enabled": False}).json()

    assert denied.status_code == 401
    assert before == {"enabled": False} and turned_on == {"enabled": True} and turned_off == {"enabled": False}
    assert [(m["sender"], m["auto"]) for m in messages] == [("client", False), ("manager", True)]
    assert started["bot_mode"] is True and poll["bot_mode"] is True
    assert messages[1]["links"] and messages[1]["links"][0]["url"].startswith("https://o-complex.com/product/")


def test_contact_request_accepts_max_messenger_with_phone_number() -> None:
    with make_client() as client:
        token = client.post("/api/chat/conversations", json={"text": "Хочу заказать"}).json()["token"]
        url = f"/api/chat/conversations/{token}/contact-request"
        bad = client.post(url, json={"name": "Анна", "method": "max", "value": "нет"})
        ok = client.post(url, json={"name": "Анна", "method": "max", "value": "+7 900 000-00-00"})
        card = client.get("/api/manager/conversations/1").json()

    assert bad.status_code == 422 and ok.status_code == 200
    assert card["client"]["contact_method"] == "max"


def test_turning_bot_on_answers_client_who_was_waiting_for_the_manager() -> None:
    with make_client() as client:
        token = client.post("/api/chat/conversations", json={"text": "Сколько стоит цеолит Макс?"}).json()["token"]
        before = client.get(f"/api/chat/conversations/{token}/messages?after=0").json()["messages"]
        client.put("/api/manager/away", json={"enabled": True})
        after = client.get(f"/api/chat/conversations/{token}/messages?after=0").json()["messages"]

    assert [m["sender"] for m in before] == ["client"]
    assert [(m["sender"], m["auto"]) for m in after] == [("client", False), ("manager", True)]
