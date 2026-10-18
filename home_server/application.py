"""Comfy Home Server의 HTTP API와 작업 실행을 제공합니다."""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
import secrets
import shutil
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator, model_validator

from .comfy_client import ComfyClient
from .configuration import AppConfig, PROJECT_DIRECTORY, load_config
from .database import Database
from .image_dimension_cache import ImageDimensionCache
from .logging_setup import configure_application_logging, shutdown_application_logging
from .output_catalog import OutputCatalog
from .output_listing import MEDIA_EXTENSIONS
from .output_timing import OutputTimingRecorder, measure_output_step
from .tag_builder import MAX_SELECTED_TAGS, anima_negative_prompt, anima_prompt, resolve_anima_prompts, validate_tag_selection
from .thumbnail_cache import PREVIEW_IMAGE_EXTENSIONS, PREVIEW_SIZE, ThumbnailCache, ThumbnailTooLargeError
from .workflows import WORKFLOW_OUTPUT_NAMES, load_workflows, prepare_anima, prepare_minimax


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
LOGGER = logging.getLogger(__name__)
CANCEL_CONFIRMATION_SECONDS = 15
MISSING_REQUEST_GRACE_SECONDS = 30
IMAGE_DIMENSION_CACHE = ImageDimensionCache()


def image_dimensions(image_path: Path) -> tuple[int, int] | None:
    """이미지 전체를 디코딩하지 않고 표시 방향에 맞는 크기를 읽습니다."""

    try:
        with Image.open(image_path) as source_image:
            width, height = source_image.size
            if source_image.getexif().get(274) in {5, 6, 7, 8}:
                width, height = height, width
            return width, height
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None


def cached_image_dimensions(image_path: Path) -> tuple[int, int] | None:
    """stat 없이 실제 이미지 크기를 시간 만료 없는 경로별 LRU Cache로 재사용합니다."""

    return IMAGE_DIMENSION_CACHE.get_dimensions(image_path, image_dimensions)


def selected_tag_definitions(
    database: Database, selected_tag_ids: list[str], prompt_text: str, negative_text: str = "",
) -> list[dict[str, Any]]:
    """그룹의 현재 참조 태그를 선택 항목에 복사하여 제출 시점의 정의를 검증합니다."""

    if len(selected_tag_ids) != len(set(selected_tag_ids)):
        raise ValueError("같은 태그 항목을 중복 선택할 수 없습니다.")
    if len(selected_tag_ids) > MAX_SELECTED_TAGS:
        raise ValueError(f"태그 항목은 최대 {MAX_SELECTED_TAGS}개 선택할 수 있습니다.")
    definitions = database.get_selected_tag_definitions(selected_tag_ids)
    available_tags = {definition["tag_id"]: definition for definition in definitions}
    missing_tag_ids = [tag_id for tag_id in selected_tag_ids if tag_id not in available_tags]
    if missing_tag_ids:
        raise ValueError("삭제되거나 찾을 수 없는 태그 항목이 선택되었습니다. 목록을 새로고침해 주세요.")
    selected_tags = [available_tags[tag_id] for tag_id in selected_tag_ids]
    validate_tag_selection("\n".join([prompt_text, negative_text]), selected_tags)
    return selected_tags


def plain_prompt(body: dict[str, Any]) -> str:
    """MiniMax Prompt를 조립하거나 wildcard로 확장하지 않고 그대로 반환합니다."""

    prompt_text = body.get("prompt")
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        raise ValueError("MiniMax Prompt를 입력해 주세요.")
    return prompt_text


class LoginInput(BaseModel):
    """로그인 비밀번호를 검증할 요청 형식입니다."""

    password: str


class PresetInput(BaseModel):
    """버전으로 저장할 Prompt preset입니다."""

    preset_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    workflow: str
    body: dict[str, Any]


class PreviewInput(BaseModel):
    """Prompt 확장 미리보기 요청입니다."""

    workflow: str = "anima"
    body: dict[str, Any]
    selected_tag_ids: list[str] = Field(default_factory=list)
    count: int = Field(default=5, ge=1, le=20)


class BatchInput(BaseModel):
    """ComfyUI에 제출할 Batch의 공통 옵션입니다."""

    workflow: str
    description: str = Field(default="", max_length=200)
    body: dict[str, Any]
    selected_tag_ids: list[str] = Field(default_factory=list)
    count: int = Field(default=1, ge=1, le=100)
    settings: dict[str, Any] = Field(default_factory=dict)
    loras: list[dict[str, Any]] = Field(default_factory=list)
    prompt_preset_id: str | None = Field(default=None, max_length=64)
    lora_preset_id: str | None = Field(default=None, max_length=64)
    lora_preset_name: str | None = Field(default=None, max_length=120)
    upload_ids: list[str] = Field(default_factory=list)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        """작업 설명의 공백을 정리하고 여러 줄 입력을 거부합니다."""

        if "\n" in value or "\r" in value:
            raise ValueError("작업 설명은 한 줄로 입력해 주세요.")
        return value.strip()


class JobProtectionInput(BaseModel):
    """상위 작업의 삭제 보호 설정입니다."""

    deletion_protected: bool


class TagGroupInput(BaseModel):
    """태그 그룹의 공통 참조 태그와 표시 설정을 검증합니다."""

    name: str = Field(min_length=1, max_length=120)
    tag_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=64)
    default_expanded: bool = True

    @field_validator("name")
    @classmethod
    def trim_group_name(cls, value: str) -> str:
        """그룹 이름 바깥 공백을 제거하고 빈 이름을 거부합니다."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("그룹 이름을 입력해 주세요.")
        return normalized


class TagEntryInput(BaseModel):
    """참조 태그의 선택지와 치환할 본문을 검증합니다."""

    group_id: str
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=8000)
    weight: float = Field(default=1, gt=0, allow_inf_nan=False)

    @field_validator("name", "content")
    @classmethod
    def trim_tag_text(cls, value: str) -> str:
        """태그 이름과 본문의 바깥 공백을 정리합니다."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("태그 이름과 본문을 입력해 주세요.")
        return normalized


class MoveInput(BaseModel):
    """관리 폴더 안에서 파일을 이동할 요청입니다."""

    source: str
    destination_folder: str


class MoveDestinationInput(BaseModel):
    """여러 결과물을 이동할 관리 폴더 안의 목적지를 검증합니다."""

    destination_folder: str = Field(min_length=1)


class BulkMoveInput(MoveDestinationInput):
    """다중 이동할 결과물 ID를 전달받고 비어 있거나 잘못된 ID를 거부합니다."""

    output_ids: list[int] = Field(min_length=1, max_length=10000)

    @field_validator("output_ids")
    @classmethod
    def validate_output_ids(cls, output_ids: list[int]) -> list[int]:
        """양수 ID만 허용하고 중복 선택은 입력 순서를 유지하여 한 번만 이동합니다."""

        if any(output_id <= 0 for output_id in output_ids):
            raise ValueError("결과물 ID는 양수여야 합니다.")
        return list(dict.fromkeys(output_ids))


class LoraProfileInput(BaseModel):
    """Workflow별 LoRA 기본 강도 설정입니다."""

    name: str
    workflow: str
    strength: float = 1
    clip_strength: float = 1
    video_strength: float = 1
    audio_strength: float = 1


class LoraPresetSelectionInput(BaseModel):
    """조합에 포함할 LoRA 파일과 유한한 강도 값을 검증합니다."""

    name: str = Field(min_length=1, max_length=1024)
    strength: float = Field(default=1, allow_inf_nan=False)
    clip_strength: float = Field(default=1, allow_inf_nan=False)
    video_strength: float = Field(default=1, allow_inf_nan=False)
    audio_strength: float = Field(default=1, allow_inf_nan=False)

    @field_validator("name", mode="before")
    @classmethod
    def trim_file_name(cls, value: Any) -> Any:
        """파일명의 바깥 공백을 제거해 빈 이름을 거부합니다."""

        return value.strip() if isinstance(value, str) else value


class LoraPresetInput(BaseModel):
    """Workflow별 LoRA 조합 preset의 이름과 구성 항목을 검증합니다."""

    name: str = Field(min_length=1, max_length=120)
    workflow: Literal["anima", "minimax_h3"]
    loras: list[LoraPresetSelectionInput] = Field(min_length=1, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def trim_preset_name(cls, value: Any) -> Any:
        """Preset 이름의 바깥 공백을 제거해 빈 이름을 거부합니다."""

        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_combination(self) -> LoraPresetInput:
        """중복 파일과 MiniMax의 LoRA 개수 제한을 검증합니다."""

        selected_names = set()
        for selected_lora in self.loras:
            if selected_lora.name in selected_names:
                raise ValueError("같은 LoRA를 한 조합에 중복 저장할 수 없습니다.")
            selected_names.add(selected_lora.name)
        if self.workflow == "minimax_h3" and len(self.loras) > 10:
            raise ValueError("MiniMax workflow에는 LoRA를 최대 10개 적용할 수 있습니다.")
        return self

    def selected_loras_snapshot(self) -> list[dict[str, Any]]:
        """해당 workflow에서 사용하는 강도만 저장할 snapshot으로 반환합니다."""

        included_fields = {"name", "strength"}
        if self.workflow == "anima":
            included_fields.add("clip_strength")
        else:
            included_fields.update({"video_strength", "audio_strength"})
        return [selected_lora.model_dump(include=included_fields) for selected_lora in self.loras]


class HomeServer:
    """설정, DB, 세션, ComfyUI 연결을 묶습니다."""

    def __init__(self, config: AppConfig) -> None:
        """프로젝트 내부 runtime과 관리 output 폴더를 준비합니다."""

        self.config = config
        self.thumbnail_cache = ThumbnailCache(config.thumbnail_cache_max_entries)
        config.runtime_directory.mkdir(parents=True, exist_ok=True)
        config.managed_output_directory.mkdir(parents=True, exist_ok=True)
        self.upload_directory = config.runtime_directory / "uploads"
        self.upload_directory.mkdir(parents=True, exist_ok=True)
        for stale_upload in self.upload_directory.iterdir():
            if stale_upload.is_file() and time.time() - stale_upload.stat().st_mtime > 24 * 3600:
                stale_upload.unlink()
        self.database = Database(config.runtime_directory / "home_server.sqlite3")
        self.output_catalog = OutputCatalog(self.database.database_path)
        self.output_catalog.synchronize(config.managed_output_directory)
        self.comfy = ComfyClient(config.comfy_endpoint)
        self.sessions: dict[str, float] = {}
        self.login_failures: dict[str, list[float]] = {}
        self.comfy_queue_available: bool | None = None
        self.submission_tasks: set[asyncio.Task[Any]] = set()
        self.request_refresh_lock = asyncio.Lock()
        self.missing_request_since: dict[str, float] = {}
        self.cancellation_retry_after: dict[str, float] = {}
        self.cancellation_wakeup = asyncio.Event()
        self._mark_interrupted_submissions()

    def record_comfy_connection(self, connected: bool, error_type: str | None = None) -> None:
        """ComfyUI 연결 상태가 바뀔 때만 로그를 남깁니다."""

        if self.comfy_queue_available == connected:
            return
        self.comfy_queue_available = connected
        if connected:
            LOGGER.info("ComfyUI 연결 확인")
        else:
            LOGGER.warning("ComfyUI 연결 실패: error_type=%s", error_type)

    def _mark_interrupted_submissions(self) -> None:
        """이전 실행에서 제출되지 못한 작업을 자동 재실행 없이 표시합니다."""

        for request in self.database.list_active_requests():
            if request["status"] == "submitting":
                self.database.update_request(request["request_id"], "stopped", "앱 재시작으로 제출 여부를 확인하지 못했습니다.")
            elif request["status"] == "cancelling" and not request["prompt_id"]:
                self.database.update_request(
                    request["request_id"], "stopped", "앱 재시작으로 제출 중 취소 요청의 접수 여부를 확인하지 못했습니다.",
                )

    def managed_path(self, relative_path: str, must_exist: bool = False) -> Path:
        """관리 output 밖으로 나가는 경로와 symlink를 거부합니다."""

        normalized = relative_path.replace("\\", "/").strip("/")
        if not normalized or any(component in {"", ".", ".."} for component in normalized.split("/")):
            raise ValueError("관리 폴더 안의 상대 경로가 필요합니다.")
        candidate = (self.config.managed_output_directory / normalized).resolve()
        if self.config.managed_output_directory not in candidate.parents:
            raise ValueError("관리 폴더 밖의 경로에는 접근할 수 없습니다.")
        if must_exist and not candidate.exists():
            raise FileNotFoundError(relative_path)
        return candidate


def move_managed_output(
    server: HomeServer, source_relative_path: str, destination_folder: str,
    expected_output_id: int | None = None,
) -> dict[str, Any]:
    """단건·작업·다중 이동에 공통으로 파일 경계와 충돌을 검사하고 FS·DB 경로를 변경합니다."""

    try:
        source_path = server.managed_path(source_relative_path, must_exist=True)
        destination_directory = server.managed_path(destination_folder)
    except (ValueError, FileNotFoundError) as exception:
        raise HTTPException(422, str(exception)) from exception
    normalized_source = source_relative_path.replace("\\", "/")
    if source_path != server.config.managed_output_directory / normalized_source:
        raise HTTPException(422, "symlink 경로의 결과물은 이동할 수 없습니다.")
    if not source_path.is_file() or source_path.suffix.lower() not in MEDIA_EXTENSIONS:
        raise HTTPException(422, "이동할 결과물 파일이 아닙니다.")
    destination_path = destination_directory / source_path.name
    source_relative_path = source_path.relative_to(server.config.managed_output_directory).as_posix()
    destination_relative_path = destination_path.relative_to(server.config.managed_output_directory).as_posix()
    file_was_moved = False

    def move_physical_output() -> None:
        """DB 잠금 안에서 목적지 충돌을 다시 확인하고 실제 파일을 이동합니다."""

        nonlocal file_was_moved
        if destination_path.exists():
            raise HTTPException(409, "목적지에 같은 이름의 파일이 있습니다.")
        destination_directory.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(destination_path))
        file_was_moved = True

    try:
        server.output_catalog.move_file(
            source_relative_path, destination_relative_path, move_physical_output,
            expected_output_id=expected_output_id,
        )
    except sqlite3.Error as exception:
        if file_was_moved:
            shutil.move(str(destination_path), str(source_path))
        raise HTTPException(409, "결과물 경로를 DB에 반영하지 못했습니다.") from exception
    except (OSError, ValueError) as exception:
        raise HTTPException(409, f"파일을 이동할 수 없습니다: {exception}") from exception
    if file_was_moved:
        for changed_path in (source_path, destination_path):
            IMAGE_DIMENSION_CACHE.invalidate(changed_path)
            server.thumbnail_cache.invalidate(changed_path)
    LOGGER.info("결과물 이동: source=%s destination=%s moved=%s", source_relative_path, destination_relative_path, file_was_moved)
    return {"path": destination_relative_path, "moved": file_was_moved}


def move_recorded_outputs(server: HomeServer, output_ids: list[int], destination_folder: str) -> dict[str, Any]:
    """결과물별로 현재 경로에서 이동하고 충돌·누락 등 일부 실패를 성공한 이동과 구분합니다."""

    try:
        server.managed_path(destination_folder)
    except ValueError as exception:
        raise HTTPException(422, str(exception)) from exception
    moved_output_ids = []
    skipped_output_ids = []
    failures = []
    for output_id in output_ids:
        try:
            source_relative_path = server.output_catalog.get_output_path_for_move(output_id)
            movement = move_managed_output(server, source_relative_path, destination_folder, output_id)
            if movement["moved"]:
                moved_output_ids.append(output_id)
            else:
                skipped_output_ids.append(output_id)
        except (LookupError, ValueError) as exception:
            failures.append({"output_id": output_id, "detail": str(exception)})
        except HTTPException as exception:
            failures.append({"output_id": output_id, "detail": exception.detail})
        except sqlite3.Error:
            LOGGER.exception("결과물 이동 DB 조회 실패: output_id=%s", output_id)
            failures.append({"output_id": output_id, "detail": "결과물의 현재 경로를 DB에서 읽지 못했습니다."})
    return {
        "moved_count": len(moved_output_ids), "skipped_count": len(skipped_output_ids),
        "moved_output_ids": moved_output_ids, "skipped_output_ids": skipped_output_ids, "failures": failures,
    }


def store_batch_requests(
    server: HomeServer, payload: BatchInput, selected_tags: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """이미지 존재 확인·요청 구성·DB 저장을 Worker에서 함께 완료합니다."""

    upload_ids = payload.upload_ids if payload.workflow == "minimax_h3" else [None] * payload.count
    if len(upload_ids) > 100:
        raise HTTPException(422, "한 Batch의 요청은 최대 100개입니다.")
    for upload_id in payload.upload_ids:
        if not any(server.upload_directory.glob(f"{upload_id}.*")):
            raise HTTPException(422, f"업로드 파일이 없습니다: {upload_id}")

    job_id = uuid.uuid4().hex[:12]
    request_settings = dict(payload.settings)
    if payload.workflow == "anima":
        request_settings.pop("batch_size", None)
    submitted_requests = []
    for upload_id in upload_ids:
        request_id = uuid.uuid4().hex[:12]
        output_stem = f"{server.config.managed_output_directory.name}/{payload.workflow}/{WORKFLOW_OUTPUT_NAMES[payload.workflow]}"
        request = {
            "request_id": request_id, "job_id": job_id, "workflow": payload.workflow,
            "status": "submitting", "output_stem": output_stem,
            "detail": {"upload_id": upload_id, "body": payload.body, "selected_tags": selected_tags,
                       "settings": request_settings, "loras": payload.loras,
                       "prompt_preset_id": payload.prompt_preset_id,
                       "lora_preset_id": payload.lora_preset_id if payload.loras else None,
                       "lora_preset_name": payload.lora_preset_name if payload.loras else None},
        }
        submitted_requests.append(request)

    server.database.add_job(job_id, payload.workflow, payload.description, submitted_requests)
    return job_id, submitted_requests


def find_uploaded_image(upload_directory: Path, upload_id: str) -> Path:
    """Worker에서 업로드 파일을 찾고 이미 사라진 입력을 명시적으로 표시합니다."""

    for upload_path in upload_directory.glob(f"{upload_id}.*"):
        return upload_path
    raise ValueError("업로드 입력 이미지를 찾을 수 없습니다.")


def clear_batch_uploads(upload_directory: Path, requests: list[dict[str, Any]]) -> None:
    """Batch가 끝난 뒤 임시 입력 파일의 탐색·삭제를 Worker에서 수행합니다."""

    for request in requests:
        upload_id = request["detail"].get("upload_id")
        if upload_id:
            for upload_path in upload_directory.glob(f"{upload_id}.*"):
                upload_path.unlink(missing_ok=True)


def create_app(config: AppConfig | None = None) -> FastAPI:
    """앱 서버와 API route를 구성합니다."""

    server = HomeServer(config or load_config())

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        """서버 종료 시 HTTP 연결과 제출 task를 정리합니다."""

        log_path = configure_application_logging(server.config.runtime_directory)
        LOGGER.info("서버 시작: 로그 파일=%s", log_path)
        if server.config.thumbnail_cache_warmup_enabled:
            server.thumbnail_cache.start_warmup(server.config.managed_output_directory)
        monitor_task = asyncio.create_task(_monitor_requests(server))
        cancellation_task = asyncio.create_task(_monitor_cancellations(server))
        try:
            yield
        finally:
            monitor_task.cancel()
            cancellation_task.cancel()
            await asyncio.gather(monitor_task, cancellation_task, return_exceptions=True)
            for submission_task in list(server.submission_tasks):
                submission_task.cancel()
            if server.submission_tasks:
                await asyncio.gather(*server.submission_tasks, return_exceptions=True)
            await server.comfy.close()
            await asyncio.to_thread(server.thumbnail_cache.stop_warmup)
            LOGGER.info("서버 종료")
            await asyncio.to_thread(shutdown_application_logging)

    app = FastAPI(title="Comfy Home Server", lifespan=lifespan)
    app.state.home_server = server

    @app.middleware("http")
    async def require_authentication(request: Request, call_next):
        """API와 결과물 조회에 session 및 동일 출처 요청을 적용합니다."""

        request_path = request.url.path
        if (request_path.startswith("/api/") and request_path not in {"/api/login", "/api/session"}) or request_path.startswith("/media/"):
            session_token = request.cookies.get("home_session", "")
            expires_at = server.sessions.get(session_token, 0)
            if expires_at < time.time():
                return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host', '')}":
                return JSONResponse({"detail": "허용되지 않은 요청 출처입니다."}, status_code=403)
        output_timing = None
        if request_path == "/api/outputs" or request_path.startswith("/api/outputs/"):
            output_timing = OutputTimingRecorder(request_path)
            request.state.output_timing = output_timing
        try:
            with measure_output_step(output_timing, "http_dispatch", emit=True):
                response = await call_next(request)
        except Exception:
            if output_timing is not None:
                output_timing.finish(500)
            LOGGER.exception("HTTP 요청 처리 실패: %s %s", request.method, request.url.path)
            raise
        if output_timing is not None:
            response.headers["X-Output-Timing-Id"] = output_timing.identifier
            output_timing.finish(response.status_code)
        if response.status_code >= 500:
            LOGGER.error("HTTP 요청 실패: %s %s status=%s", request.method, request.url.path, response.status_code)
        return response

    @app.get("/")
    async def home_page():
        """반응형 웹 앱의 첫 화면을 제공합니다."""

        return FileResponse(PROJECT_DIRECTORY / "web" / "index.html")

    @app.get("/app.css")
    async def style_sheet():
        """웹 앱 CSS를 제공합니다."""

        return FileResponse(PROJECT_DIRECTORY / "web" / "app.css", media_type="text/css")

    @app.get("/app.js")
    async def javascript():
        """웹 앱 JavaScript를 제공합니다."""

        return FileResponse(PROJECT_DIRECTORY / "web" / "app.js", media_type="text/javascript")

    @app.post("/api/login")
    async def login(request: Request, payload: LoginInput):
        """설정 비밀번호로 로그인하고 HttpOnly cookie를 발급합니다."""

        remote_address = request.client.host if request.client else "unknown"
        recent_failures = [attempt for attempt in server.login_failures.get(remote_address, []) if time.time() - attempt < 60]
        if len(recent_failures) >= 10:
            LOGGER.warning("로그인 시도 제한: address=%s", remote_address)
            raise HTTPException(429, "잠시 후 다시 시도해 주세요.")
        if not hmac.compare_digest(payload.password, server.config.password):
            recent_failures.append(time.time())
            server.login_failures[remote_address] = recent_failures
            LOGGER.warning("로그인 실패: address=%s", remote_address)
            raise HTTPException(401, "비밀번호가 맞지 않습니다.")
        server.login_failures.pop(remote_address, None)
        session_token = secrets.token_urlsafe(32)
        server.sessions[session_token] = time.time() + 7 * 24 * 3600
        LOGGER.info("로그인 성공: address=%s", remote_address)
        response = JSONResponse({"authenticated": True})
        response.set_cookie("home_session", session_token, httponly=True, samesite="strict", max_age=7 * 24 * 3600)
        return response

    @app.get("/api/session")
    async def session(request: Request):
        """현재 브라우저의 로그인 여부를 알려줍니다."""

        session_token = request.cookies.get("home_session", "")
        return {"authenticated": server.sessions.get(session_token, 0) > time.time()}

    @app.post("/api/logout")
    async def logout(request: Request):
        """현재 session을 삭제합니다."""

        session_token = request.cookies.get("home_session", "")
        server.sessions.pop(session_token, None)
        response = JSONResponse({"authenticated": False})
        response.delete_cookie("home_session")
        return response

    @app.get("/api/status")
    async def status():
        """ComfyUI 연결과 앱의 경로 설정을 확인합니다."""

        try:
            queue = await server.comfy.queue()
            connected = True
            queue_count = len(queue.get("queue_pending", []))
            server.record_comfy_connection(True)
        except Exception as exception:
            connected = False
            queue_count = None
            server.record_comfy_connection(False, type(exception).__name__)
        return {"comfy_connected": connected, "queue_pending": queue_count, "output_directory": str(server.config.managed_output_directory)}

    @app.get("/api/presets")
    def presets():
        """저장된 Prompt preset을 조회합니다."""

        return JSONResponse(server.database.list_presets())

    @app.post("/api/presets")
    def save_preset(payload: PresetInput):
        """Prompt preset의 새 버전을 저장합니다."""

        if payload.workflow not in {"anima", "minimax_h3"}:
            raise HTTPException(422, "지원하지 않는 workflow입니다.")
        body = dict(payload.body)
        try:
            if payload.workflow == "minimax_h3":
                plain_prompt(body)
            else:
                prompt_text = anima_prompt(body)
                negative_text = body.get("negative", "")
                if not isinstance(negative_text, str):
                    raise ValueError("Negative Prompt 형식이 올바르지 않습니다.")
                body = {"prompt": prompt_text, "negative": negative_text}
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception
        preset_id = payload.preset_id or uuid.uuid4().hex
        return JSONResponse(server.database.save_preset(preset_id, payload.name.strip(), payload.workflow, body))

    @app.get("/api/presets/{preset_id}/versions")
    def preset_versions(preset_id: str):
        """저장된 Prompt의 이전 버전을 보여줍니다."""

        return JSONResponse(server.database.list_preset_versions(preset_id))

    @app.get("/api/tags")
    def list_tags():
        """Anima 태그 항목과 표시 그룹을 함께 반환합니다."""

        return JSONResponse({"groups": server.database.list_tag_groups(), "entries": server.database.list_tag_entries()})

    @app.post("/api/tags/groups", status_code=201)
    def create_tag_group(payload: TagGroupInput):
        """기본 펼침 상태를 포함한 태그 표시 그룹을 만듭니다."""

        created_tag_group = server.database.save_tag_group(
            uuid.uuid4().hex, payload.name, payload.tag_key, payload.default_expanded,
        )
        return JSONResponse(created_tag_group, status_code=201)

    @app.put("/api/tags/groups/{group_id}")
    def update_tag_group(group_id: str, payload: TagGroupInput):
        """존재하는 그룹의 이름과 기본 펼침 상태를 수정합니다."""

        if server.database.get_tag_group(group_id) is None:
            raise HTTPException(404, "태그 그룹을 찾을 수 없습니다.")
        return JSONResponse(server.database.save_tag_group(group_id, payload.name, payload.tag_key, payload.default_expanded))

    @app.delete("/api/tags/groups/{group_id}")
    def delete_tag_group(group_id: str):
        """항목이 없는 표시 그룹만 삭제합니다."""

        try:
            deleted = server.database.delete_tag_group(group_id)
        except sqlite3.IntegrityError as exception:
            raise HTTPException(409, "그룹의 태그 항목을 먼저 이동하거나 삭제해 주세요.") from exception
        if not deleted:
            raise HTTPException(404, "태그 그룹을 찾을 수 없습니다.")
        return JSONResponse({"deleted": True})

    @app.post("/api/tags/entries", status_code=201)
    def create_tag_entry(payload: TagEntryInput):
        """그룹 안에 새 태그 선택지를 저장합니다."""

        if server.database.get_tag_group(payload.group_id) is None:
            raise HTTPException(422, "태그 그룹을 찾을 수 없습니다.")
        return JSONResponse(server.database.save_tag_entry(uuid.uuid4().hex, payload.model_dump()), status_code=201)

    @app.put("/api/tags/entries/{tag_id}")
    def update_tag_entry(tag_id: str, payload: TagEntryInput):
        """안정적인 ID를 유지하며 기존 태그 항목을 수정합니다."""

        if server.database.get_tag_entry(tag_id) is None:
            raise HTTPException(404, "태그 항목을 찾을 수 없습니다.")
        if server.database.get_tag_group(payload.group_id) is None:
            raise HTTPException(422, "태그 그룹을 찾을 수 없습니다.")
        return JSONResponse(server.database.save_tag_entry(tag_id, payload.model_dump()))

    @app.delete("/api/tags/entries/{tag_id}")
    def delete_tag_entry(tag_id: str):
        """현재 태그 정의를 삭제하고 과거 작업 snapshot은 보존합니다."""

        if not server.database.delete_tag_entry(tag_id):
            raise HTTPException(404, "태그 항목을 찾을 수 없습니다.")
        return JSONResponse({"deleted": True})

    @app.post("/api/prompts/preview")
    async def preview(payload: PreviewInput):
        """Anima는 wildcard를 확장하고 MiniMax는 평문을 그대로 보여줍니다."""

        if payload.workflow == "minimax_h3":
            if payload.selected_tag_ids:
                raise HTTPException(422, "MiniMax에는 태그 선택을 사용할 수 없습니다.")
            try:
                prompt_text = plain_prompt(payload.body)
            except ValueError as exception:
                raise HTTPException(422, str(exception)) from exception
            return await asyncio.to_thread(JSONResponse, {
                "combined_prompt": prompt_text, "examples": [{"index": 1, "seed": None, "prompt": prompt_text}],
            })
        if payload.workflow != "anima":
            raise HTTPException(422, "지원하지 않는 workflow입니다.")
        try:
            prompt_text = anima_prompt(payload.body)
            negative_text = anima_negative_prompt(payload.body)
            selected_tags = await asyncio.to_thread(
                selected_tag_definitions, server.database, payload.selected_tag_ids, prompt_text, negative_text,
            )
            examples = []
            for example_index in range(payload.count):
                wildcard_seed = secrets.randbelow(2**31)
                template, negative_template, selected_path, negative_selected_path = await asyncio.to_thread(
                    resolve_anima_prompts, payload.body, selected_tags, wildcard_seed,
                )
                resolved = await server.comfy.populate_wildcards(template, wildcard_seed)
                resolved_negative = await server.comfy.populate_wildcards(negative_template, wildcard_seed)
                examples.append({
                    "index": example_index + 1, "seed": wildcard_seed,
                    "prompt": resolved, "negative": resolved_negative, "selected_path": selected_path,
                    "negative_selected_path": negative_selected_path,
                })
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception
        except Exception as exception:
            raise HTTPException(502, str(exception)) from exception
        return await asyncio.to_thread(JSONResponse, {"combined_prompt": None, "examples": examples})

    @app.get("/api/loras")
    async def loras():
        """ComfyUI에서 현재 확인되는 LoRA 파일 목록을 제공합니다."""

        try:
            available_files = await server.comfy.list_loras()
            profiles = await asyncio.to_thread(server.database.list_lora_profiles)
            return await asyncio.to_thread(JSONResponse, {"files": available_files, "profiles": profiles})
        except Exception as exception:
            raise HTTPException(502, str(exception)) from exception

    @app.post("/api/loras/profiles")
    async def save_lora_profile(payload: LoraProfileInput):
        """선택한 LoRA의 workflow별 기본 강도를 저장합니다."""

        if payload.workflow not in {"anima", "minimax_h3"}:
            raise HTTPException(422, "지원하지 않는 workflow입니다.")
        available_loras = await server.comfy.list_loras()
        if payload.name not in available_loras:
            raise HTTPException(422, "ComfyUI에서 LoRA 파일을 찾을 수 없습니다.")
        settings = payload.model_dump(include={"strength", "clip_strength", "video_strength", "audio_strength"})
        await asyncio.to_thread(server.database.save_lora_profile, payload.name, payload.workflow, settings)
        return {"saved": True}

    @app.get("/api/loras/presets")
    def list_lora_presets():
        """ComfyUI 연결 여부와 관계없이 저장된 LoRA 조합을 조회합니다."""

        return JSONResponse(server.database.list_lora_presets())

    @app.post("/api/loras/presets", status_code=201)
    def create_lora_preset(payload: LoraPresetInput):
        """현재 조합을 새 preset으로 저장합니다."""

        return JSONResponse(server.database.create_lora_preset(
            uuid.uuid4().hex, payload.name, payload.workflow, payload.selected_loras_snapshot(),
        ), status_code=201)

    @app.put("/api/loras/presets/{preset_id}")
    def update_lora_preset(preset_id: str, payload: LoraPresetInput):
        """사용자가 저장한 기존 LoRA 조합을 명시적으로 갱신합니다."""

        updated_preset = server.database.update_lora_preset(
            preset_id, payload.name, payload.workflow, payload.selected_loras_snapshot(),
        )
        if updated_preset is None:
            raise HTTPException(404, "LoRA preset을 찾을 수 없습니다.")
        return JSONResponse(updated_preset)

    @app.delete("/api/loras/presets/{preset_id}")
    def delete_lora_preset(preset_id: str):
        """선택한 LoRA 조합 preset을 삭제합니다."""

        if not server.database.delete_lora_preset(preset_id):
            raise HTTPException(404, "LoRA preset을 찾을 수 없습니다.")
        return JSONResponse({"deleted": True})

    @app.post("/api/uploads")
    def upload(file: UploadFile = File(...)):
        """Mobile 또는 desktop 입력 이미지를 제출 전 임시 저장합니다."""

        original_name = Path(file.filename or "image").name
        extension = Path(original_name).suffix.lower()
        if extension not in IMAGE_EXTENSIONS:
            raise HTTPException(422, "지원하지 않는 이미지 형식입니다.")
        upload_id = uuid.uuid4().hex
        upload_path = server.upload_directory / f"{upload_id}{extension}"
        total_bytes = 0
        try:
            with upload_path.open("wb") as output_file:
                while chunk := file.file.read(1024 * 1024):
                    total_bytes += len(chunk)
                    if total_bytes > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "입력 이미지가 50 MB를 초과합니다.")
                    output_file.write(chunk)
        except Exception:
            upload_path.unlink(missing_ok=True)
            raise
        return JSONResponse({"upload_id": upload_id, "name": original_name, "size": total_bytes})

    @app.post("/api/batches")
    async def submit_batch(payload: BatchInput):
        """작업을 기록하고 ComfyUI 제출을 백그라운드에서 시작합니다."""

        if payload.workflow not in {"anima", "minimax_h3"}:
            raise HTTPException(422, "지원하지 않는 workflow입니다.")
        if payload.workflow == "minimax_h3" and not payload.upload_ids:
            raise HTTPException(422, "MiniMax에는 입력 이미지가 필요합니다.")
        if payload.workflow == "anima" and payload.upload_ids:
            raise HTTPException(422, "Anima는 현재 입력 이미지를 사용하지 않습니다.")
        if any(not re.fullmatch(r"[0-9a-f]{32}", upload_id) for upload_id in payload.upload_ids):
            raise HTTPException(422, "업로드 식별자 형식이 올바르지 않습니다.")
        selected_tags: list[dict[str, Any]] = []
        try:
            if payload.workflow == "minimax_h3":
                if payload.selected_tag_ids:
                    raise ValueError("MiniMax에는 태그 선택을 사용할 수 없습니다.")
                plain_prompt(payload.body)
            else:
                prompt_text = anima_prompt(payload.body)
                negative_text = anima_negative_prompt(payload.body)
                selected_tags = await asyncio.to_thread(
                    selected_tag_definitions, server.database, payload.selected_tag_ids, prompt_text, negative_text,
                )
            available_loras = set(await server.comfy.list_loras()) if payload.loras else set()
            missing_loras = [selected_lora.get("name") for selected_lora in payload.loras if selected_lora.get("name") not in available_loras]
            if missing_loras:
                raise ValueError(f"ComfyUI에서 LoRA를 찾을 수 없습니다: {', '.join(str(name) for name in missing_loras)}")
            await asyncio.to_thread(load_workflows, server.config.workflow_directory, payload.workflow)
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception
        except Exception as exception:
            raise HTTPException(502, str(exception)) from exception

        job_id, submitted_requests = await asyncio.to_thread(store_batch_requests, server, payload, selected_tags)
        submission_task = asyncio.create_task(_submit_requests(server, submitted_requests))
        server.submission_tasks.add(submission_task)
        submission_task.add_done_callback(server.submission_tasks.discard)
        LOGGER.info("Batch 생성: job_id=%s workflow=%s count=%s", job_id, payload.workflow, len(submitted_requests))
        return {"job_id": job_id, "request_ids": [request["request_id"] for request in submitted_requests]}

    @app.get("/api/jobs")
    async def jobs(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1, le=50),
        job_id: str = "",
        refresh: bool = False,
        summary: bool = False,
    ):
        """작업 이력을 페이지 단위로 반환하고 필요하면 요청 상태를 갱신합니다."""

        if refresh:
            await _refresh_requests(server)
        read_jobs = server.database.list_job_summaries if summary else server.database.list_jobs

        def read_job_page_response() -> JSONResponse:
            """목록 조회부터 최종 JSON 직렬화까지 같은 Worker에서 완료합니다."""

            response = read_jobs(page=page, page_size=page_size, job_id=job_id)
            return JSONResponse(response)

        return await asyncio.to_thread(read_job_page_response)

    @app.get("/api/jobs/deletion-candidates")
    def job_deletion_candidates(job_id: str = ""):
        """현재 목록의 모든 페이지에서 삭제 가능한 작업 ID만 반환합니다."""

        return JSONResponse({"job_ids": server.database.list_deletable_job_ids(job_id)})

    @app.get("/api/jobs/activity")
    def jobs_activity():
        """다른 탭에서는 하위 요청을 읽지 않고 활성 작업 수만 반환합니다."""

        return JSONResponse({"active_count": server.database.count_active_jobs()})

    @app.get("/api/jobs/{job_id}/inputs")
    def job_inputs(job_id: str):
        """생성 탭 복원에 필요한 작업 공통 입력을 반환합니다."""

        job = server.database.get_job_inputs(job_id)
        if job is None:
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        return JSONResponse(job)

    @app.get("/api/jobs/{job_id}")
    def job_details(job_id: str):
        """사용자가 펼친 작업의 하위 요청 상세를 반환합니다."""

        job = server.database.get_job(job_id)
        if job is None:
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        return JSONResponse(job)

    @app.patch("/api/jobs/{job_id}/protection")
    def update_job_protection(job_id: str, payload: JobProtectionInput):
        """작업의 삭제 보호를 켜거나 해제합니다."""

        if not server.database.set_job_deletion_protection(job_id, payload.deletion_protected):
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        return JSONResponse({"job_id": job_id, "deletion_protected": payload.deletion_protected})

    @app.post("/api/requests/{request_id}/cancel")
    async def cancel_request(request_id: str):
        """하위 요청의 취소 의도를 기록하고 전송 완료를 기다리지 않고 응답합니다."""

        request = await asyncio.to_thread(server.database.get_submission_state, request_id)
        if request is None:
            raise HTTPException(404, "요청을 찾을 수 없습니다.")
        if request["status"] not in {"submitting", "pending", "running", "cancelling"}:
            raise HTTPException(409, "진행 중인 요청만 취소할 수 있습니다.")
        if not await asyncio.to_thread(server.database.mark_request_cancelling, request_id):
            raise HTTPException(409, "요청이 이미 종료되었습니다.")
        server.cancellation_retry_after.pop(request_id, None)
        server.cancellation_wakeup.set()
        return {"status": "cancelling"}

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        """아직 제출 중인 요청까지 작업 단위 취소를 기록하고 즉시 접수 결과를 반환합니다."""

        requested_count = await asyncio.to_thread(server.database.request_job_cancellation, job_id)
        if requested_count is None:
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        if not requested_count:
            raise HTTPException(409, "취소할 수 있는 요청이 없습니다.")
        active_requests = await asyncio.to_thread(server.database.list_active_requests, job_id=job_id)
        for request in active_requests:
            server.cancellation_retry_after.pop(request["request_id"], None)
        server.cancellation_wakeup.set()
        LOGGER.info("작업 취소 접수: job_id=%s requested_count=%s", job_id, requested_count)
        return {"status": "cancelling", "requested_count": requested_count}

    @app.post("/api/jobs/{job_id}/outputs/move")
    def move_job_outputs(job_id: str, payload: MoveDestinationInput):
        """생성이 끝난 작업의 남아 있는 결과물을 현재 경로에서 목적지 폴더로 이동합니다."""

        try:
            output_ids = server.output_catalog.list_job_output_ids_for_move(job_id)
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        except ValueError as exception:
            raise HTTPException(409, str(exception)) from exception
        return JSONResponse(move_recorded_outputs(server, output_ids, payload.destination_folder))

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str, delete_outputs: bool = False):
        """완료된 작업 이력과 선택한 경우 원래 위치의 결과물을 삭제합니다."""

        job = server.database.get_job(job_id)
        if job is None:
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        if job["deletion_protected"]:
            raise HTTPException(409, "삭제 보호된 작업입니다. 보호를 해제한 뒤 삭제해 주세요.")
        if any(request["status"] in {"submitting", "pending", "running", "cancelling"} for request in job["requests"]):
            raise HTTPException(409, "진행 중인 작업은 삭제할 수 없습니다.")
        deleted_files = 0
        missing_files = 0

        def delete_recorded_outputs() -> list[str]:
            """DB 잠금으로 삭제 보호 변경을 막은 동안 원래 위치의 결과물만 삭제합니다."""

            nonlocal deleted_files, missing_files
            removed_paths = []
            output_paths = {
                path
                for request in job["requests"]
                for path in request["result"].get("output_paths", [])
            }
            for relative_path in sorted(output_paths):
                try:
                    output_path = server.managed_path(relative_path)
                except ValueError:
                    LOGGER.warning("결과물 삭제 경로 제외: job_id=%s path=%s", job_id, relative_path)
                    continue
                original_path = server.config.managed_output_directory / relative_path
                if output_path != original_path or output_path.suffix.lower() not in MEDIA_EXTENSIONS:
                    LOGGER.warning("결과물 삭제 경로 제외: job_id=%s path=%s", job_id, relative_path)
                    continue
                if not output_path.is_file():
                    missing_files += 1
                    removed_paths.append(relative_path)
                    LOGGER.info("원래 위치에 결과물 없음: job_id=%s path=%s", job_id, relative_path)
                    continue
                try:
                    output_path.unlink()
                    removed_paths.append(relative_path)
                except OSError as exception:
                    raise HTTPException(409, f"결과물을 삭제할 수 없습니다: {relative_path}") from exception
                deleted_files += 1
            return removed_paths
        try:
            deleted = server.database.delete_job(job_id, before_deletion=delete_recorded_outputs if delete_outputs else None)
        except ValueError as exception:
            raise HTTPException(409, str(exception)) from exception
        if not deleted:
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        LOGGER.info("작업 이력 삭제: job_id=%s delete_outputs=%s deleted_files=%s missing_files=%s", job_id, delete_outputs, deleted_files, missing_files)
        return JSONResponse({"deleted": True, "deleted_files": deleted_files, "missing_files": missing_files})

    @app.get("/api/outputs")
    def outputs(
        request: Request,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=64, ge=1, le=100),
        prefix: str = "",
        job_id: str = "",
        request_id: str = "",
    ):
        """결과물 index에서 요청 해상도와 정렬된 페이지를 조회합니다."""

        output_timing = request.state.output_timing
        handler_started_at = time.perf_counter()
        output_timing.record("worker_dispatch", output_timing.started_at, emit=True)
        LOGGER.info(
            "OUTPUT_TIMING id=%s event=parameters page=%s page_size=%s job_id=%s request_id=%s",
            output_timing.identifier, page, page_size, job_id or "-", request_id or "-",
        )
        normalized_prefix = prefix.replace("\\", "/")
        if job_id and request_id:
            raise HTTPException(422, "작업과 요청 필터를 동시에 사용할 수 없습니다.")
        if normalized_prefix:
            try:
                server.managed_path(normalized_prefix)
            except ValueError as exception:
                raise HTTPException(422, str(exception)) from exception
        try:
            with measure_output_step(output_timing, "catalog_listing", emit=True):
                listing = server.output_catalog.list_files(
                    page, page_size, normalized_prefix, job_id, request_id, output_timing,
                )
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        with measure_output_step(output_timing, "page_enrichment", emit=True):
            for output_file in listing["files"]:
                if output_file["dimensions_source"] is not None or output_file["kind"] != "image":
                    continue
                file_path = server.config.managed_output_directory / output_file["path"]
                with measure_output_step(output_timing, "image_dimensions_fallback", output_file["path"], emit=True):
                    dimensions = cached_image_dimensions(file_path)
                if dimensions:
                    output_file["width"], output_file["height"] = dimensions
                    output_file["dimensions_source"] = "file"
        with measure_output_step(output_timing, "json_response", emit=True):
            response = JSONResponse(listing)
        output_timing.record("handler_total", handler_started_at, emit=True)
        return response

    @app.get("/api/outputs/deletion-candidates")
    def output_deletion_candidates(job_id: str = "", request_id: str = ""):
        """현재 작업·요청 필터에서 보호되지 않은 이미지의 전체 선택용 ID를 반환합니다."""

        if job_id and request_id:
            raise HTTPException(422, "작업과 요청 필터를 동시에 사용할 수 없습니다.")
        try:
            output_ids = server.output_catalog.list_deletable_output_ids(job_id, request_id)
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        return JSONResponse({"output_ids": output_ids})

    @app.get("/api/outputs/selection-candidates")
    def output_selection_candidates(job_id: str = "", request_id: str = ""):
        """현재 필터의 전체 선택용 ID와 삭제 가능한 ID를 함께 반환합니다."""

        if job_id and request_id:
            raise HTTPException(422, "작업과 요청 필터를 동시에 사용할 수 없습니다.")
        try:
            candidates = server.output_catalog.list_selection_candidates(job_id, request_id)
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        return JSONResponse(candidates)

    @app.post("/api/outputs/sync")
    def synchronize_outputs(request: Request):
        """수동 새로고침에서 현재 파일 목록만 대조하고 실제 크기·해상도는 수집하지 않습니다."""

        output_timing = getattr(request.state, "output_timing", None)
        with measure_output_step(output_timing, "catalog_sync", emit=True):
            return server.output_catalog.synchronize(server.config.managed_output_directory)

    @app.get("/api/outputs/preview/{relative_path:path}")
    def output_preview(relative_path: str, request: Request):
        """현재 파일 버전의 압축된 WebP 썸네일을 LRU Cache에서 제공합니다."""

        output_timing = request.state.output_timing
        output_timing.record("worker_dispatch", output_timing.started_at, emit=True)
        try:
            with measure_output_step(output_timing, "preview_path_resolve", relative_path, emit=True):
                file_path = server.managed_path(relative_path)
        except (ValueError, FileNotFoundError) as exception:
            raise HTTPException(404, str(exception)) from exception
        if server.output_catalog.is_deleted(file_path.relative_to(server.config.managed_output_directory).as_posix()):
            raise HTTPException(404, "삭제된 결과물입니다.")
        with measure_output_step(output_timing, "preview_file_type_check", relative_path, emit=True):
            is_preview_image = file_path.is_file() and file_path.suffix.lower() in PREVIEW_IMAGE_EXTENSIONS
        if not is_preview_image:
            raise HTTPException(404, "미리보기를 지원하지 않는 결과물입니다.")
        try:
            with measure_output_step(output_timing, "preview_file_stat", relative_path, emit=True):
                file_stat = file_path.stat()
        except OSError as exception:
            raise HTTPException(404, "결과물을 찾을 수 없습니다.") from exception
        etag = f'W/"{file_stat.st_mtime_ns:x}-{file_stat.st_size:x}-{PREVIEW_SIZE:x}"'
        cache_headers = {"Cache-Control": "private, max-age=0, must-revalidate", "ETag": etag}
        if request.headers.get("if-none-match") == etag:
            LOGGER.info("OUTPUT_TIMING id=%s event=thumbnail_cache state=not_modified", output_timing.identifier)
            return Response(status_code=304, headers=cache_headers)
        try:
            with measure_output_step(output_timing, "thumbnail_cache_get", relative_path, emit=True):
                thumbnail_bytes = server.thumbnail_cache.get_or_create(
                    file_path, file_stat.st_mtime_ns, file_stat.st_size, output_timing=output_timing,
                )
        except ThumbnailTooLargeError as exception:
            raise HTTPException(413, str(exception)) from exception
        except FileNotFoundError as exception:
            raise HTTPException(404, "결과물을 찾을 수 없습니다.") from exception
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exception:
            LOGGER.warning("결과물 미리보기 생성 실패: path=%s error_type=%s", relative_path, type(exception).__name__)
            raise HTTPException(422, "결과물 미리보기를 만들 수 없습니다.") from exception
        with measure_output_step(output_timing, "preview_response", relative_path, emit=True):
            return Response(content=thumbnail_bytes, media_type="image/webp", headers=cache_headers)

    @app.get("/media/{relative_path:path}")
    def media(relative_path: str):
        """인증된 브라우저에 관리 폴더 안의 생성물을 제공합니다."""

        try:
            file_path = server.managed_path(relative_path)
        except (ValueError, FileNotFoundError) as exception:
            raise HTTPException(404, str(exception)) from exception
        if server.output_catalog.is_deleted(file_path.relative_to(server.config.managed_output_directory).as_posix()):
            raise HTTPException(404, "삭제된 결과물입니다.")
        if not file_path.is_file() or file_path.suffix.lower() not in MEDIA_EXTENSIONS:
            raise HTTPException(404, "지원하지 않는 결과물입니다.")
        return FileResponse(file_path)

    @app.delete("/api/outputs/{output_id}")
    def delete_output(output_id: int):
        """단일 이미지의 현재 파일을 지우고 작업 이력과 삭제된 catalog 행은 보존합니다."""

        def remove_output_image(relative_path: str) -> bool:
            """관리 폴더의 실제 이미지 파일만 삭제하며 이미 없으면 삭제 표시만 남깁니다."""

            try:
                image_path = server.managed_path(relative_path)
            except ValueError as exception:
                raise HTTPException(422, str(exception)) from exception
            if image_path != server.config.managed_output_directory / relative_path:
                raise HTTPException(422, "symlink 경로의 결과물은 삭제할 수 없습니다.")
            if image_path.suffix.lower() not in PREVIEW_IMAGE_EXTENSIONS:
                raise HTTPException(422, "이미지 결과물만 삭제할 수 있습니다.")
            try:
                image_path.unlink()
            except FileNotFoundError:
                return False
            except OSError as exception:
                raise HTTPException(409, "이미지 파일을 삭제할 수 없습니다.") from exception
            return True

        try:
            deletion_result = server.output_catalog.delete_file(output_id, remove_output_image)
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        except ValueError as exception:
            raise HTTPException(409, str(exception)) from exception
        except sqlite3.Error as exception:
            LOGGER.exception("결과물 삭제 DB 오류: output_id=%s", output_id)
            raise HTTPException(409, "결과물 삭제 상태를 DB에 반영하지 못했습니다.") from exception
        image_path = server.config.managed_output_directory / deletion_result["path"]
        IMAGE_DIMENSION_CACHE.invalidate(image_path)
        server.thumbnail_cache.invalidate(image_path)
        LOGGER.info("결과물 삭제: output_id=%s path=%s deleted_files=%s", output_id,
                    deletion_result["path"], deletion_result["deleted_files"])
        return JSONResponse(deletion_result)

    @app.post("/api/outputs/move")
    def move_output(payload: MoveInput):
        """결과물 하나를 관리 폴더 안의 다른 폴더로 이동합니다."""

        return JSONResponse(move_managed_output(server, payload.source, payload.destination_folder))

    @app.post("/api/outputs/move-batch")
    def move_selected_outputs(payload: BulkMoveInput):
        """선택한 결과물들을 이동하고 성공·동일 폴더·실패 항목을 구분하여 반환합니다."""

        return JSONResponse(move_recorded_outputs(server, payload.output_ids, payload.destination_folder))

    return app


async def _monitor_cancellations(server: HomeServer) -> None:
    """취소된 작업의 접수 ID만 묶어 전송하고 실패 시 간격을 두고 재시도합니다."""

    while True:
        try:
            active_requests = await asyncio.to_thread(server.database.list_active_requests)
            active_request_ids = {request["request_id"] for request in active_requests}
            server.cancellation_retry_after = {
                request_id: retry_after for request_id, retry_after in server.cancellation_retry_after.items()
                if request_id in active_request_ids
            }
            cancellation_requests = []
            for request in active_requests:
                if request["status"] != "cancelling" or not request["prompt_id"]:
                    continue
                if time.monotonic() < server.cancellation_retry_after.get(request["request_id"], 0):
                    continue
                cancellation_requests.append(request)
            for first_index in range(0, len(cancellation_requests), 100):
                request_batch = cancellation_requests[first_index:first_index + 100]
                request_ids = [request["request_id"] for request in request_batch]
                cancellation_error = None
                try:
                    await server.comfy.cancel_prompts([request["prompt_id"] for request in request_batch])
                    LOGGER.info("ComfyUI 취소 전송: count=%s", len(request_batch))
                except Exception as exception:
                    cancellation_error = "ComfyUI 취소 전송 실패. 자동 재시도 중입니다."
                    LOGGER.warning("ComfyUI 취소 전송 실패: count=%s error_type=%s", len(request_batch), type(exception).__name__)
                for request_id in request_ids:
                    server.cancellation_retry_after[request_id] = time.monotonic() + 5
                await asyncio.to_thread(server.database.record_cancellation_error, request_ids, cancellation_error)
        except Exception:
            LOGGER.exception("취소 요청 처리 중 오류가 발생했습니다.")
        try:
            await asyncio.wait_for(server.cancellation_wakeup.wait(), timeout=1)
        except TimeoutError:
            pass
        server.cancellation_wakeup.clear()


async def _skip_cancelled_submission(server: HomeServer, request_id: str) -> bool:
    """네트워크 전송 직전 취소를 재확인하고 미접수 요청을 취소 완료로 만듭니다."""

    submission_state = await asyncio.to_thread(server.database.get_submission_state, request_id)
    if submission_state is None or submission_state["status"] != "submitting":
        if submission_state and submission_state["status"] == "cancelling" and not submission_state["prompt_id"]:
            await asyncio.to_thread(server.database.cancel_unsubmitted_request, request_id)
        return True
    return False


async def _submit_requests(server: HomeServer, requests: list[dict[str, Any]]) -> None:
    """ComfyUI에 요청을 순서대로 접수하고 업로드 임시 파일을 제거합니다."""

    workflow_templates: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    try:
        for request in requests:
            request_id = request["request_id"]
            detail = request["detail"]
            submission_started = False
            try:
                if await _skip_cancelled_submission(server, request_id):
                    continue
                if request["workflow"] == "anima":
                    wildcard_seed = secrets.randbelow(2**31)
                    prompt_template, negative_template, selected_path, negative_selected_path = await asyncio.to_thread(
                        resolve_anima_prompts,
                        detail["body"], detail["selected_tags"], wildcard_seed,
                    )
                    prompt_text = await server.comfy.populate_wildcards(prompt_template, wildcard_seed)
                    negative_text = await server.comfy.populate_wildcards(
                        negative_template, wildcard_seed,
                    )
                else:
                    wildcard_seed = None
                    selected_path = []
                    negative_selected_path = []
                    prompt_text = plain_prompt(detail["body"])
                    negative_text = ""
                if request["workflow"] not in workflow_templates:
                    workflow_templates[request["workflow"]] = await asyncio.to_thread(
                        load_workflows, server.config.workflow_directory, request["workflow"],
                    )
                api_workflow, ui_workflow = workflow_templates[request["workflow"]]
                if request["workflow"] == "anima":
                    request_settings = dict(detail["settings"])
                    request_settings["seed"] = secrets.randbelow(2**31)
                    request_workflow, metadata_workflow = await asyncio.to_thread(
                        prepare_anima,
                        api_workflow, ui_workflow, prompt_text, negative_text,
                        request_settings, detail["loras"], request["output_stem"],
                    )
                else:
                    request_settings = detail["settings"]
                    upload_id = detail["upload_id"]
                    upload_path = await asyncio.to_thread(find_uploaded_image, server.upload_directory, upload_id)
                    uploaded_name = f"{request_id}_{upload_path.name}"
                    uploaded_reference = await server.comfy.upload_image(upload_path, uploaded_name)
                    request_workflow, metadata_workflow = await asyncio.to_thread(
                        prepare_minimax,
                        api_workflow, ui_workflow, uploaded_reference, prompt_text,
                        request_settings, detail["loras"], request["output_stem"],
                    )
                metadata = {
                    "workflow": metadata_workflow,
                    "home_server_request": {
                        "request_id": request_id, "job_id": request["job_id"],
                        "prompt": prompt_text, "negative": negative_text,
                        "selected_path": selected_path,
                        "negative_selected_path": negative_selected_path,
                        "wildcard_seed": wildcard_seed, "settings": request_settings,
                        "loras": detail["loras"],
                    },
                }
                if await _skip_cancelled_submission(server, request_id):
                    continue
                submission_started = True
                prompt_id = await server.comfy.submit(request_workflow, metadata)
                await asyncio.to_thread(
                    server.database.set_request_accepted,
                    request_id, prompt_id, {"prompt": prompt_text, "negative": negative_text,
                                            "selected_path": selected_path,
                                            "negative_selected_path": negative_selected_path,
                                            "wildcard_seed": wildcard_seed, "settings": request_settings},
                )
                server.cancellation_wakeup.set()
                LOGGER.info("요청 접수: request_id=%s prompt_id=%s", request_id, prompt_id)
            except Exception as exception:
                submission_state = await asyncio.to_thread(server.database.get_submission_state, request_id)
                if submission_state and submission_state["status"] == "cancelling" and not submission_state["prompt_id"]:
                    if submission_started:
                        await asyncio.to_thread(
                            server.database.update_request, request_id, "stopped",
                            "제출 응답을 받지 못해 ComfyUI 접수 여부를 확인할 수 없습니다.",
                        )
                    else:
                        await asyncio.to_thread(server.database.cancel_unsubmitted_request, request_id)
                else:
                    await asyncio.to_thread(server.database.update_request, request_id, "failed", str(exception))
                LOGGER.error("요청 제출 실패: request_id=%s error_type=%s", request_id, type(exception).__name__)
    finally:
        await asyncio.to_thread(clear_batch_uploads, server.upload_directory, requests)


async def _refresh_requests(server: HomeServer) -> None:
    """중복 감시를 막고 작은 상태 조회와 묶음 DB 갱신으로 진행 상태를 확인합니다."""

    async with server.request_refresh_lock:
        active_requests = await asyncio.to_thread(server.database.list_active_requests)
        accepted_requests = [request for request in active_requests if request["prompt_id"]]
        active_request_ids = {request["request_id"] for request in active_requests}
        server.missing_request_since = {
            request_id: missing_since for request_id, missing_since in server.missing_request_since.items()
            if request_id in active_request_ids
        }
        if not accepted_requests:
            return
        try:
            queue = await server.comfy.queue()
            server.record_comfy_connection(True)
        except Exception as exception:
            server.record_comfy_connection(False, type(exception).__name__)
            server.missing_request_since.clear()
            return
        running_ids = {str(item[1]) for item in queue.get("queue_running", [])}
        pending_ids = {str(item[1]) for item in queue.get("queue_pending", [])}
        updates = []
        history_requests = []
        for request in accepted_requests:
            if request["prompt_id"] in running_ids or request["prompt_id"] in pending_ids:
                server.missing_request_since.pop(request["request_id"], None)
                next_status = "running" if request["prompt_id"] in running_ids else "pending"
                if request["status"] not in {next_status, "cancelling"}:
                    updates.append({"request_id": request["request_id"], "status": next_status})
            else:
                history_requests.append(request)
        history_semaphore = asyncio.Semaphore(4)

        async def read_history_state(request: dict[str, Any]) -> dict[str, Any] | None:
            """이력 읽기 동시 수를 제한하고 실패한 조회를 유실 판정에 사용하지 않습니다."""

            async with history_semaphore:
                try:
                    history = await server.comfy.history(request["prompt_id"])
                except Exception:
                    server.missing_request_since.pop(request["request_id"], None)
                    return None
            record = history.get(request["prompt_id"])
            if not record:
                missing_since = server.missing_request_since.setdefault(request["request_id"], time.monotonic())
                grace_seconds = CANCEL_CONFIRMATION_SECONDS if request["status"] == "cancelling" else MISSING_REQUEST_GRACE_SECONDS
                if time.monotonic() - missing_since < grace_seconds:
                    return None
                next_status = "cancelled" if request["status"] == "cancelling" else "stopped"
                error_message = None if next_status == "cancelled" else "ComfyUI 대기열과 완료 이력에서 요청을 확인할 수 없어 추적을 중단했습니다."
                return {"request_id": request["request_id"], "status": next_status, "error_message": error_message}
            server.missing_request_since.pop(request["request_id"], None)
            status_info = record.get("status", {})
            status_name = str(status_info.get("status_str", ""))
            if status_name == "success":
                output_paths = await asyncio.to_thread(_history_output_paths, server, record, request["workflow"])
                return {"request_id": request["request_id"], "status": "completed", "output_paths": output_paths}
            interruption_recorded = any(
                isinstance(message, (list, tuple)) and message and message[0] == "execution_interrupted"
                for message in status_info.get("messages", [])
            )
            if status_name in {"error", "interrupted"}:
                next_status = "cancelled" if status_name == "interrupted" or interruption_recorded else "failed"
                return {"request_id": request["request_id"], "status": next_status,
                        "error_message": None if next_status == "cancelled" else status_name}
            return None

        history_updates = await asyncio.gather(*(read_history_state(request) for request in history_requests))
        updates.extend(update for update in history_updates if update is not None)
        applied_updates = await asyncio.to_thread(server.database.apply_request_states, updates)
        for update in applied_updates:
            LOGGER.info("요청 상태 갱신: request_id=%s status=%s", update["request_id"], update["status"])


async def _monitor_requests(server: HomeServer) -> None:
    """브라우저 접속 여부와 관계없이 활성 작업의 완료 상태를 확인합니다."""

    while True:
        try:
            await _refresh_requests(server)
        except Exception:
            LOGGER.exception("작업 상태 확인 중 오류가 발생했습니다.")
        await asyncio.sleep(1)


def _history_output_paths(server: HomeServer, record: dict[str, Any], workflow: str) -> list[str]:
    """Saver의 실제 출력 경로를 history에서 읽고 관리 폴더 내부인지 검증합니다."""

    saver_identifier = "13" if workflow == "anima" else "2568"
    saver_outputs = record.get("outputs", {}).get(saver_identifier, {})
    output_paths = []
    managed_folder_name = server.config.managed_output_directory.name
    for output_kind in ("images", "gifs"):
        for output_asset in saver_outputs.get(output_kind, []):
            if output_asset.get("type") != "output":
                continue
            subfolder = str(output_asset.get("subfolder", "")).replace("\\", "/")
            if not subfolder.startswith(f"{managed_folder_name}/"):
                continue
            relative_folder = subfolder[len(managed_folder_name) + 1:]
            filename = str(output_asset.get("filename", ""))
            if not filename or "/" in filename or "\\" in filename:
                continue
            relative_path = f"{relative_folder}/{filename}"
            try:
                output_path = server.managed_path(relative_path)
            except ValueError:
                continue
            if output_path.suffix.lower() in MEDIA_EXTENSIONS and relative_path not in output_paths:
                output_paths.append(relative_path)
    return output_paths
