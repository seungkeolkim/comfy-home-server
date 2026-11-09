"""실제 탐색 데이터와 분리된 Phase 0 화면 파일을 제공합니다."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


PREVIEW_DIRECTORY = Path(__file__).resolve().parent.parent / "web" / "style-preview"
PREVIEW_ASSETS = {"preview.css": "text/css", "preview.js": "text/javascript"}


def create_style_preview_router() -> APIRouter:
    """고정된 목업 파일만 제공하며 생성·저장 API를 추가하지 않습니다."""

    router = APIRouter()

    @router.get("/style-preview", include_in_schema=False)
    async def style_preview_page():
        """일반 생성과 같은 Session을 사용하는 화면 목업을 제공합니다."""

        return FileResponse(
            PREVIEW_DIRECTORY / "index.html", media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/style-preview/{asset_name}", include_in_schema=False)
    async def style_preview_asset(asset_name: str):
        """허용한 CSS·JavaScript 외의 파일 요청을 거부합니다."""

        media_type = PREVIEW_ASSETS.get(asset_name)
        if media_type is None:
            raise HTTPException(404, "화면 파일을 찾을 수 없습니다.")
        return FileResponse(
            PREVIEW_DIRECTORY / asset_name, media_type=media_type,
            headers={"Cache-Control": "no-store"},
        )

    return router
