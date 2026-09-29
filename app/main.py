"""Точка входа FastAPI: создание приложения и подключение роутов."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.routes import analyze, chat, demo, feedback, health, manager, stats, ui, webhooks
from app.bootstrap import Container, build_container
from app.core.config import get_settings
from app.core.logging import setup_logging


def create_app(container: Container | None = None) -> FastAPI:
    """Собирает приложение FastAPI.

    Args:
        container: Готовый контейнер зависимостей (для тестов); если не передан, собирается при старте.

    Returns:
        Настроенный экземпляр FastAPI с подключёнными роутами; Swagger (``/docs``) доступен только в демо-режиме.
    """
    setup_logging()
    settings = container.settings if container else get_settings()
    docs = {} if settings.demo_mode else {"docs_url": None, "redoc_url": None, "openapi_url": None}

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.container = container or await build_container(get_settings())
        yield
        if container is None:
            await application.state.container.aclose()

    application = FastAPI(title="AmoCRM AI Assistant", version=__version__, lifespan=lifespan, **docs)
    register_exception_handlers(application)
    routers = (
        ui.router,
        health.router,
        chat.router,
        demo.router,
        manager.router,
        analyze.router,
        feedback.router,
        stats.router,
        webhooks.router,
    )
    for router in routers:
        application.include_router(router)
    application.mount("/static", ui.static_files, name="static")
    return application


app = create_app()
