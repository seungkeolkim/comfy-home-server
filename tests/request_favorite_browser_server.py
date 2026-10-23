"""운영 DB·ComfyUI와 분리된 요청 즐겨찾기 Browser 검증 서버입니다."""

import json
import sys
from pathlib import Path

import uvicorn
from PIL import Image

from home_server.application import create_app
from home_server.configuration import AppConfig, PROJECT_DIRECTORY
from test_application import FakeComfyClient
from test_request_favorites import prepare_favorite_job


def create_favorite_browser_application(runtime_directory: Path, workflow: str = "anima"):
    """원본 태그가 현재 DB에 없는 요청과 상하위 분류를 준비합니다."""

    output_directory = runtime_directory / "outputs"
    configuration = AppConfig(
        host="127.0.0.1", port=0, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory, managed_output_directory=output_directory,
        runtime_directory=runtime_directory, workflow_directory=PROJECT_DIRECTORY / "data/workflows",
        video_preview_warmup_enabled=False,
    )
    application = create_app(configuration)
    server = application.state.home_server
    server.comfy = FakeComfyClient()
    if workflow == "minimax_h3":
        output_directory.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), "green").save(output_directory / "source.png")
        server.output_catalog.synchronize(output_directory)
        source_identifier = server.output_catalog.list_files(1, 64)["files"][0]["output_id"]
        output_identifier = prepare_favorite_job(server, workflow, {
            "output_id": source_identifier, "path": "source.png", "width": 64, "height": 64,
        })[0]
        server.database.favorites.save_output(output_identifier, output_directory)
        with server.database._connect() as connection:
            favorite = connection.execute("SELECT favorite_id,snapshot_json FROM request_favorites").fetchone()
            snapshot = json.loads(favorite["snapshot_json"])
            snapshot["resolved"]["settings"]["input_scope"] = "job"
            connection.execute("UPDATE request_favorites SET snapshot_json=? WHERE favorite_id=?",
                               (json.dumps(snapshot), favorite["favorite_id"]))
    else:
        prepare_favorite_job(server)
    parent_identifier = server.database.job_folders.save_folder("인물", None)
    child_identifier = server.database.job_folders.save_folder("최종 후보", parent_identifier)
    server.database.job_folders.save_folder("배경", None)
    server.database.job_folders.move_jobs(["favorite-job"], child_identifier)
    return application


if __name__ == "__main__":
    workflow = sys.argv[3] if len(sys.argv) > 3 else "anima"
    uvicorn.run(create_favorite_browser_application(Path(sys.argv[1]), workflow), host="127.0.0.1", port=int(sys.argv[2]), log_level="warning")
