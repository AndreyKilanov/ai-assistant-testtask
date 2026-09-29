"""Сводная статистика и метрики Prometheus."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.deps import get_container, require_manager
from app.bootstrap import Container
from app.schemas.stats import StatsResponse

router = APIRouter(tags=["monitoring"])


@router.get("/api/stats", response_model=StatsResponse, dependencies=[Depends(require_manager)])
async def stats(container: Annotated[Container, Depends(get_container)]) -> StatsResponse:
    """Сводка за текущие сутки (UTC): подсказки, попадания в кеш, токены, задержки, оценки."""
    return await container.stats.today()


@router.get("/metrics", include_in_schema=False, dependencies=[Depends(require_manager)])
async def metrics() -> Response:
    """Метрики Prometheus текущего процесса (нужен заголовок ``X-Manager-Token``)."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
