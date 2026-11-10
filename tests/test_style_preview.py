"""Phase 0 화면은 고정 자산만 제공하고 다른 파일을 노출하지 않아야 합니다."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from home_server.style_preview import create_style_preview_router


def test_preview_serves_only_allowed_files() -> None:
    """예시 화면·스크립트·스타일은 제공하고 설정·경로 요청은 거부합니다."""

    application = FastAPI()
    application.include_router(create_style_preview_router())
    with TestClient(application) as client:
        for path, media_type in (
            ("/style", "text/html"),
            ("/style-preview", "text/html"),
            ("/style-preview/preview.css", "text/css"),
            ("/style-preview/preview.js", "text/javascript"),
            ("/style-preview/settings-preview.js", "text/javascript"),
            ("/style-preview/ranking-preview.js", "text/javascript"),
            ("/style-preview/project-persistence.js", "text/javascript"),
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(media_type)
            assert response.headers["cache-control"] == "no-store"
        for path in ("/style-preview/config.toml", "/style-preview/home_server.sqlite3", "/style-preview/%2E%2E%2Fconfig.toml"):
            assert client.get(path).status_code == 404
