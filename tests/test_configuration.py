"""호스트와 컨테이너의 설정 경로 선택을 검증합니다."""

from pathlib import Path

import pytest

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
    assert config.thumbnail_cache_max_entries == 10_000
    assert config.thumbnail_cache_warmup_enabled is False


@pytest.mark.parametrize("output_settings, expected_error", [
    ("thumbnail_cache_max_entries = 0", "thumbnail_cache_max_entries"),
    ("thumbnail_cache_max_entries = -1", "thumbnail_cache_max_entries"),
    ("thumbnail_cache_max_entries = true", "thumbnail_cache_max_entries"),
    ('thumbnail_cache_max_entries = "10000"', "thumbnail_cache_max_entries"),
    ("thumbnail_cache_max_entries = 2.5", "thumbnail_cache_max_entries"),
    ('thumbnail_cache_warmup_enabled = "false"', "thumbnail_cache_warmup_enabled"),
    ("thumbnail_cache_warmup_enabled = 1", "thumbnail_cache_warmup_enabled"),
    ("thumbnail_cache_max_entries = 3\nthumbnail_cache_warmup_enabled = true", ""),
])
def test_thumbnail_cache_configuration(tmp_path: Path, output_settings: str, expected_error: str) -> None:
    """개수와 기동 시 채우기 설정을 읽고 타입·범위 오류를 명확히 거부합니다."""

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[server]\nhost = "127.0.0.1"\nport = 8388\npassword = "test"\n'
        '[comfy]\nendpoint = "http://example.test"\noutput_directory = "output"\n'
        'managed_output_folder = "from_home_server"\n[outputs]\n' + output_settings,
        encoding="utf-8",
    )
    if expected_error:
        with pytest.raises(ValueError, match=expected_error):
            load_config(config_path)
    else:
        configuration = load_config(config_path)
        assert configuration.thumbnail_cache_max_entries == 3
        assert configuration.thumbnail_cache_warmup_enabled is True
