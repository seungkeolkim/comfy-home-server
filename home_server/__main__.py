"""설정된 주소와 포트에서 웹 서버를 실행합니다."""

import argparse

import uvicorn

from .configuration import PROJECT_DIRECTORY, load_config


def main() -> None:
    """config.toml의 주소로 서버를 시작하고 필요하면 Python 코드를 감시합니다."""

    argument_parser = argparse.ArgumentParser(description="Comfy Home Server를 실행합니다.")
    argument_parser.add_argument("--reload", action="store_true", help="Python 코드 변경 시 서버를 재시작합니다.")
    arguments = argument_parser.parse_args()
    config = load_config()
    watched_directories = [str(PROJECT_DIRECTORY / "home_server")] if arguments.reload else None
    uvicorn.run(
        "home_server.application:app",
        host=config.host,
        port=config.port,
        reload=arguments.reload,
        reload_dirs=watched_directories,
    )


if __name__ == "__main__":
    main()
