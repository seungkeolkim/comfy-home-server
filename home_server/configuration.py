"""애플리케이션 설정을 읽고 경로를 검증합니다."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIRECTORY = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppConfig:
    """웹 서버와 ComfyUI 연결에 필요한 설정을 보관합니다."""

    host: str
    port: int
    password: str
    comfy_endpoint: str
    comfy_output_directory: Path
    managed_output_directory: Path
    runtime_directory: Path
    workflow_directory: Path


def load_config(config_path: Path | None = None) -> AppConfig:
    """TOML 설정을 읽고 관리 폴더가 output 내부인지 확인합니다."""

    selected_path = config_path or PROJECT_DIRECTORY / "config.toml"
    with selected_path.open("rb") as config_file:
        config_data = tomllib.load(config_file)

    server_data = config_data["server"]
    comfy_data = config_data["comfy"]
    configured_output_directory = os.environ.get(
        "HOME_SERVER_COMFY_OUTPUT_DIRECTORY", str(comfy_data["output_directory"])
    )
    output_directory = Path(configured_output_directory).expanduser().resolve()
    managed_folder = str(comfy_data["managed_output_folder"])
    managed_directory = (output_directory / managed_folder).resolve()

    if managed_directory == output_directory or output_directory not in managed_directory.parents:
        raise ValueError("managed_output_folder는 ComfyUI output의 하위 폴더여야 합니다.")
    if not server_data["password"]:
        raise ValueError("서버 비밀번호가 비어 있습니다.")

    return AppConfig(
        host=str(server_data["host"]),
        port=int(server_data["port"]),
        password=str(server_data["password"]),
        comfy_endpoint=os.environ.get("HOME_SERVER_COMFY_ENDPOINT", str(comfy_data["endpoint"])).rstrip("/"),
        comfy_output_directory=output_directory,
        managed_output_directory=managed_directory,
        runtime_directory=PROJECT_DIRECTORY / "runtime",
        workflow_directory=PROJECT_DIRECTORY / "data" / "workflows",
    )
