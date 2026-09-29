"""Настройки приложения: читаются из переменных окружения и файла .env."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация сервиса.

    Attributes:
        database_url: DSN Postgres (asyncpg) с расширением pgvector.
        redis_url: URL Redis для очереди arq и счётчиков лимитов.
        groq_api_key: Ключ Groq API. Пустой ключ включает офлайн-режим без вызова LLM.
        groq_model: Идентификатор основной модели Groq для генерации ответа.
        groq_fallback_model: Запасная модель Groq (со своим суточным лимитом); пустая строка отключает запасную.
        embeddings_url: Адрес сервиса Text Embeddings Inference (HuggingFace TEI).
        embedding_model: Модель эмбеддингов, которую обслуживает TEI.
        embedding_dim: Размерность вектора выбранной модели эмбеддингов.
        rag_min_dense_score: Порог косинусной близости, ниже которого обращение считается вне базы знаний.
        webhook_secret: Общий секрет для проверки входящих вебхуков AmoCRM.
        daily_request_limit: Максимум обращений к LLM в сутки (для бесплатного Groq ~150: около 2 тыс. токенов на
            запрос при суточном лимите 200 тыс. токенов на модель).
        prompt_version: Версия набора промптов из каталога prompts/.
        cache_ttl_seconds: Время жизни закешированного ответа.
        cache_history_turns: Сколько последних реплик диалога входит в ключ кеша.
        webhook_max_tries: Сколько раз worker пробует обработать вебхук при недоступности модели.
        client_rate_limit_per_minute: Сколько обращений в минуту допускается от одного лида (от IP — втрое больше).
        worker_metrics_port: Порт HTTP-сервера метрик Prometheus у worker'а.
        manager_token: Код доступа менеджера к консоли и ИИ-эндпоинтам (заголовок ``X-Manager-Token``).
        groq_extra_models: Дополнительные модели Groq через запятую: выбираются в консоли менеджера и служат запасными
            (у каждой модели свой суточный лимит токенов).
        demo_mode: Демо-режим: переключатель экранов и автоматический вход в консоль (только для локальной
            демонстрации; отдаёт код менеджера без ввода).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    redis_url: str = "redis://localhost:6379/0"
    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "qwen/qwen3.8-27b"
    groq_fallback_model: str = "openai/gpt-oss-120b"
    groq_extra_models: str = "openai/gpt-oss-20b"
    embeddings_url: str = "http://localhost:8080"
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dim: int = 384
    rag_min_dense_score: float = 0.81
    webhook_secret: SecretStr = SecretStr("change-me")
    daily_request_limit: int = 150
    prompt_version: str = "v2"
    cache_ttl_seconds: int = 3600
    cache_history_turns: int = 2
    webhook_max_tries: int = 3
    client_rate_limit_per_minute: int = 20
    worker_metrics_port: int = 9101
    manager_token: SecretStr = SecretStr("demo-manager")
    demo_mode: bool = False


@lru_cache
def get_settings() -> Settings:
    """Возвращает единственный экземпляр настроек на процесс.

    Returns:
        Закэшированный объект Settings.
    """
    return Settings()
