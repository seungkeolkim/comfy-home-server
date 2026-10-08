"""Module import는 실제 DB를 열지 않고 서버 실행 때만 앱을 만드는지 검증합니다."""

import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from home_server import __main__ as server_entrypoint
from home_server.configuration import PROJECT_DIRECTORY


def test_application_import_does_not_initialize_runtime() -> None:
    """새 Python process의 import만으로 실제 DB 초기화나 migration이 실행되지 않습니다."""

    import_check_script = """
from unittest.mock import patch

with patch('home_server.database.Database', side_effect=AssertionError('import opened the runtime DB')):
    import home_server.application
"""
    result = subprocess.run(
        [sys.executable, "-c", import_check_script], cwd=PROJECT_DIRECTORY,
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("reload_enabled", [False, True])
def test_server_entrypoint_uses_application_factory(monkeypatch: pytest.MonkeyPatch, reload_enabled: bool) -> None:
    """일반 실행과 reload 모두 서버 process에서 앱 factory를 호출합니다."""

    server_arguments = ["home_server"]
    if reload_enabled:
        server_arguments.append("--reload")
    server_runner = Mock()
    monkeypatch.setattr(sys, "argv", server_arguments)
    monkeypatch.setattr(server_entrypoint, "load_config", lambda: SimpleNamespace(host="127.0.0.1", port=8388))
    monkeypatch.setattr(server_entrypoint.uvicorn, "run", server_runner)
    server_entrypoint.main()
    server_runner.assert_called_once_with(
        "home_server.application:create_app", factory=True, host="127.0.0.1", port=8388,
        reload=reload_enabled,
        reload_dirs=[str(PROJECT_DIRECTORY / "home_server")] if reload_enabled else None,
    )
