"""Служебные эндпоинты."""

from fastapi import APIRouter

from app import __version__

router = APIRouter(tags=["service"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Проверка живости сервиса для healthcheck контейнера."""
    return {"status": "ok", "version": __version__}
