"""서버 이미지 Snapshot, 세 영상 모드, 실제 해상도와 이력 보존을 GPU 없이 검증합니다."""

import asyncio
import copy
import json
import os
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from home_server.minimax_inputs import inspect_input_images, prepare_input_canvas, snapshot_input_images
from home_server.workflows import load_workflows, prepare_minimax
from test_application import FakeComfyClient, create_processing_test_app
from test_output_catalog import add_catalog_test_request, read_history_json


class CapturingImageClient(FakeComfyClient):
    """ComfyUI에 보내는 실제 입력 Canvas를 확인하고 필요하면 업로드를 지연합니다."""

    def __init__(self, block_upload: bool = False) -> None:
        """Canvas 기록과 Thread 제어 gate를 준비합니다."""

        super().__init__()
        self.uploaded_images = []
        self.upload_started = threading.Event()
        self.release_upload = threading.Event()
        if not block_upload:
            self.release_upload.set()

    async def upload_image(self, image_path: Path, file_name: str) -> str:
        """임시 입력의 실제 크기와 Pixel을 읽어 원본 변경의 영향을 확인합니다."""

        with Image.open(image_path) as image:
            self.uploaded_images.append({"size": image.size, "center": image.getpixel((image.width // 2, image.height // 2)), "corner": image.getpixel((0, 0))})
        self.upload_started.set()
        await asyncio.to_thread(self.release_upload.wait, 5)
        return await super().upload_image(image_path, file_name)


def add_input_images(server, image_definitions: list[tuple[str, tuple[int, int]]]) -> dict[str, int]:
    """실제 파일과 catalog를 만들며 테스트 결과물만 동기화합니다."""

    for relative_path, dimensions in image_definitions:
        image_path = server.config.managed_output_directory / relative_path
        image_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", dimensions, "red").save(image_path)
    server.output_catalog.synchronize(server.config.managed_output_directory)
    with sqlite3.connect(server.database.database_path) as connection:
        return dict(connection.execute("SELECT relative_path,output_id FROM output_files"))


def wait_for_submissions(comfy_client: CapturingImageClient, expected_count: int) -> None:
    """백그라운드 요청이 정해진 시간 안에 접수되는지 확인합니다."""

    deadline = time.monotonic() + 5
    while len(comfy_client.submissions) < expected_count and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(comfy_client.submissions) == expected_count


@pytest.mark.parametrize("generation_mode,execution_mode,endpoint_slots", [
    ("F2VA", "I2VA", [0]), ("L2VA", "L2VA", [1]), ("FL2VA", "FL2VA", [0, 1]),
])
def test_server_image_batch_modes_actual_dimensions_and_metadata(tmp_path: Path, generation_mode: str, execution_mode: str, endpoint_slots: list[int]) -> None:
    """동일 템플릿에서 모드별 endpoint만 구성하며 실제 첫 이미지의 공통 크기와 원본 출처를 저장합니다."""

    comfy_client = CapturingImageClient()
    application = create_processing_test_app(tmp_path, comfy_client)
    server = application.state.home_server
    output_ids = add_input_images(server, [("folder/b.png", (100, 60)), ("folder/a.png", (65, 97))])
    source_request_id = add_catalog_test_request(server.database)
    server.database.complete_request(source_request_id, list(output_ids))
    server.database.set_job_deletion_protection("catalog-job", True)
    source_history = read_history_json(server.database.database_path)
    plain_prompt = "[Scene]\n{camera|lighting}\n__literal__"
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        listed_images = client.get("/api/outputs/input-images", params={"path": "folder"}).json()["files"]
        assert [image["name"] for image in listed_images] == ["a.png", "b.png"]
        inspection = client.post("/api/outputs/input-images/inspect", json={"output_ids": list(output_ids.values())}).json()["files"]
        assert [(image["width"], image["height"]) for image in inspection] == [(65, 97), (100, 60)]
        response = client.post("/api/batches", json={
            "workflow": "minimax_h3", "body": {"prompt": plain_prompt}, "output_ids": list(output_ids.values()),
            "input_scope": "folder", "input_directory": "folder",
            "settings": {"generation_mode": generation_mode, "resolution_mode": "automatic", "width": 640, "height": 480},
        })
        assert response.status_code == 200, response.text
        wait_for_submissions(comfy_client, 2)
        job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
        assert job["inputs"]["settings"]["width"] == 65
        assert job["inputs"]["settings"]["resolution_reference"]["path"] == "folder/a.png"
        for request_workflow, request_metadata in comfy_client.submissions:
            director = request_workflow["2730"]["inputs"]
            assert director["mode"] == execution_mode
            assert (director["width"], director["height"]) == (96, 128)
            timeline = json.loads(director["timeline_data"])
            assert [image["slot"] for image in timeline["items"]] == endpoint_slots
            assert len({image["value"] for image in timeline["items"]}) == 1
            assert json.loads(director["builder_state"])["mode"] == timeline["builder_state"]["mode"] == execution_mode
            assert timeline["resolution"]["input_scaling"] == "Off"
            assert timeline["resolution"]["custom_mode"] == "fixed"
            assert director["external_prompt_overwrite"] == timeline["resolved_prompt"] == plain_prompt
            metadata_director = next(node for node in request_metadata["workflow"]["nodes"] if str(node["id"]) == "2730")
            assert metadata_director["widgets_values_named"]["mode"] == execution_mode
            assert request_metadata["home_server_request"]["settings"]["width"] == 96
        assert [request["result"]["source_image"]["path"] for request in job["requests"]] == ["folder/a.png", "folder/b.png"]
        assert all(image["size"] == (96, 128) and image["center"] == (255, 0, 0) for image in comfy_client.uploaded_images)
        assert comfy_client.uploaded_images[1]["corner"] == (0, 0, 0)
        assert comfy_client.wildcard_prompts == []
        current_source_history = read_history_json(server.database.database_path)
        for history_key, original_rows in source_history.items():
            for original_row in original_rows:
                assert original_row in current_source_history[history_key]


@pytest.mark.parametrize("input_scope", ["single", "folder"])
def test_snapshot_survives_original_deletion_and_manual_resolution_is_preserved(tmp_path: Path, input_scope: str) -> None:
    """접수 후 원본이 없어져도 임시 입력을 사용하며 직접 입력한 공통 해상도와 출처는 유지합니다."""

    comfy_client = CapturingImageClient(block_upload=True)
    application = create_processing_test_app(tmp_path, comfy_client)
    server = application.state.home_server
    input_definitions = [("input.png", (200, 100))]
    if input_scope == "folder":
        input_definitions.append(("second.png", (100, 200)))
    output_ids = add_input_images(server, input_definitions)
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            response = client.post("/api/batches", json={
                "workflow": "minimax_h3", "body": {"prompt": "still image"}, "output_ids": list(output_ids.values()),
                "input_scope": input_scope, "input_directory": "" if input_scope == "folder" else None,
                "settings": {"generation_mode": "L2VA", "resolution_mode": "manual", "width": 128, "height": 96},
            })
            assert response.status_code == 200
            assert comfy_client.upload_started.wait(3)
            for source_name, dimensions in input_definitions:
                (server.config.managed_output_directory / source_name).unlink()
            comfy_client.release_upload.set()
            wait_for_submissions(comfy_client, len(input_definitions))
            assert comfy_client.uploaded_images[0]["size"] == (128, 96)
            request_workflow, metadata = comfy_client.submissions[0]
            assert metadata["home_server_request"]["source_image"]["path"] == "input.png"
            deadline = time.monotonic() + 3
            while list(server.upload_directory.iterdir()) and time.monotonic() < deadline:
                time.sleep(0.02)
            assert list(server.upload_directory.iterdir()) == []
    finally:
        comfy_client.release_upload.set()


def test_selection_boundaries_tombstones_and_atomic_failure_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """잘못된 ID·폴더·개수·모드와 일부 Snapshot 실패가 빈 작업이나 임시 찌꺼기를 남기지 않습니다."""

    application = create_processing_test_app(tmp_path, CapturingImageClient())
    server = application.state.home_server
    output_ids = add_input_images(server, [("folder/a.png", (64, 96)), ("other/b.png", (64, 96))])
    (server.config.managed_output_directory / "folder/broken.png").write_bytes(b"broken")
    (server.config.managed_output_directory / "folder/movie.mp4").write_bytes(b"video")
    server.output_catalog.synchronize(server.config.managed_output_directory)
    with sqlite3.connect(server.database.database_path) as connection:
        output_ids = dict(connection.execute("SELECT relative_path,output_id FROM output_files"))
    payload = {"workflow": "minimax_h3", "body": {"prompt": "video"}, "output_ids": [output_ids["folder/a.png"]], "input_scope": "single"}
    with TestClient(application) as client:
        assert client.get("/api/outputs/input-images").status_code == 401
        client.post("/api/login", json={"password": "test"})
        for changes in [
            {"output_ids": [999999]}, {"output_ids": [-1]},
            {"output_ids": [output_ids["folder/movie.mp4"]]},
            {"output_ids": [output_ids["folder/a.png"]] * 2},
            {"output_ids": list(output_ids.values()), "input_scope": "single"},
            {"input_scope": "folder", "input_directory": "other"},
            {"input_scope": "folder", "input_directory": "../outside"},
            {"settings": {"generation_mode": "REF2VA"}},
            {"settings": {"width": 8193}},
            {"settings": {"width": None}}, {"settings": {"frame_rate": []}},
            {"output_ids": [output_ids["folder/a.png"], output_ids["folder/broken.png"]], "input_scope": "folder", "input_directory": "folder"},
            {"upload_ids": ["a" * 32]},
        ]:
            response = client.post("/api/batches", json={**payload, **changes})
            assert response.status_code == 422, response.text
            assert list(server.upload_directory.iterdir()) == []
        assert client.post("/api/outputs/input-images/inspect", json={"output_ids": [1] * 101}).status_code == 422
        assert client.post("/api/batches", json={**payload, "output_ids": [1] * 101}).status_code == 422
        assert client.get("/api/jobs").json()["total"] == 0

        assert client.delete(f"/api/outputs/{output_ids['folder/a.png']}").status_code == 200
        assert client.post("/api/outputs/input-images/inspect", json={"output_ids": payload["output_ids"]}).status_code == 422
        assert all(image["name"] != "a.png" for image in client.get("/api/outputs/input-images", params={"path": "folder"}).json()["files"])

        def reject_job_storage(*arguments, **keyword_arguments) -> None:
            """DB 기록 실패를 재현하여 생성한 Snapshot 회수를 확인합니다."""

            raise ValueError("job storage failed")

        monkeypatch.setattr(server.database, "add_job", reject_job_storage)
        assert client.post("/api/batches", json={**payload, "output_ids": [output_ids["other/b.png"]]}).status_code == 422
        assert list(server.upload_directory.iterdir()) == []


def test_input_directory_link_cannot_escape_the_result_root(tmp_path: Path) -> None:
    """후보 조회·해상도 확인·Snapshot 생성 모두 외부 symlink 또는 junction 부모를 거부합니다."""

    application = create_processing_test_app(tmp_path, CapturingImageClient())
    server = application.state.home_server
    output_ids = add_input_images(server, [("source.png", (32, 32))])
    outside_directory = tmp_path / "outside-input"
    outside_directory.mkdir()
    Image.new("RGB", (32, 32), "blue").save(outside_directory / "source.png")
    alias_directory = server.config.managed_output_directory / "alias"
    try:
        alias_directory.symlink_to(outside_directory, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        subprocess.run(["cmd", "/c", "mklink", "/J", str(alias_directory), str(outside_directory)], check=True, capture_output=True)
    with sqlite3.connect(server.database.database_path) as connection:
        connection.execute("UPDATE output_files SET relative_path='alias/source.png'")
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        assert client.get("/api/outputs/input-images", params={"path": "alias"}).status_code == 422
        assert client.post("/api/outputs/input-images/inspect", json={"output_ids": list(output_ids.values())}).status_code == 422
        assert client.post("/api/batches", json={
            "workflow": "minimax_h3", "body": {"prompt": "video"}, "input_scope": "single", "output_ids": list(output_ids.values()),
        }).status_code == 422
        assert list(server.upload_directory.iterdir()) == []


def test_actual_exif_dimensions_and_template_isolation(tmp_path: Path) -> None:
    """생성 요청 크기 대신 EXIF 방향을 읽고 공통 템플릿에 이전 모드나 Reference를 남기지 않습니다."""

    application = create_processing_test_app(tmp_path, CapturingImageClient())
    server = application.state.home_server
    image_path = server.config.managed_output_directory / "oriented.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (80, 40), "red").save(image_path, exif=exif)
    server.output_catalog.synchronize(server.config.managed_output_directory)
    output_id = server.output_catalog.list_files(1, 64)["files"][0]["output_id"]
    with sqlite3.connect(server.database.database_path) as connection:
        connection.execute("UPDATE output_files SET requested_width=999,requested_height=777")
    inspection = inspect_input_images(server.config.managed_output_directory, server.output_catalog, [output_id])[0]
    assert (inspection["width"], inspection["height"]) == (40, 80)
    prepared_path = prepare_input_canvas(image_path, 64, 96)
    with Image.open(prepared_path) as prepared_image:
        assert prepared_image.size == (64, 96)
        assert prepared_image.getexif().get(274) is None
    api_template, ui_template = load_workflows(server.config.workflow_directory, "minimax_h3")
    original_api = copy.deepcopy(api_template)
    original_ui = copy.deepcopy(ui_template)
    for generation_mode in ("F2VA", "L2VA", "FL2VA", "F2VA"):
        request_workflow, metadata = prepare_minimax(api_template, ui_template, "input.png", "plain", {"generation_mode": generation_mode}, [], "from_home_server/minimax_h3/test")
        timeline = json.loads(request_workflow["2730"]["inputs"]["timeline_data"])
        assert all(image["type"] == "image" for image in timeline["items"])
        assert "refmods" not in timeline and "continuity" not in timeline
    assert api_template == original_api
    assert ui_template == original_ui


def test_folder_candidates_ignore_pagination_and_snapshot_byte_limit_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """100장을 넘는 폴더 후보도 모두 표시하며 크기 제한 위반은 작업과 Snapshot을 남기지 않습니다."""

    application = create_processing_test_app(tmp_path, CapturingImageClient())
    server = application.state.home_server
    output_ids = add_input_images(server, [(f"folder/{image_number:03d}.png", (32, 32)) for image_number in range(101)])
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        listing = client.get("/api/outputs/input-images", params={"path": "folder"}).json()["files"]
        assert len(listing) == 101
        assert listing[0]["name"] == "000.png" and listing[-1]["name"] == "100.png"
        monkeypatch.setattr("home_server.minimax_inputs.MAX_INPUT_BYTES", 1)
        response = client.post("/api/batches", json={
            "workflow": "minimax_h3", "body": {"prompt": "video"}, "input_scope": "single",
            "output_ids": [output_ids["folder/000.png"]],
        })
        assert response.status_code == 422
        assert list(server.upload_directory.iterdir()) == []
        assert client.get("/api/jobs").json()["total"] == 0


def test_snapshot_collision_never_removes_an_existing_upload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """임시 이름 충돌을 강제해도 이전 요청의 입력 파일은 삭제하지 않습니다."""

    application = create_processing_test_app(tmp_path, CapturingImageClient())
    server = application.state.home_server
    output_ids = add_input_images(server, [("image.png", (32, 32))])
    existing_path = server.upload_directory / f"{'c' * 32}.png"
    existing_path.write_bytes(b"previous input")
    monkeypatch.setattr("home_server.minimax_inputs.uuid.uuid4", lambda: SimpleNamespace(hex="c" * 32))
    with pytest.raises(FileExistsError):
        snapshot_input_images(server.config.managed_output_directory, server.output_catalog, server.upload_directory, list(output_ids.values()), "single", None)
    assert existing_path.read_bytes() == b"previous input"

