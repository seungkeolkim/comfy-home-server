"""운영 데이터와 GPU를 사용하지 않는 실제 생성 UI 검증 서버입니다."""

import sys
from pathlib import Path

import uvicorn

from test_application import create_processing_test_app
from test_style_generation import StyleComfyClient


def create_style_generation_browser_application(runtime_directory: Path):
    """실제 임시 PNG를 저장하는 격리 Home 인스턴스를 준비합니다."""

    fake_client = StyleComfyClient()
    application = create_processing_test_app(runtime_directory.resolve(), fake_client)
    fake_client.output_directory = application.state.home_server.config.comfy_output_directory
    return application


if __name__ == "__main__":
    uvicorn.run(create_style_generation_browser_application(Path(sys.argv[1])), host="127.0.0.1", port=int(sys.argv[2]), log_level="warning")
