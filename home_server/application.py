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
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator, model_validator

from .comfy_client import ComfyClient
from .configuration import AppConfig, PROJECT_DIRECTORY, load_config
from .database import Database
from .logging_setup import configure_application_logging
from .tag_builder import anima_prompt, resolve_tag_prompt, validate_tag_selection
from .workflows import WORKFLOW_OUTPUT_NAMES, load_workflows, prepare_anima, prepare_minimax


MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mkv", ".mov"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
PREVIEW_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
PREVIEW_SIZE = 384
MAX_PREVIEW_PIXELS = 80_000_000
LOGGER = logging.getLogger(__name__)


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


def settings_dimensions(settings: dict[str, Any]) -> tuple[int, int] | None:
    """저장된 요청 설정에서 양수 해상도를 읽습니다."""

    try:
        width = int(settings["width"])
        height = int(settings["height"])
    except (KeyError, TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def selected_tag_definitions(
    database: Database, selected_tag_ids: list[str], prompt_text: str,
) -> list[dict[str, Any]]:
    """현재 DB에서 선택한 태그를 읽고 Prompt 참조 기준으로 검증합니다."""

    if len(selected_tag_ids) != len(set(selected_tag_ids)):
        raise ValueError("같은 태그 항목을 중복 선택할 수 없습니다.")
    available_tags = {tag["tag_id"]: tag for tag in database.list_tag_entries()}
    missing_tag_ids = [tag_id for tag_id in selected_tag_ids if tag_id not in available_tags]
    if missing_tag_ids:
        raise ValueError("삭제되거나 찾을 수 없는 태그 항목이 선택되었습니다. 목록을 새로고침해 주세요.")
    selected_tags = [available_tags[tag_id] for tag_id in selected_tag_ids]
    validate_tag_selection(prompt_text, selected_tags)
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
    upload_ids: list[str] = Field(default_factory=list)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        """작업 설명의 공백을 정리하고 여러 줄 입력을 거부합니다."""

        if "\n" in value or "\r" in value:
            raise ValueError("작업 설명은 한 줄로 입력해 주세요.")
        return value.strip()


class TagGroupInput(BaseModel):
    """태그 표시 그룹의 이름과 기본 펼침 상태를 검증합니다."""

    name: str = Field(min_length=1, max_length=120)
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
    tag_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=64)
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
        config.runtime_directory.mkdir(parents=True, exist_ok=True)
        config.managed_output_directory.mkdir(parents=True, exist_ok=True)
        self.upload_directory = config.runtime_directory / "uploads"
        self.upload_directory.mkdir(parents=True, exist_ok=True)
        for stale_upload in self.upload_directory.iterdir():
            if stale_upload.is_file() and time.time() - stale_upload.stat().st_mtime > 24 * 3600:
                stale_upload.unlink()
        self.database = Database(config.runtime_directory / "home_server.sqlite3")
        self.comfy = ComfyClient(config.comfy_endpoint)
        self.sessions: dict[str, float] = {}
        self.login_failures: dict[str, list[float]] = {}
        self.comfy_queue_available: bool | None = None
        self.submission_tasks: set[asyncio.Task[Any]] = set()
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


def create_app(config: AppConfig | None = None) -> FastAPI:
    """앱 서버와 API route를 구성합니다."""

    server = HomeServer(config or load_config())

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        """서버 종료 시 HTTP 연결과 제출 task를 정리합니다."""

        log_path = configure_application_logging(server.config.runtime_directory)
        LOGGER.info("서버 시작: 로그 파일=%s", log_path)
        monitor_task = asyncio.create_task(_monitor_requests(server))
        try:
            yield
        finally:
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)
            for submission_task in server.submission_tasks:
                submission_task.cancel()
            if server.submission_tasks:
                await asyncio.gather(*server.submission_tasks, return_exceptions=True)
            await server.comfy.close()
            LOGGER.info("서버 종료")

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
        try:
            response = await call_next(request)
        except Exception:
            LOGGER.exception("HTTP 요청 처리 실패: %s %s", request.method, request.url.path)
            raise
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
    async def presets():
        """저장된 Prompt preset을 조회합니다."""

        return server.database.list_presets()

    @app.post("/api/presets")
    async def save_preset(payload: PresetInput):
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
        return server.database.save_preset(preset_id, payload.name.strip(), payload.workflow, body)

    @app.get("/api/presets/{preset_id}/versions")
    async def preset_versions(preset_id: str):
        """저장된 Prompt의 이전 버전을 보여줍니다."""

        return server.database.list_preset_versions(preset_id)

    @app.get("/api/tags")
    async def list_tags():
        """Anima 태그 항목과 표시 그룹을 함께 반환합니다."""

        return {"groups": server.database.list_tag_groups(), "entries": server.database.list_tag_entries()}

    @app.post("/api/tags/groups", status_code=201)
    async def create_tag_group(payload: TagGroupInput):
        """기본 펼침 상태를 포함한 태그 표시 그룹을 만듭니다."""

        return server.database.save_tag_group(uuid.uuid4().hex, payload.name, payload.default_expanded)

    @app.put("/api/tags/groups/{group_id}")
    async def update_tag_group(group_id: str, payload: TagGroupInput):
        """존재하는 그룹의 이름과 기본 펼침 상태를 수정합니다."""

        if server.database.get_tag_group(group_id) is None:
            raise HTTPException(404, "태그 그룹을 찾을 수 없습니다.")
        return server.database.save_tag_group(group_id, payload.name, payload.default_expanded)

    @app.delete("/api/tags/groups/{group_id}")
    async def delete_tag_group(group_id: str):
        """항목이 없는 표시 그룹만 삭제합니다."""

        try:
            deleted = server.database.delete_tag_group(group_id)
        except sqlite3.IntegrityError as exception:
            raise HTTPException(409, "그룹의 태그 항목을 먼저 이동하거나 삭제해 주세요.") from exception
        if not deleted:
            raise HTTPException(404, "태그 그룹을 찾을 수 없습니다.")
        return {"deleted": True}

    @app.post("/api/tags/entries", status_code=201)
    async def create_tag_entry(payload: TagEntryInput):
        """그룹 안에 새 태그 선택지를 저장합니다."""

        if server.database.get_tag_group(payload.group_id) is None:
            raise HTTPException(422, "태그 그룹을 찾을 수 없습니다.")
        return server.database.save_tag_entry(uuid.uuid4().hex, payload.model_dump())

    @app.put("/api/tags/entries/{tag_id}")
    async def update_tag_entry(tag_id: str, payload: TagEntryInput):
        """안정적인 ID를 유지하며 기존 태그 항목을 수정합니다."""

        if server.database.get_tag_entry(tag_id) is None:
            raise HTTPException(404, "태그 항목을 찾을 수 없습니다.")
        if server.database.get_tag_group(payload.group_id) is None:
            raise HTTPException(422, "태그 그룹을 찾을 수 없습니다.")
        return server.database.save_tag_entry(tag_id, payload.model_dump())

    @app.delete("/api/tags/entries/{tag_id}")
    async def delete_tag_entry(tag_id: str):
        """현재 태그 정의를 삭제하고 과거 작업 snapshot은 보존합니다."""

        if not server.database.delete_tag_entry(tag_id):
            raise HTTPException(404, "태그 항목을 찾을 수 없습니다.")
        return {"deleted": True}

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
            return {"combined_prompt": prompt_text, "examples": [{"index": 1, "seed": None, "prompt": prompt_text}]}
        if payload.workflow != "anima":
            raise HTTPException(422, "지원하지 않는 workflow입니다.")
        try:
            prompt_text = anima_prompt(payload.body)
            selected_tags = selected_tag_definitions(
                server.database, payload.selected_tag_ids, prompt_text,
            )
            examples = []
            for example_index in range(payload.count):
                wildcard_seed = secrets.randbelow(2**31)
                template, selected_path = resolve_tag_prompt(payload.body, selected_tags, wildcard_seed)
                resolved = await server.comfy.populate_wildcards(template, wildcard_seed)
                examples.append({
                    "index": example_index + 1, "seed": wildcard_seed,
                    "prompt": resolved, "selected_path": selected_path,
                })
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception
        except Exception as exception:
            raise HTTPException(502, str(exception)) from exception
        return {"combined_prompt": None, "examples": examples}

    @app.get("/api/loras")
    async def loras():
        """ComfyUI에서 현재 확인되는 LoRA 파일 목록을 제공합니다."""

        try:
            return {"files": await server.comfy.list_loras(), "profiles": server.database.list_lora_profiles()}
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
        server.database.save_lora_profile(payload.name, payload.workflow, settings)
        return {"saved": True}

    @app.get("/api/loras/presets")
    async def list_lora_presets():
        """ComfyUI 연결 여부와 관계없이 저장된 LoRA 조합을 조회합니다."""

        return server.database.list_lora_presets()

    @app.post("/api/loras/presets", status_code=201)
    async def create_lora_preset(payload: LoraPresetInput):
        """현재 조합을 새 preset으로 저장합니다."""

        return server.database.create_lora_preset(
            uuid.uuid4().hex, payload.name, payload.workflow, payload.selected_loras_snapshot(),
        )

    @app.put("/api/loras/presets/{preset_id}")
    async def update_lora_preset(preset_id: str, payload: LoraPresetInput):
        """사용자가 저장한 기존 LoRA 조합을 명시적으로 갱신합니다."""

        updated_preset = server.database.update_lora_preset(
            preset_id, payload.name, payload.workflow, payload.selected_loras_snapshot(),
        )
        if updated_preset is None:
            raise HTTPException(404, "LoRA preset을 찾을 수 없습니다.")
        return updated_preset

    @app.delete("/api/loras/presets/{preset_id}")
    async def delete_lora_preset(preset_id: str):
        """선택한 LoRA 조합 preset을 삭제합니다."""

        if not server.database.delete_lora_preset(preset_id):
            raise HTTPException(404, "LoRA preset을 찾을 수 없습니다.")
        return {"deleted": True}

    @app.post("/api/uploads")
    async def upload(file: UploadFile = File(...)):
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
                while chunk := await file.read(1024 * 1024):
                    total_bytes += len(chunk)
                    if total_bytes > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "입력 이미지가 50 MB를 초과합니다.")
                    output_file.write(chunk)
        except Exception:
            upload_path.unlink(missing_ok=True)
            raise
        return {"upload_id": upload_id, "name": original_name, "size": total_bytes}

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
                selected_tags = selected_tag_definitions(
                    server.database, payload.selected_tag_ids, prompt_text,
                )
            available_loras = set(await server.comfy.list_loras()) if payload.loras else set()
            missing_loras = [selected_lora.get("name") for selected_lora in payload.loras if selected_lora.get("name") not in available_loras]
            if missing_loras:
                raise ValueError(f"ComfyUI에서 LoRA를 찾을 수 없습니다: {', '.join(str(name) for name in missing_loras)}")
            load_workflows(server.config.workflow_directory, payload.workflow)
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception
        except Exception as exception:
            raise HTTPException(502, str(exception)) from exception

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
                           "settings": request_settings, "loras": payload.loras},
            }
            submitted_requests.append(request)

        server.database.add_job(job_id, payload.workflow, payload.description, submitted_requests)
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
    ):
        """작업 이력을 페이지 단위로 반환하고 필요하면 요청 상태를 갱신합니다."""

        if refresh:
            await _refresh_requests(server)
        return server.database.list_jobs(page=page, page_size=page_size, job_id=job_id)

    @app.post("/api/requests/{request_id}/cancel")
    async def cancel_request(request_id: str):
        """ComfyUI에서 대기·실행 중인 하위 요청 하나를 취소합니다."""

        request = server.database.get_request(request_id)
        if request is None:
            raise HTTPException(404, "요청을 찾을 수 없습니다.")
        if request["status"] not in {"pending", "running"}:
            raise HTTPException(409, "대기·실행 중인 요청만 취소할 수 있습니다.")
        if not await _cancel_comfy_request(server, request):
            await _refresh_requests(server)
            raise HTTPException(409, "ComfyUI에서 취소 가능한 요청을 찾지 못했습니다.")
        return {"status": "cancelling"}

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        """상위 작업에 속한 대기·실행 요청을 각각 취소합니다."""

        job = server.database.get_job(job_id)
        if job is None:
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        active_requests = [
            request for request in job["requests"] if request["status"] in {"pending", "running"}
        ]
        if not active_requests:
            raise HTTPException(409, "취소할 수 있는 요청이 없습니다.")
        cancelled_count = 0
        failed_count = 0
        for request in active_requests:
            try:
                if await _cancel_comfy_request(server, request):
                    cancelled_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1
                LOGGER.exception("작업 내 요청 취소 실패: request_id=%s", request["request_id"])
        if not cancelled_count and failed_count:
            await _refresh_requests(server)
            raise HTTPException(409, "ComfyUI에서 취소 가능한 요청을 찾지 못했습니다.")
        return {"cancelled_count": cancelled_count, "failed_count": failed_count}

    @app.delete("/api/jobs/{job_id}")
    async def delete_job(job_id: str, delete_outputs: bool = False):
        """완료된 작업 이력과 선택한 경우 원래 위치의 결과물을 삭제합니다."""

        job = server.database.get_job(job_id)
        if job is None:
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        if any(request["status"] in {"submitting", "pending", "running", "cancelling"} for request in job["requests"]):
            raise HTTPException(409, "진행 중인 작업은 삭제할 수 없습니다.")
        deleted_files = 0
        missing_files = 0
        if delete_outputs:
            output_paths = {
                path
                for request in job["requests"]
                for path in request["detail"].get("resolved", {}).get("output_paths", [])
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
                    LOGGER.info("원래 위치에 결과물 없음: job_id=%s path=%s", job_id, relative_path)
                    continue
                try:
                    output_path.unlink()
                except OSError as exception:
                    raise HTTPException(409, f"결과물을 삭제할 수 없습니다: {relative_path}") from exception
                deleted_files += 1
        try:
            deleted = server.database.delete_job(job_id)
        except ValueError as exception:
            raise HTTPException(409, str(exception)) from exception
        if not deleted:
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        LOGGER.info("작업 이력 삭제: job_id=%s delete_outputs=%s deleted_files=%s missing_files=%s", job_id, delete_outputs, deleted_files, missing_files)
        return {"deleted": True, "deleted_files": deleted_files, "missing_files": missing_files}

    @app.get("/api/outputs")
    async def outputs(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=24, ge=1, le=100),
        prefix: str = "",
        job_id: str = "",
        request_id: str = "",
    ):
        """관리 output의 현재 파일을 정렬해 페이지 단위로 반환합니다."""

        normalized_prefix = prefix.replace("\\", "/")
        selected_output_paths = None
        if job_id and request_id:
            raise HTTPException(422, "작업과 요청 필터를 동시에 사용할 수 없습니다.")
        if job_id:
            job = server.database.get_job(job_id)
            if job is None:
                raise HTTPException(404, "작업을 찾을 수 없습니다.")
            selected_output_paths = set()
            for request in job["requests"]:
                selected_output_paths.update(request["detail"].get("resolved", {}).get("output_paths", []))
        elif request_id:
            request = server.database.get_request(request_id)
            if request is None:
                raise HTTPException(404, "요청을 찾을 수 없습니다.")
            selected_output_paths = set(request["detail"].get("resolved", {}).get("output_paths", []))
        if normalized_prefix:
            try:
                server.managed_path(normalized_prefix)
            except ValueError as exception:
                raise HTTPException(422, str(exception)) from exception
        found_files = []
        for output_path in server.config.managed_output_directory.rglob("*"):
            try:
                if not output_path.is_file() or output_path.suffix.lower() not in MEDIA_EXTENSIONS:
                    continue
                if server.config.managed_output_directory not in output_path.resolve().parents:
                    continue
                relative_path = output_path.relative_to(server.config.managed_output_directory).as_posix()
                if normalized_prefix and not relative_path.startswith(normalized_prefix):
                    continue
                if selected_output_paths is not None and relative_path not in selected_output_paths:
                    continue
                file_stat = output_path.stat()
            except OSError:
                # Explorer에서 스캔 도중 파일이 이동되거나 삭제될 수 있습니다.
                continue
            found_files.append({
                "path": relative_path,
                "name": output_path.name, "size": file_stat.st_size,
                "modified_at": file_stat.st_mtime,
                "kind": "video" if output_path.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"} else "image",
            })
        found_files.sort(key=lambda item: (item["modified_at"], item["path"]), reverse=True)
        total = len(found_files)
        first_index = (page - 1) * page_size
        page_files = found_files[first_index:first_index + page_size]
        requests_by_output_path = server.database.find_output_requests([file["path"] for file in page_files])
        for file in page_files:
            output_request = requests_by_output_path.get(file["path"], {})
            file["job_id"] = output_request.get("job_id")
            file_path = server.config.managed_output_directory / file["path"]
            dimensions = image_dimensions(file_path) if file["kind"] == "image" else None
            file["dimensions_source"] = "file" if dimensions else None
            if dimensions is None:
                dimensions = settings_dimensions(output_request.get("settings", {}))
                if dimensions:
                    file["dimensions_source"] = "settings"
            file["width"] = dimensions[0] if dimensions else None
            file["height"] = dimensions[1] if dimensions else None
        return {
            "files": page_files,
            "page": page, "page_size": page_size, "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }

    @app.get("/api/outputs/preview/{relative_path:path}")
    def output_preview(relative_path: str, request: Request):
        """원본을 변경하거나 저장하지 않고 작은 WebP preview를 제공합니다."""

        try:
            file_path = server.managed_path(relative_path, must_exist=True)
        except (ValueError, FileNotFoundError) as exception:
            raise HTTPException(404, str(exception)) from exception
        if not file_path.is_file() or file_path.suffix.lower() not in PREVIEW_IMAGE_EXTENSIONS:
            raise HTTPException(404, "미리보기를 지원하지 않는 결과물입니다.")
        try:
            file_stat = file_path.stat()
        except OSError as exception:
            raise HTTPException(404, "결과물을 찾을 수 없습니다.") from exception
        etag = f'W/"{file_stat.st_mtime_ns:x}-{file_stat.st_size:x}-{PREVIEW_SIZE:x}"'
        cache_headers = {"Cache-Control": "private, max-age=0, must-revalidate", "ETag": etag}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=cache_headers)
        try:
            with Image.open(file_path) as source_image:
                if source_image.width * source_image.height > MAX_PREVIEW_PIXELS:
                    raise HTTPException(413, "미리보기 크기 제한을 초과했습니다.")
                oriented_image = ImageOps.exif_transpose(source_image)
                image_mode = "RGBA" if "A" in oriented_image.getbands() or "transparency" in oriented_image.info else "RGB"
                preview_image = oriented_image.convert(image_mode)
                preview_image.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.Resampling.LANCZOS)
                output_buffer = BytesIO()
                preview_image.save(output_buffer, format="WEBP", quality=75)
        except FileNotFoundError as exception:
            raise HTTPException(404, "결과물을 찾을 수 없습니다.") from exception
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exception:
            LOGGER.warning("결과물 미리보기 생성 실패: path=%s error_type=%s", relative_path, type(exception).__name__)
            raise HTTPException(422, "결과물 미리보기를 만들 수 없습니다.") from exception
        return Response(content=output_buffer.getvalue(), media_type="image/webp", headers=cache_headers)

    @app.get("/media/{relative_path:path}")
    async def media(relative_path: str):
        """인증된 브라우저에 관리 폴더 안의 생성물을 제공합니다."""

        try:
            file_path = server.managed_path(relative_path, must_exist=True)
        except (ValueError, FileNotFoundError) as exception:
            raise HTTPException(404, str(exception)) from exception
        if not file_path.is_file() or file_path.suffix.lower() not in MEDIA_EXTENSIONS:
            raise HTTPException(404, "지원하지 않는 결과물입니다.")
        return FileResponse(file_path)

    @app.post("/api/outputs/move")
    async def move_output(payload: MoveInput):
        """결과물을 관리 폴더 안의 다른 폴더로 이동합니다."""

        try:
            source_path = server.managed_path(payload.source, must_exist=True)
            destination_directory = server.managed_path(payload.destination_folder)
        except (ValueError, FileNotFoundError) as exception:
            raise HTTPException(422, str(exception)) from exception
        if not source_path.is_file() or source_path.suffix.lower() not in MEDIA_EXTENSIONS:
            raise HTTPException(422, "이동할 결과물 파일이 아닙니다.")
        destination_path = destination_directory / source_path.name
        if destination_path.exists():
            raise HTTPException(409, "목적지에 같은 이름의 파일이 있습니다.")
        try:
            destination_directory.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(destination_path))
        except OSError as exception:
            raise HTTPException(409, f"파일을 이동할 수 없습니다: {exception}") from exception
        LOGGER.info("결과물 이동: source=%s destination=%s", payload.source, destination_path)
        return {"path": destination_path.relative_to(server.config.managed_output_directory).as_posix()}

    return app


async def _cancel_comfy_request(server: HomeServer, request: dict[str, Any]) -> bool:
    """지정한 ComfyUI 요청만 취소하고 확인될 때까지 추적합니다."""

    cancelled = await server.comfy.cancel_prompt(request["prompt_id"])
    if not cancelled:
        return False
    server.database.mark_request_cancelling(request["request_id"])
    LOGGER.info("요청 취소 접수: request_id=%s prompt_id=%s", request["request_id"], request["prompt_id"])
    return True


async def _submit_requests(server: HomeServer, requests: list[dict[str, Any]]) -> None:
    """ComfyUI에 요청을 순서대로 접수하고 업로드 임시 파일을 제거합니다."""

    try:
        for request in requests:
            request_id = request["request_id"]
            detail = request["detail"]
            try:
                if request["workflow"] == "anima":
                    wildcard_seed = secrets.randbelow(2**31)
                    prompt_template, selected_path = resolve_tag_prompt(
                        detail["body"], detail["selected_tags"], wildcard_seed,
                    )
                    prompt_text = await server.comfy.populate_wildcards(prompt_template, wildcard_seed)
                    negative_text = await server.comfy.populate_wildcards(
                        str(detail["body"].get("negative", "")), wildcard_seed,
                    )
                else:
                    wildcard_seed = None
                    selected_path = []
                    prompt_text = plain_prompt(detail["body"])
                    negative_text = ""
                api_workflow, ui_workflow = load_workflows(server.config.workflow_directory, request["workflow"])
                if request["workflow"] == "anima":
                    request_settings = dict(detail["settings"])
                    request_settings["seed"] = secrets.randbelow(2**31)
                    request_workflow, metadata_workflow = prepare_anima(
                        api_workflow, ui_workflow, prompt_text, negative_text,
                        request_settings, detail["loras"], request["output_stem"],
                    )
                else:
                    request_settings = detail["settings"]
                    upload_id = detail["upload_id"]
                    upload_path = next(server.upload_directory.glob(f"{upload_id}.*"))
                    uploaded_name = f"{request_id}_{upload_path.name}"
                    uploaded_reference = await server.comfy.upload_image(upload_path, uploaded_name)
                    request_workflow, metadata_workflow = prepare_minimax(
                        api_workflow, ui_workflow, uploaded_reference, prompt_text,
                        request_settings, detail["loras"], request["output_stem"],
                    )
                metadata = {
                    "workflow": metadata_workflow,
                    "home_server_request": {
                        "request_id": request_id, "job_id": request["job_id"],
                        "prompt": prompt_text, "negative": negative_text,
                        "selected_path": selected_path,
                        "wildcard_seed": wildcard_seed, "settings": request_settings,
                        "loras": detail["loras"],
                    },
                }
                prompt_id = await server.comfy.submit(request_workflow, metadata)
                server.database.set_request_accepted(
                    request_id, prompt_id, {"prompt": prompt_text, "negative": negative_text,
                                            "selected_path": selected_path,
                                            "wildcard_seed": wildcard_seed, "settings": request_settings},
                )
                LOGGER.info("요청 접수: request_id=%s prompt_id=%s", request_id, prompt_id)
            except Exception as exception:
                server.database.update_request(request_id, "failed", str(exception))
                LOGGER.error("요청 제출 실패: request_id=%s error_type=%s", request_id, type(exception).__name__)
    finally:
        for request in requests:
            upload_id = request["detail"].get("upload_id")
            if upload_id:
                for upload_path in server.upload_directory.glob(f"{upload_id}.*"):
                    upload_path.unlink(missing_ok=True)


async def _refresh_requests(server: HomeServer) -> None:
    """ComfyUI queue와 history를 조회해 하위 요청 상태를 갱신합니다."""

    active_requests = [request for request in server.database.list_active_requests() if request["prompt_id"]]
    if not active_requests:
        return
    try:
        queue = await server.comfy.queue()
        server.record_comfy_connection(True)
    except Exception as exception:
        server.record_comfy_connection(False, type(exception).__name__)
        return
    running_ids = {str(item[1]) for item in queue.get("queue_running", [])}
    pending_ids = {str(item[1]) for item in queue.get("queue_pending", [])}
    for request in active_requests:
        prompt_id = request["prompt_id"]
        if prompt_id in running_ids:
            if request["status"] not in {"running", "cancelling"}:
                server.database.update_queue_state(request["request_id"], "running")
                LOGGER.info("요청 실행: request_id=%s prompt_id=%s", request["request_id"], prompt_id)
        elif prompt_id in pending_ids:
            if request["status"] not in {"pending", "cancelling"}:
                server.database.update_queue_state(request["request_id"], "pending")
                LOGGER.info("요청 대기: request_id=%s prompt_id=%s", request["request_id"], prompt_id)
        else:
            try:
                history = await server.comfy.history(prompt_id)
            except Exception:
                continue
            record = history.get(prompt_id)
            if not record:
                if request["status"] == "cancelling":
                    cancellation_age = datetime.now(timezone.utc) - datetime.fromisoformat(request["updated_at"])
                    if cancellation_age.total_seconds() >= 15:
                        server.database.update_request(request["request_id"], "cancelled")
                        LOGGER.info("이력 없는 취소 요청 확정: request_id=%s prompt_id=%s", request["request_id"], prompt_id)
                continue
            status = record.get("status", {})
            status_name = str(status.get("status_str", ""))
            if status_name == "success":
                output_paths = _history_output_paths(server, record, request["workflow"])
                server.database.complete_request(request["request_id"], output_paths)
                LOGGER.info("요청 완료: request_id=%s prompt_id=%s", request["request_id"], prompt_id)
            elif status_name in {"error", "interrupted"}:
                request_status = "cancelled" if status_name == "interrupted" and request["status"] == "cancelling" else "failed"
                server.database.update_request(request["request_id"], request_status, None if request_status == "cancelled" else status_name)
                LOGGER.info("요청 종료: request_id=%s prompt_id=%s status=%s", request["request_id"], prompt_id, request_status)


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


app = create_app()
