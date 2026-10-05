"""설정된 주소와 포트에서 웹 서버를 실행합니다."""

import uvicorn

from .configuration import load_config


def main() -> None:
    """config.toml의 host와 port로 ASGI 서버를 시작합니다."""

    config = load_config()
    uvicorn.run("home_server.application:app", host=config.host, port=config.port)


if __name__ == "__main__":
    main()
