"""실제 프로젝트 저장의 격리·조건 불변성·동시성·Migration을 검증합니다."""

import copy
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_server.configuration import PROJECT_DIRECTORY
from home_server.database import Database
from home_server.style_projects import ProjectWriteInput
from test_application import FakeComfyClient, create_processing_test_app


def project_settings(name: str = "프로젝트 A") -> dict:
    """서로 다른 Case ID와 고정 STR을 가진 두 Prompt를 준비합니다."""

    return {
        "name": name, "purpose": "특정 Prompt의 그림체 탐색", "pipelineIdentifier": "anima",
        "promptCases": [
            {"identifier": "portrait-case", "name": "인물", "prompt": "portrait, {artist}", "negativePrompt": ""},
            {"identifier": "garden-case", "name": "정원", "prompt": "garden, {artist}", "negativePrompt": ""},
        ],
        "negativePrompt": "low quality", "width": 576, "height": 864, "steps": 12, "cfg": 1,
        "componentPolicies": {"artist:example": {"enabled": True, "minimumStrength": 0.4, "maximumStrength": 0.4}},
    }


def project_request(settings: dict, expected_revision: int | None = None) -> dict:
    """실제 요청과 같은 고유 Operation ID를 발급합니다."""

    return {"settings": settings, "operationIdentifier": uuid.uuid4().hex, "expectedRevision": expected_revision}


def test_fresh_projects_persist_without_jobs_and_keep_evaluation_snapshots(tmp_path: Path) -> None:
    """이름·범위 변경과 실제 평가 조건 변경을 구분하고 재시작 뒤 다시 엽니다."""

    fake_comfy = FakeComfyClient()
    application = create_processing_test_app(tmp_path, fake_comfy)
    server = application.state.home_server
    with TestClient(application) as client:
        assert client.get("/api/style-workspace").status_code == 401
        client.post("/api/login", json={"password": "test"})
        workspace = client.get("/api/style-workspace").json()
        assert workspace["projects"] == []
        assert workspace["components"][0]["identifier"] == "lora:example.safetensors"
        assert workspace["globalSettings"]["additionalArtists"] == []
        request = project_request(project_settings())
        response = client.post("/api/style-projects", json=request)
        assert response.status_code == 201, response.text
        first_project = response.json()
        second_settings = project_settings("프로젝트 B")
        second_settings["promptCases"][0]["prompt"] = "different character"
        second_project = client.post("/api/style-projects", json=project_request(second_settings)).json()
        assert first_project["candidates"] == first_project["decisions"] == []
        assert first_project["generation"] == 0
        assert client.post("/api/style-projects", json=request).json()["identifier"] == first_project["identifier"]
        settings = first_project["settings"]
        settings["name"] = "바뀐 이름"
        settings["purpose"] = "메모만 변경"
        settings["componentPolicies"]["artist:example"]["maximumStrength"] = 0.9
        update_request = project_request(settings, first_project["revision"])
        update_response = client.put(f"/api/style-projects/{first_project['identifier']}", json=update_request)
        assert update_response.status_code == 200, update_response.text
        renamed_project = update_response.json()
        assert renamed_project["evaluationIdentifier"] == first_project["evaluationIdentifier"]
        assert renamed_project["storageBinding"]["project_folder"].startswith("바뀐 이름__")
        assert renamed_project["storageBinding"]["state"] == "not_created"
        assert client.put(f"/api/style-projects/{first_project['identifier']}", json=update_request).json()["revision"] == 2
        assert client.put(f"/api/style-projects/{first_project['identifier']}", json=project_request(settings, 1)).status_code == 409
        changed_settings = copy.deepcopy(renamed_project["settings"])
        changed_settings["promptCases"][0]["prompt"] = "new portrait"
        new_evaluation = client.put(
            f"/api/style-projects/{first_project['identifier']}", json=project_request(changed_settings, 2),
        ).json()
        assert new_evaluation["evaluationIdentifier"] != first_project["evaluationIdentifier"]
        assert client.get(f"/api/style-projects/{second_project['identifier']}").json()["settings"] == second_project["settings"]
        assert client.get("/api/jobs").json()["total"] == 0
        assert fake_comfy.submissions == []
        with sqlite3.connect(server.database.database_path) as connection:
            contracts = [json.loads(row[0]) for row in connection.execute(
                "SELECT contract_json FROM style_evaluation_revisions WHERE project_id=? ORDER BY created_at", (first_project["identifier"],),
            )]
        assert len(contracts) == 2
        assert contracts[0]["prompt_cases"][0]["prompt"] == "portrait, {artist}"
        assert contracts[1]["prompt_cases"][0]["identifier"] == "portrait-case"
        assert contracts[0]["workflow"]["api_hash"] == contracts[1]["workflow"]["api_hash"]
        assert contracts[0]["sampling"]["seed"] == 42
    restored_database = Database(server.database.database_path)
    projects = restored_database.style_projects.list_projects()
    assert len(projects) == 2
    assert next(project for project in projects if project["identifier"] == first_project["identifier"])["name"] == "바뀐 이름"


def test_global_defaults_and_artist_catalog_do_not_rewrite_projects(tmp_path: Path) -> None:
    """글로벌 기본값과 실제 작가 등록을 저장하고 기존 프로젝트를 보존합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        saved_project = client.post("/api/style-projects", json=project_request(project_settings())).json()
        settings = client.get("/api/style-workspace").json()["globalSettings"]
        settings["additionalArtists"] = [{"identifier": "artist:example", "name": "example", "kind": "작가"}]
        settings["availableComponents"]["artist:example"] = True
        settings["artistMinimumStrength"] = settings["artistMaximumStrength"] = 0.8
        response = client.put("/api/style-settings", json=settings)
        assert response.status_code == 200, response.text
        assert response.json()["revision"] == 2
        assert client.put("/api/style-settings", json=settings).status_code == 409
        assert client.get(f"/api/style-projects/{saved_project['identifier']}").json()["settings"] == saved_project["settings"]
        assert client.get("/api/style-workspace").json()["globalSettings"]["additionalArtists"][0]["name"] == "example"


@pytest.mark.parametrize("invalid_change", [
    {"name": "../outside"}, {"name": "CON"}, {"pipelineIdentifier": "moss"},
    {"width": 0}, {"cfg": "NaN"}, {"promptCases": []},
    {"promptCases": [{"identifier": "same", "name": "빈 입력", "prompt": "   "}]},
    {"componentPolicies": {"lora:example": {"enabled": False, "minimumStrength": 1, "maximumStrength": 0.5}}},
])
def test_invalid_project_settings_are_not_saved(tmp_path: Path, invalid_change: dict) -> None:
    """경로·미지원 모델·조건·비활성 범위 오류도 서버에서 거부합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        settings = project_settings()
        settings.update(invalid_change)
        assert client.post("/api/style-projects", json=project_request(settings)).status_code == 422
        assert client.get("/api/style-projects").json() == {"projects": []}


def test_concurrent_project_writes_have_one_winner(tmp_path: Path) -> None:
    """같은 Revision에서 시작한 두 탭 중 한 변경만 저장합니다."""

    database = Database(tmp_path / "home_server.sqlite3")
    workflow_directory = PROJECT_DIRECTORY / "data" / "workflows"
    project = database.style_projects.save_project(ProjectWriteInput(**project_request(project_settings())), workflow_directory)

    def write_project(name: str) -> str:
        """각 Thread에서 별도 연결로 같은 프로젝트 Revision을 변경합니다."""

        from home_server.style_projects import StyleRevisionConflict

        settings = project_settings(name)
        try:
            database.style_projects.save_project(ProjectWriteInput(**project_request(settings, 1)), workflow_directory, project["identifier"])
        except StyleRevisionConflict:
            return "conflict"
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(write_project, ["첫 번째 이름", "두 번째 이름"])) == ["conflict", "saved"]


def test_version_fourteen_backup_and_migration_preserve_general_history(tmp_path: Path) -> None:
    """14번 DB 사본에서 Migration·재기동을 검증하고 원본 Backup을 확인합니다."""

    database_path = tmp_path / "home_server.sqlite3"
    original_database = Database(database_path)
    original_database.add_job("keep", "anima", "기존 일반 생성", [{
        "request_id": "keep-request", "status": "completed", "output_stem": "anima/original", "detail": {},
    }])
    with sqlite3.connect(database_path) as connection:
        for table_name in ["style_evaluation_revisions", "style_projects", "style_workspace_settings"]:
            connection.execute(f"DROP TABLE {table_name}")
        connection.execute("PRAGMA user_version=14")
    migrated_database = Database(database_path)
    assert migrated_database.list_jobs()["total"] == 1
    assert migrated_database.style_projects.list_projects() == []
    backup_path = next((tmp_path / "backups").glob("*before_style_projects*.sqlite3"))
    with sqlite3.connect(backup_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 14
        assert connection.execute("SELECT COUNT(*) FROM job_requests").fetchone()[0] == 1
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    Database(database_path)
    assert len(list((tmp_path / "backups").glob("*before_style_projects*.sqlite3"))) == 1


def test_style_routes_share_home_origin_and_file_boundaries(tmp_path: Path) -> None:
    """쓰기 API의 출처 보호와 실제/예시 화면 자산만 노출하는 경계를 검증합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        assert client.post("/api/style-projects", json=project_request(project_settings()), headers={"origin": "https://other.test"}).status_code == 403
        assert client.get("/style").status_code == 200
        assert client.get("/style-preview/project-persistence.js").status_code == 200
        assert client.get("/style-preview/config.toml").status_code == 404
