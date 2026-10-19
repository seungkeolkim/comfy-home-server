"""실제 Codec·점진 HTTP 재생을 검증하는 독립 서버이며 운영 데이터에 접근하지 않습니다."""

import shutil
import sys
from pathlib import Path

import uvicorn

from home_server.application import create_app
from home_server.configuration import AppConfig, PROJECT_DIRECTORY
from home_server import video_encoding
from test_application import FakeComfyClient


def create_browser_test_application(runtime_directory: Path):
    """준비/변환 중/실패 원본을 가진 독립 앱과 저속 변환을 준비합니다."""

    output_directory = runtime_directory / "outputs"
    output_directory.mkdir(parents=True, exist_ok=True)
    source_path = output_directory / "progressive.mp4"
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
        "-f", "lavfi", "-i", "sine=frequency=500:sample_rate=44100", "-t", "8",
        "-c:v", "libx264", "-c:a", "aac", "-threads", "1", "-y", str(source_path),
    ]
    video_encoding.subprocess.run(command, check=True, capture_output=True, timeout=30)
    shutil.copyfile(source_path, output_directory / "ready.mp4")
    shutil.copyfile(source_path, output_directory / "failed.mp4")
    configuration = AppConfig(
        host="127.0.0.1", port=0, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory, managed_output_directory=output_directory,
        runtime_directory=runtime_directory, workflow_directory=PROJECT_DIRECTORY / "data/workflows",
        video_preview_warmup_enabled=False,
    )
    app = create_app(configuration)
    app.state.home_server.comfy = FakeComfyClient()
    cache = app.state.home_server.video_previews
    sources = {Path(row["relative_path"]).stem: row["output_id"] for row in cache.catalog.iter_video_sources()}
    ready_source = cache.source(sources["ready"])
    ready_directory = cache.directory("previews", ready_source.identifier, create=True)
    video_encoding.encode_video_preview(ready_source.path, ready_directory / "preview.mp4", configuration, cache._stop,
                                       video_encoding.ignore_started_process)
    cache._write_metadata(ready_directory, {**ready_source.metadata(), "complete": True})
    failed_source = cache.source(sources["failed"])
    cache._write_metadata(cache.directory("previews", failed_source.identifier, create=True),
                          {**failed_source.metadata(), "failed": True, "attempts": 3, "error": "test failure"})
    original_process_runner = video_encoding.run_video_process

    def slow_video_process(command, output_path, stop_event, timeout_seconds, process_started):
        """변환 완료 전 재생을 관찰할 수 있도록 입력 읽기 속도만 실시간으로 제한합니다."""

        modified_command = list(command)
        input_index = modified_command.index("-i")
        modified_command[input_index:input_index] = ["-readrate", "1"]
        return original_process_runner(modified_command, output_path, stop_event, timeout_seconds, process_started)

    video_encoding.run_video_process = slow_video_process

    @app.get("/api/test-video-sources")
    def browser_test_sources():
        """회귀 스크립트가 이름에 해당하는 격리 원본 ID만 확인하게 합니다."""

        return sources

    return app


if __name__ == "__main__":
    uvicorn.run(create_browser_test_application(Path(sys.argv[1])), host="127.0.0.1", port=int(sys.argv[2]), log_level="warning")
