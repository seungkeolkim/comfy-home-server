"""Prompt와 전체 버전 삭제의 원자성 및 작업 Snapshot 보존을 검증합니다."""

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from test_application import FakeComfyClient, create_processing_test_app


def read_prompt_related_records(database_path: Path) -> dict[str, list[tuple]]:
    """Prompt 정의 외에 삭제로 달라지면 안 되는 기존 데이터의 원문을 읽습니다."""

    with sqlite3.connect(database_path) as connection:
        table_names = ("jobs", "job_requests", "job_inputs", "request_results", "output_files", "request_favorites", "favorite_output_links")
        return {table_name: connection.execute(f"SELECT * FROM {table_name}").fetchall() for table_name in table_names}


def test_delete_prompt_removes_all_versions_and_preserves_snapshots(tmp_path: Path) -> None:
    """Anima·MiniMax Prompt를 삭제해도 생성 이력·즐겨찾기·결과물 파일은 보존합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    database = server.database
    database.save_preset("portrait", "인물", "anima", {"prompt": "first", "negative": "first negative"})
    database.save_preset("portrait", "인물", "anima", {"prompt": "second", "negative": "second negative"})
    database.save_preset("motion", "영상", "minimax_h3", {"prompt": "video"})
    database.save_preset("keep", "보존", "anima", {"prompt": "keep", "negative": ""})
    output_path = server.config.managed_output_directory / "portrait.png"
    Image.new("RGB", (32, 32), "teal").save(output_path)
    database.add_job("saved-job", "anima", "삭제 이후에도 보존", [{
        "request_id": "saved-request", "status": "completed", "output_stem": "anima/portrait",
        "detail": {"preset_id": "portrait", "preset_version": 2, "body": {"prompt": "second", "negative": "second negative"},
                   "selected_tags": [], "settings": {"seed": 42}, "loras": [],
                   "resolved": {"prompt": "second", "negative": "second negative", "settings": {"seed": 42}}},
    }])
    database.complete_request("saved-request", ["portrait.png"])
    output_id = server.output_catalog.list_files(1, 10)["files"][0]["output_id"]
    database.favorites.save_output(output_id, server.config.managed_output_directory)
    original_records = read_prompt_related_records(database.database_path)
    original_output = output_path.read_bytes()

    with TestClient(application) as client:
        assert client.delete("/api/presets/portrait").status_code == 401
        client.post("/api/login", json={"password": "test"})
        assert client.delete("/api/presets/portrait", headers={"Origin": "http://other.test"}).status_code == 403
        assert database.get_preset("portrait") is not None
        assert client.delete("/api/presets/portrait").json() == {"deleted": True}
        assert client.get("/api/presets/portrait/versions").json() == []
        assert client.delete("/api/presets/portrait").status_code == 404
        assert client.delete("/api/presets/motion").status_code == 200
        assert client.get("/api/presets/motion/versions").json() == []
        assert [preset["preset_id"] for preset in client.get("/api/presets").json()] == ["keep"]
        assert len(database.list_preset_versions("keep")) == 1
        assert read_prompt_related_records(database.database_path) == original_records
        assert output_path.read_bytes() == original_output
        assert list(server.administration.backup_directory.iterdir()) == []
        with database._connect() as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 14
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            assert json.loads(connection.execute("SELECT input_json FROM job_inputs").fetchone()[0])["preset_id"] == "portrait"


def test_prompt_delete_failure_rolls_back_version_deletion(tmp_path: Path) -> None:
    """Prompt 삭제가 실패하면 앞서 삭제한 버전도 함께 Rollback합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    database = application.state.home_server.database
    database.save_preset("protected", "실패 검증", "anima", {"prompt": "first"})
    database.save_preset("protected", "실패 검증", "anima", {"prompt": "second"})
    with database._connect() as connection:
        connection.execute("CREATE TRIGGER reject_prompt_deletion BEFORE DELETE ON presets BEGIN SELECT RAISE(ABORT, 'test deletion failure'); END")
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        response = client.delete("/api/presets/protected")
        assert response.status_code == 409
        assert database.get_preset("protected")["version"] == 2
        assert [version["version"] for version in database.list_preset_versions("protected")] == [2, 1]
