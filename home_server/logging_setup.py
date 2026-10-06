"""애플리케이션 로그를 콘솔과 크기 제한 파일에 기록합니다."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_application_logging(runtime_directory: Path) -> Path:
    """기존 handler를 정리하고 runtime 아래에 회전 로그를 설정합니다."""

    log_directory = runtime_directory / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / "home_server.log"
    application_logger = logging.getLogger("home_server")

    for existing_handler in application_logger.handlers[:]:
        application_logger.removeHandler(existing_handler)
        existing_handler.close()

    log_formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(log_formatter)

    application_logger.setLevel(logging.INFO)
    application_logger.propagate = False
    application_logger.addHandler(console_handler)
    application_logger.addHandler(file_handler)
    return log_path
