"""스타일 프로젝트 화면과 별도의 Phase 0 예시 화면을 제공합니다."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


PREVIEW_DIRECTORY = Path(__file__).resolve().parent.parent / "web" / "style-preview"
PREVIEW_ASSETS = {
    "preview.css": "text/css",
    "preview.js": "text/javascript",
    "settings-preview.js": "text/javascript",
    "style-prompt-seeds.js": "text/javascript",
    "ranking-preview.js": "text/javascript",
    "project-persistence.js": "text/javascript",
    "style-project-forks.js": "text/javascript",
    "style-generation.js": "text/javascript",
    "style-voting.js": "text/javascript",
    "style-evolution.js": "text/javascript",
    "style-comparison.js": "text/javascript",
    "style-library.js": "text/javascript",
    "style-favorites.js": "text/javascript",
    "style-lora-presets.js": "text/javascript",
    "style-component-statistics.js": "text/javascript",
}


def create_style_preview_router() -> APIRouter:
    """화면 자산만 제공하며 프로젝트 API는 별도 Router에서 관리합니다."""

    router = APIRouter()

    @router.get("/style", include_in_schema=False)
    @router.get("/style-preview", include_in_schema=False)
    async def style_preview_page():
        """같은 UI 자산에서 실제 프로젝트와 예시 화면을 경로로 구분합니다."""

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
