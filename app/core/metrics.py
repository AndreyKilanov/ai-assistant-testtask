"""Метрики Prometheus: запросы, токены, задержки, лимиты, вебхуки, оценки."""

from prometheus_client import Counter, Histogram

REQUESTS = Counter(
    "assistant_requests_total",
    "Обращения к ассистенту по исходу",
    ["mode", "cache", "outcome"],
)
LATENCY = Histogram(
    "assistant_latency_seconds",
    "Время подготовки подсказки",
    ["cache"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 45),
)
LLM_TOKENS = Counter("llm_tokens_total", "Токены, потраченные на вызовы модели", ["direction", "model"])
RATE_LIMITED = Counter("rate_limited_total", "Обращения, отклонённые лимитами", ["scope"])
WEBHOOK_EVENTS = Counter("webhook_events_total", "События вебхука AmoCRM по результату", ["result"])
FEEDBACK = Counter("feedback_total", "Оценки подсказок менеджерами", ["rating"])
CHAT_MESSAGES = Counter("chat_messages_total", "Сообщения чата по автору", ["sender"])
CONTACT_REQUESTS = Counter("contact_requests_total", "Запросы клиентов на связь по способу", ["method"])
