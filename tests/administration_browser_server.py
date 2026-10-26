"""운영 데이터와 GPU에 접근하지 않는 관리자 Browser 검증 서버입니다."""

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import uvicorn
from PIL import Image

from home_server.application import create_app
from home_server.configuration import AppConfig, PROJECT_DIRECTORY


class AdministrationBrowserComfyClient:
    """관리자 화면 조회에서만 사용하는 ComfyUI 응답을 재현합니다."""

    async def close(self) -> None:
        """외부 연결을 생성하지 않으므로 정리할 자원이 없습니다."""

    async def list_loras(self) -> list[str]:
        """테스트 서버에서는 LoRA 파일을 제공하지 않습니다."""

        return []

    async def queue(self) -> dict:
        """실제 생성 요청이 없는 빈 Queue를 반환합니다."""

        return {"queue_running": [], "queue_pending": []}

    async def system_resources(self) -> dict:
        """실제 GPU나 운영 서버를 조회하지 않고 자원 표시를 재현합니다."""

        return {"cpu_percent": 0, "ram": {"used": 1024, "total": 2048}, "gpus": []}


def create_administration_browser_application(runtime_directory: Path):
    """Schema가 다른 백업과 복원 후 파일 차이를 확인할 독립 환경을 준비합니다."""

    output_directory = runtime_directory / "outputs"
    configuration = AppConfig(
        host="127.0.0.1", port=0, password="test", comfy_endpoint="http://example.test",
        comfy_output_directory=output_directory, managed_output_directory=output_directory,
        runtime_directory=runtime_directory, workflow_directory=PROJECT_DIRECTORY / "data/workflows",
    )
    application = create_app(configuration)
    server = application.state.home_server
    server.comfy = AdministrationBrowserComfyClient()
    server.database.save_preset("before", "복원 기준 Prompt", "anima", {"prompt": "before"})
    server.administration.create_backup("복원 기준 백업")
    old_backup = server.administration.create_backup("이전 Schema 백업")
    with closing(sqlite3.connect(server.administration.backup_directory / old_backup["file_name"])) as connection:
        connection.execute("PRAGMA user_version = 13")
    server.database.save_preset("after", "이후 변경 Prompt", "anima", {"prompt": "after"})
    Image.new("RGB", (64, 64), "teal").save(output_directory / "unregistered.png")
    return application


if __name__ == "__main__":
    uvicorn.run(create_administration_browser_application(Path(sys.argv[1])), host="127.0.0.1", port=int(sys.argv[2]), log_level="warning")
