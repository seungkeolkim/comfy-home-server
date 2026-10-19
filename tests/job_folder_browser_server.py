"""운영 데이터와 분리된 이력 폴더 Browser 검증 서버입니다."""

import sys
from pathlib import Path

import uvicorn
from PIL import Image

from home_server.application import create_app
from home_server.configuration import AppConfig, PROJECT_DIRECTORY
from test_application import FakeComfyClient
from test_output_catalog import add_catalog_test_request


def create_job_folder_browser_application(runtime_directory: Path):
    """두 페이지 이상의 이력과 깊이 3 폴더·보호 작업·실제 이미지를 준비합니다."""

    output_directory = runtime_directory / "outputs"
    output_directory.mkdir(parents=True, exist_ok=True)
    configuration = AppConfig(
        host="127.0.0.1", port=0, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory, managed_output_directory=output_directory,
        runtime_directory=runtime_directory, workflow_directory=PROJECT_DIRECTORY / "data/workflows",
        video_preview_warmup_enabled=False,
    )
    application = create_app(configuration)
    server = application.state.home_server
    server.comfy = FakeComfyClient()
    database = server.database
    root_id = database.job_folders.save_folder("인물 A", None)
    child_id = database.job_folders.save_folder("표정 비교", root_id)
    leaf_id = database.job_folders.save_folder("최종 후보", child_id)
    database.job_folders.save_folder("배경 실험", None)
    for job_index in range(24):
        job_id = f"folder-job-{job_index}"
        request_id = add_catalog_test_request(database, job_id)
        database.update_job_description(job_id, f"조명 비교 {job_index}" if job_index < 12 else f"다른 실험 {job_index}")
        if job_index < 22:
            database.job_folders.move_jobs([job_id], leaf_id if job_index % 2 else root_id)
        image_names = []
        for image_index in range(3):
            image_name = f"{job_id}-{image_index}.png"
            Image.new("RGB", (128, 96), (job_index * 9, 80 + image_index * 40, 140)).save(output_directory / image_name)
            image_names.append(image_name)
        database.complete_request(request_id, image_names)
    database.set_job_deletion_protection("folder-job-21", True)
    database.add_job("running-job", "anima", "보호 실행 중", [{
        "request_id": "running-request", "status": "running", "output_stem": "running",
        "detail": {"body": {"prompt": "실행 중 보존"}, "settings": {"width": 768, "height": 512}},
    }], root_id)
    database.set_job_deletion_protection("running-job", True)
    return application


if __name__ == "__main__":
    uvicorn.run(create_job_folder_browser_application(Path(sys.argv[1])), host="127.0.0.1", port=int(sys.argv[2]), log_level="warning")
