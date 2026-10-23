"""요청 즐겨찾기의 독립 보관·분류·정확한 단건 복원과 입력 이미지 보존을 검증합니다."""

import json
import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from home_server.database import Database
from test_application import FakeComfyClient, create_processing_test_app


def prepare_favorite_job(server, workflow: str = "anima", source_image: dict | None = None) -> list[int]:
    """큰 Seed와 원본 후보·확정 Prompt가 다른 두 요청 및 여러 결과물을 만듭니다."""

    settings = {"width": 64, "height": 64, "steps": 12, "cfg": 1, "seed": 18446744073709551615,
                "duration": 1, "frame_rate": 12, "generation_mode": "FL2VA"}
    requests = []
    for request_index in range(2):
        resolved = {"prompt": "saved garden, literal {unchanged}", "negative": "saved negative",
                    "selected_path": [{"name": "당시 정원", "tag_id": "archived-tag"}],
                    "settings": dict(settings), "source_image": source_image}
        if workflow == "minimax_h3":
            resolved["settings"].pop("seed")
        requests.append({"request_id": f"favorite-request-{request_index}", "status": "pending", "output_stem": "output",
                         "detail": {"body": {"prompt": "[SCENE]", "negative": "saved negative"},
                                    "settings": settings, "loras": [{"name": "example.safetensors", "strength": 0.75}],
                                    "selected_tags": [{"tag_id": "archived-tag", "group_id": "old-group", "tag_key": "SCENE",
                                                       "name": "당시 정원", "content": "saved garden", "weight": 2}],
                                    "resolved": resolved}})
    server.database.add_job("favorite-job", workflow, "즐겨찾기 실험", requests)
    output_paths = ["261024_100000_18446744073709551615.png", "261024_100000_18446744073709551615_00001.png"]
    server.config.managed_output_directory.mkdir(parents=True, exist_ok=True)
    for output_path in output_paths:
        Image.new("RGB", (64, 64)).save(server.config.managed_output_directory / output_path)
    server.database.complete_request("favorite-request-0", output_paths)
    server.database.complete_request("favorite-request-1", [])
    with sqlite3.connect(server.database.database_path) as connection:
        return [row[0] for row in connection.execute("SELECT output_id FROM output_files WHERE request_id='favorite-request-0'")]


def wait_for_favorite_submission(client: TestClient, job_identifier: str) -> dict:
    """Fake ComfyClient의 백그라운드 접수가 끝날 때까지만 기다립니다."""

    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_identifier}").json()
        if job["requests"][0]["prompt_id"] or job["requests"][0]["status"] == "failed":
            return job
        time.sleep(0.01)
    raise AssertionError("즐겨찾기 재제출이 완료되지 않았습니다.")


def test_favorite_snapshot_deduplicates_outputs_and_survives_history_and_media_deletion(tmp_path: Path) -> None:
    """같은 요청의 여러 파일은 하나로 저장하고 현재 분류·이력 삭제·파일 삭제 뒤에도 설정은 남깁니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    output_identifiers = prepare_favorite_job(server)
    parent_identifier = server.database.job_folders.save_folder("상위", None)
    child_identifier = server.database.job_folders.save_folder("하위", parent_identifier)
    server.database.job_folders.move_jobs(["favorite-job"], child_identifier)
    with TestClient(application) as client:
        assert client.get("/api/favorites").status_code == 401
        client.post("/api/login", json={"password": "test"})
        first = client.put(f"/api/outputs/{output_identifiers[0]}/favorite")
        assert first.status_code == 200, first.text
        favorite_identifier = first.json()["favorite_id"]
        assert client.put(f"/api/outputs/{output_identifiers[1]}/favorite").json()["favorite_id"] == favorite_identifier
        assert client.get("/api/favorites", params={"folder_id": parent_identifier}).json()["total"] == 1
        snapshot = client.get(f"/api/favorites/{favorite_identifier}").json()
        assert snapshot["selected_tags"][0]["content"] == "saved garden"
        assert snapshot["resolved"]["settings"]["seed"] == "18446744073709551615"
        assert all(output_file["favorite_id"] == favorite_identifier for output_file in client.get("/api/outputs").json()["files"])
        assert client.post("/api/outputs/move", json={"source": "261024_100000_18446744073709551615.png", "destination_folder": "moved"}).status_code == 200
        assert client.get("/api/favorites").json()["items"][0]["file"]["path"].startswith("moved/")
        server.database.job_folders.move_jobs(["favorite-job"], None)
        assert client.get("/api/favorites", params={"folder_id": parent_identifier}).json()["total"] == 0
        assert client.get("/api/favorites", params={"folder_id": "unassigned"}).json()["total"] == 1
        assert client.delete("/api/jobs/favorite-job").status_code == 200
        retained_snapshot = client.get(f"/api/favorites/{favorite_identifier}").json()
        assert retained_snapshot["inputs"] == snapshot["inputs"]
        assert retained_snapshot["source_job_id"] is None
        for output_identifier in output_identifiers:
            assert client.delete(f"/api/outputs/{output_identifier}").status_code == 200
        assert client.get("/api/favorites").json()["items"][0]["file"] is None
        assert client.delete(f"/api/favorites/{favorite_identifier}").status_code == 200
        assert client.get("/api/favorites").json()["total"] == 0


def test_exact_and_source_restore_use_archived_inputs_and_fixed_seed_for_one_request(tmp_path: Path) -> None:
    """확정 복원은 wildcard를 다시 확장하지 않고 원본 변형은 현재 태그 DB 없이 저장 후보로 추첨합니다."""

    fake_comfy = FakeComfyClient()
    application = create_processing_test_app(tmp_path, fake_comfy)
    server = application.state.home_server
    output_identifier = prepare_favorite_job(server)[0]
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        favorite_identifier = client.put(f"/api/outputs/{output_identifier}/favorite").json()["favorite_id"]
        client.delete("/api/jobs/favorite-job")
        payload = {"workflow": "anima", "body": {"prompt": "saved garden, literal {unchanged}", "negative": "saved negative"},
                   "count": 100, "settings": {"seed": 1}, "loras": [{"name": "example.safetensors", "strength": 0.75}]}
        response = client.post(f"/api/favorites/{favorite_identifier}/batches", json=payload)
        assert response.status_code == 200, response.text
        restored_job = wait_for_favorite_submission(client, response.json()["job_id"])
        assert restored_job["request_count"] == 1
        assert restored_job["requests"][0]["result"]["settings"]["seed"] == 18446744073709551615
        assert fake_comfy.wildcard_prompts == []
        workflow = fake_comfy.submissions[-1][0]
        assert workflow["24"]["inputs"]["seed"] == 18446744073709551615
        assert fake_comfy.submissions[-1][1]["home_server_request"]["prompt"] == payload["body"]["prompt"]
        payload.update({"restore_mode": "source", "body": {"prompt": "[SCENE]", "negative": "saved negative"}, "selected_tag_ids": ["archived-tag"]})
        response = client.post(f"/api/favorites/{favorite_identifier}/batches", json=payload)
        assert response.status_code == 200, response.text
        restored_job = wait_for_favorite_submission(client, response.json()["job_id"])
        assert restored_job["requests"][0]["result"]["prompt"] == "saved garden"
        assert fake_comfy.submissions[-1][0]["24"]["inputs"]["seed"] == 18446744073709551615
        payload["selected_tag_ids"] = ["unknown"]
        assert client.post(f"/api/favorites/{favorite_identifier}/batches", json=payload).status_code == 422


def test_minimax_favorite_keeps_input_copy_and_uses_actual_unsigned_seed(tmp_path: Path) -> None:
    """원본 입력이 삭제되어도 별도 복사본과 파일명 Seed로 영상 한 건을 고정 복원합니다."""

    fake_comfy = FakeComfyClient()
    application = create_processing_test_app(tmp_path, fake_comfy)
    server = application.state.home_server
    source_path = server.config.managed_output_directory / "source.png"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), "green").save(source_path)
    server.output_catalog.synchronize(server.config.managed_output_directory)
    source_identifier = server.output_catalog.list_files(1, 64)["files"][0]["output_id"]
    output_identifier = prepare_favorite_job(server, "minimax_h3", {"output_id": source_identifier, "path": "source.png", "width": 64, "height": 64})[0]
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        response = client.put(f"/api/outputs/{output_identifier}/favorite")
        assert response.status_code == 200, response.text
        favorite_identifier = response.json()["favorite_id"]
        client.delete(f"/api/outputs/{source_identifier}")
        payload = {"workflow": "minimax_h3", "body": {"prompt": "saved garden"}, "settings": {}, "loras": []}
        response = client.post(f"/api/favorites/{favorite_identifier}/batches", json=payload)
        assert response.status_code == 200, response.text
        job = wait_for_favorite_submission(client, response.json()["job_id"])
        assert job["requests"][0]["status"] == "pending", job
        seed_control = fake_comfy.submissions[-1][0]["2739"]["inputs"]
        assert seed_control["seed_value"] == 18446744073709551615
        assert json.loads(seed_control["seed_control_state"])["mode"] == "fixed"
        assert client.delete(f"/api/favorites/{favorite_identifier}").status_code == 200
        assert list(server.database.favorites.input_directory.iterdir()) == []


def test_schema_thirteen_favorites_migration_backs_up_existing_rows(tmp_path: Path) -> None:
    """Schema 13 백업과 기존 요청·출력 보존을 검증하며 재시작 시 백업을 중복 생성하지 않습니다."""

    database_path = tmp_path / "jobs.sqlite3"
    database = Database(database_path)
    database.add_job("existing", "anima", "보존", [])
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE favorite_output_links")
        connection.execute("DROP TABLE request_favorites")
        connection.execute("PRAGMA user_version=13")
    assert Database(database_path).get_job("existing")["description"] == "보존"
    backup_path = next((tmp_path / "backups").glob("*_before_request_favorites_*.sqlite3"))
    with sqlite3.connect(backup_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 13
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    Database(database_path)
    assert len(list((tmp_path / "backups").glob("*_before_request_favorites_*.sqlite3"))) == 1


def test_favorite_validation_preserves_settings_and_rejects_missing_sources(tmp_path: Path) -> None:
    """없는 입력·LoRA·잘못된 Workflow는 거절하고 생략된 LoRA는 보관된 조합을 사용합니다."""

    fake_comfy = FakeComfyClient()
    application = create_processing_test_app(tmp_path, fake_comfy)
    server = application.state.home_server
    output_identifier = prepare_favorite_job(server)[0]
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        favorite_identifier = client.put(f"/api/outputs/{output_identifier}/favorite").json()["favorite_id"]
        payload = {"workflow": "minimax_h3", "body": {"prompt": "saved garden"}}
        assert client.post(f"/api/favorites/{favorite_identifier}/batches", json=payload).status_code == 422
        payload.update({"workflow": "anima", "loras": [{"name": "removed.safetensors", "strength": 0.75}]})
        assert client.post(f"/api/favorites/{favorite_identifier}/batches", json=payload).status_code == 422
        assert fake_comfy.submissions == []
        payload.pop("loras")
        response = client.post(f"/api/favorites/{favorite_identifier}/batches", json=payload)
        assert response.status_code == 200, response.text
        wait_for_favorite_submission(client, response.json()["job_id"])
        assert fake_comfy.submissions[-1][1]["home_server_request"]["loras"] == [{"name": "example.safetensors", "strength": 0.75}]
        assert client.put("/api/outputs/999999/favorite").status_code == 404
        assert client.get("/api/favorites/absent").status_code == 404
        assert client.get("/api/favorites", params={"folder_id": "absent"}).status_code == 404
        with server.database._connect() as connection:
            connection.execute("UPDATE jobs SET workflow='minimax_h3' WHERE job_id='favorite-job'")
        assert client.delete(f"/api/favorites/{favorite_identifier}").status_code == 200
        missing_input = client.put(f"/api/outputs/{output_identifier}/favorite")
        assert missing_input.status_code == 422
        assert "입력 이미지" in missing_input.json()["detail"]
        assert client.get("/api/favorites").json()["total"] == 0
        assert not server.database.favorites.input_directory.exists()
