"""Веб-интерфейсы: экран клиента (``/``) и консоль менеджера (``/manager``), статические файлы."""

import mimetypes
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".js")

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
FONT_CACHE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"


class AssetFiles(StaticFiles):
    """Статика интерфейса: шрифты кешируются надолго, скрипты и стили перепроверяются по ETag."""

    def file_response(
        self, full_path: str | Path, stat_result: object, scope: Scope, status_code: int = 200
    ) -> Response:
        """Собирает ответ с заголовком Cache-Control по типу файла.

        Args:
            full_path: Путь к файлу.
            stat_result: Результат ``os.stat`` файла.
            scope: ASGI-контекст запроса.
            status_code: Код ответа.

        Returns:
            Ответ с содержимым файла и заголовком Cache-Control.
        """
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = FONT_CACHE if str(full_path).endswith(".woff2") else REVALIDATE
        return response


router = APIRouter(include_in_schema=False)
static_files = AssetFiles(directory=STATIC_DIR)


@router.get("/")
async def client_page() -> FileResponse:
    """Отдаёт публичный экран клиента: чат с менеджером и запрос на связь."""
    return FileResponse(STATIC_DIR / "client.html", headers={"Cache-Control": REVALIDATE})


@router.get("/manager")
async def manager_page() -> FileResponse:
    """Отдаёт консоль менеджера (вход по коду доступа): входящие, история, карточка клиента, подсказки ИИ."""
    return FileResponse(STATIC_DIR / "manager.html", headers={"Cache-Control": REVALIDATE})
