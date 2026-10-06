"""호스트와 컨테이너의 설정 경로 선택을 검증합니다."""

from pathlib import Path

from home_server.configuration import load_config


def test_environment_overrides_comfy_connection_and_output_path(tmp_path: Path, monkeypatch) -> None:
    """컨테이너 환경변수가 로컬 TOML의 ComfyUI 경로를 대체합니다."""

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """[server]
host = "127.0.0.1"
port = 8388
password = "test-password"

[comfy]
endpoint = "http://127.0.0.1:8188"
output_directory = "unused-output"
managed_output_folder = "from_home_server"
""",
        encoding="utf-8",
    )
    mounted_output_directory = tmp_path / "mounted-output"
    monkeypatch.setenv("HOME_SERVER_COMFY_ENDPOINT", "http://host.docker.internal:8188")
    monkeypatch.setenv("HOME_SERVER_COMFY_OUTPUT_DIRECTORY", str(mounted_output_directory))

    config = load_config(config_path)

    assert config.comfy_endpoint == "http://host.docker.internal:8188"
    assert config.comfy_output_directory == mounted_output_directory.resolve()
    assert config.managed_output_directory == mounted_output_directory.resolve() / "from_home_server"
