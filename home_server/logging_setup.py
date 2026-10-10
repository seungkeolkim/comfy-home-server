"""애플리케이션 로그를 Queue로 전달하고 별도 Thread에서 콘솔·파일에 기록합니다."""

import logging
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from queue import SimpleQueue


APPLICATION_LOG_LISTENER: QueueListener | None = None


def shutdown_application_logging() -> None:
    """로그 Queue를 모두 비운 뒤 Listener와 실제 출력 Handler를 닫습니다."""

    global APPLICATION_LOG_LISTENER
    if APPLICATION_LOG_LISTENER is None:
        return
    listener = APPLICATION_LOG_LISTENER
    APPLICATION_LOG_LISTENER = None
    application_logger = logging.getLogger("home_server")
    for handler in application_logger.handlers[:]:
        if isinstance(handler, QueueHandler) and handler.queue is listener.queue:
            application_logger.removeHandler(handler)
            handler.close()
    listener.stop()
    for handler in listener.handlers:
        handler.close()


def configure_application_logging(runtime_directory: Path) -> Path:
    """기존 출력 처리를 정리하고 Queue Listener로 회전 로그를 시작합니다."""

    global APPLICATION_LOG_LISTENER
    shutdown_application_logging()
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
    log_queue = SimpleQueue()
    application_logger.addHandler(QueueHandler(log_queue))
    APPLICATION_LOG_LISTENER = QueueListener(
        log_queue, console_handler, file_handler, respect_handler_level=True,
    )
    APPLICATION_LOG_LISTENER.start()
    return log_path
