"""일반 생성과 스타일 구성이 같은 로그인 Session을 공유하는지 검증합니다."""

import time
from pathlib import Path

from fastapi.testclient import TestClient

from test_application import FakeComfyClient, create_processing_test_app


def test_shared_workspace_assets_are_public_without_changing_session(tmp_path: Path) -> None:
    """로그인 전 공통 화면 자산을 받아도 Session을 발급하거나 기존 Cookie를 지우지 않습니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    with TestClient(application) as client:
        for asset_path, media_type in (
            ("/workspace-shell.css", "text/css"),
            ("/workspace-shell.js", "text/javascript"),
        ):
            asset_response = client.get(asset_path)
            assert asset_response.status_code == 200
            assert asset_response.headers["content-type"].startswith(media_type)
            assert asset_response.headers["cache-control"] == "no-cache"
            assert "set-cookie" not in asset_response.headers
            assert "clear-site-data" not in asset_response.headers
        assert client.get("/api/session").json() == {"authenticated": False}


def test_workspace_navigation_reuses_one_authenticated_session(tmp_path: Path) -> None:
    """한 번 로그인한 Cookie로 양쪽 화면과 API를 반복해서 열 수 있습니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    with TestClient(application) as client:
        assert client.get("/api/session").json() == {"authenticated": False}
        for protected_path in ("/api/tags", "/api/style-workspace", "/api/style-projects"):
            assert client.get(protected_path).status_code == 401

        login_response = client.post("/api/login", json={"password": "test"})
        assert login_response.status_code == 200
        session_cookie = client.cookies.get("home_session")
        assert session_cookie
        assert "Path=/" in login_response.headers["set-cookie"]

        for workspace_path in ("/", "/style", "/", "/style"):
            page_response = client.get(workspace_path)
            assert page_response.status_code == 200
            assert "set-cookie" not in page_response.headers
            assert client.cookies.get("home_session") == session_cookie
            assert client.get("/api/session").json() == {"authenticated": True}
            assert client.get("/api/tags").status_code == 200
            assert client.get("/api/style-workspace").status_code == 200

        assert len(application.state.home_server.sessions) == 1


def test_logout_invalidates_both_workspace_apis(tmp_path: Path) -> None:
    """로그아웃하면 일반 생성과 스타일 구성 API의 동일 Session을 폐기합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        session_cookie = client.cookies.get("home_session")
        logout_response = client.post("/api/logout")
        assert logout_response.status_code == 200
        assert logout_response.json() == {"authenticated": False}
        assert client.get("/api/session").json() == {"authenticated": False}

        for protected_path in ("/api/tags", "/api/style-workspace", "/api/style-projects"):
            rejected_response = client.get(protected_path, headers={"Cookie": f"home_session={session_cookie}"})
            assert rejected_response.status_code == 401


def test_expired_session_requires_login_in_both_workspaces(tmp_path: Path) -> None:
    """Session 만료도 두 모드에서 동일하게 인증 실패로 처리합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        session_cookie = client.cookies.get("home_session")
        application.state.home_server.sessions[session_cookie] = time.time() - 1

        assert client.get("/api/session").json() == {"authenticated": False}
        assert client.get("/api/tags").status_code == 401
        assert client.get("/api/style-workspace").status_code == 401
