"""Comfy Home Server의 HTTP API와 작업 실행을 제공합니다."""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
import secrets
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .comfy_client import ComfyClient
from .configuration import AppConfig, PROJECT_DIRECTORY, load_config
from .database import Database
from .prompt_builder import choose_scenario, compile_prompt, compile_selected_prompt
from .workflows import load_workflows, prepare_anima, prepare_minimax


MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mkv", ".mov"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
FINAL_STATUSES = {"completed", "failed", "cancelled", "stopped"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
LOGGER = logging.getLogger(__name__)


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

    body: dict[str, Any]
    selected_scenario_ids: list[str] = Field(default_factory=list)
    count: int = Field(default=5, ge=1, le=20)


class BatchInput(BaseModel):
    """ComfyUI에 제출할 Batch의 공통 옵션입니다."""

    workflow: str
    body: dict[str, Any]
    selected_scenario_ids: list[str] = Field(default_factory=list)
    count: int = Field(default=1, ge=1, le=100)
    settings: dict[str, Any] = Field(default_factory=dict)
    loras: list[dict[str, Any]] = Field(default_factory=list)
    upload_ids: list[str] = Field(default_factory=list)


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
        self.submission_tasks: set[asyncio.Task[Any]] = set()
        self._mark_interrupted_submissions()

    def _mark_interrupted_submissions(self) -> None:
        """이전 실행에서 제출되지 못한 작업을 자동 재실행 없이 표시합니다."""

        for job in self.database.list_jobs(limit=1000):
            if job["status"] == "submitting":
                self.database.update_job(job["request_id"], "stopped", "앱 재시작으로 제출 여부를 확인하지 못했습니다.")

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

        monitor_task = asyncio.create_task(_monitor_jobs(server))
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
        return await call_next(request)

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
            raise HTTPException(429, "잠시 후 다시 시도해 주세요.")
        if not hmac.compare_digest(payload.password, server.config.password):
            recent_failures.append(time.time())
            server.login_failures[remote_address] = recent_failures
            raise HTTPException(401, "비밀번호가 맞지 않습니다.")
        server.login_failures.pop(remote_address, None)
        session_token = secrets.token_urlsafe(32)
        server.sessions[session_token] = time.time() + 7 * 24 * 3600
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
        except Exception:
            connected = False
            queue_count = None
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
        preset_id = payload.preset_id or uuid.uuid4().hex
        return server.database.save_preset(preset_id, payload.name.strip(), payload.workflow, payload.body)

    @app.get("/api/presets/{preset_id}/versions")
    async def preset_versions(preset_id: str):
        """저장된 Prompt의 이전 버전을 보여줍니다."""

        return server.database.list_preset_versions(preset_id)

    @app.post("/api/prompts/preview")
    async def preview(payload: PreviewInput):
        """상황 조합과 Impact wildcard 확장 결과를 미리 보여줍니다."""

        combined_prompt = compile_prompt(payload.body, payload.selected_scenario_ids)
        examples = []
        for example_index in range(payload.count):
            wildcard_seed = secrets.randbelow(2**31)
            scenario = choose_scenario(payload.body, payload.selected_scenario_ids, wildcard_seed)
            template = compile_selected_prompt(payload.body, scenario)
            try:
                resolved = await server.comfy.populate_wildcards(template, wildcard_seed)
            except Exception as exception:
                raise HTTPException(502, str(exception)) from exception
            examples.append({
                "index": example_index + 1, "scenario": scenario.get("name") if scenario else None,
                "seed": wildcard_seed, "prompt": resolved,
            })
        return {"combined_prompt": combined_prompt, "examples": examples}

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
        try:
            compile_prompt(payload.body, payload.selected_scenario_ids)
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

        batch_id = uuid.uuid4().hex[:12]
        date_folder = datetime.now().strftime("%Y-%m-%d")
        submitted_jobs = []
        for upload_id in upload_ids:
            request_id = uuid.uuid4().hex[:12]
            output_stem = f"{server.config.managed_output_directory.name}/{payload.workflow}/{date_folder}/{batch_id}/{request_id}"
            job = {
                "request_id": request_id, "batch_id": batch_id, "workflow": payload.workflow,
                "status": "submitting", "output_stem": output_stem,
                "detail": {"upload_id": upload_id, "body": payload.body, "selected_scenario_ids": payload.selected_scenario_ids,
                           "settings": payload.settings, "loras": payload.loras},
            }
            server.database.add_job(job)
            submitted_jobs.append(job)

        submission_task = asyncio.create_task(_submit_jobs(server, submitted_jobs))
        server.submission_tasks.add(submission_task)
        submission_task.add_done_callback(server.submission_tasks.discard)
        return {"batch_id": batch_id, "request_ids": [job["request_id"] for job in submitted_jobs]}

    @app.get("/api/jobs")
    async def jobs(refresh: bool = False):
        """최근 작업 목록을 반환하고 활성 작업의 ComfyUI 상태를 확인합니다."""

        if refresh:
            await _refresh_jobs(server)
        return server.database.list_jobs()

    @app.post("/api/jobs/{request_id}/cancel")
    async def cancel_job(request_id: str):
        """제출 전 작업이나 ComfyUI 대기열의 요청을 취소합니다."""

        job = server.database.get_job(request_id)
        if job is None:
            raise HTTPException(404, "작업을 찾을 수 없습니다.")
        if job["status"] != "pending":
            raise HTTPException(409, "대기 중인 요청만 취소할 수 있습니다.")
        queue = await server.comfy.queue()
        pending_ids = {str(item[1]) for item in queue.get("queue_pending", [])}
        if job["prompt_id"] not in pending_ids:
            raise HTTPException(409, "ComfyUI 대기열에서 이 요청을 찾지 못했습니다.")
        await server.comfy.cancel_pending(job["prompt_id"])
        server.database.update_job(request_id, "cancelled")
        return {"status": "cancelled"}

    @app.get("/api/outputs")
    async def outputs(limit: int = 500, prefix: str = ""):
        """관리 output 폴더의 현재 파일을 새로 읽습니다."""

        selected_limit = max(1, min(limit, 2000))
        normalized_prefix = prefix.replace("\\", "/")
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
        found_files.sort(key=lambda item: item["modified_at"], reverse=True)
        return {"files": found_files[:selected_limit], "total": len(found_files)}

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
        return {"path": destination_path.relative_to(server.config.managed_output_directory).as_posix()}

    return app


async def _submit_jobs(server: HomeServer, jobs: list[dict[str, Any]]) -> None:
    """ComfyUI에 요청을 순서대로 접수하고 업로드 임시 파일을 제거합니다."""

    try:
        for job in jobs:
            request_id = job["request_id"]
            detail = job["detail"]
            wildcard_seed = secrets.randbelow(2**31)
            scenario = choose_scenario(detail["body"], detail["selected_scenario_ids"], wildcard_seed)
            prompt_template = compile_selected_prompt(detail["body"], scenario)
            try:
                prompt_text = await server.comfy.populate_wildcards(prompt_template, wildcard_seed)
                negative_text = await server.comfy.populate_wildcards(
                    str(detail["body"].get("negative", "")), wildcard_seed,
                )
                api_workflow, ui_workflow = load_workflows(server.config.workflow_directory, job["workflow"])
                if job["workflow"] == "anima":
                    request_settings = dict(detail["settings"])
                    request_settings["seed"] = secrets.randbelow(2**31)
                    request_workflow, metadata_workflow = prepare_anima(
                        api_workflow, ui_workflow, prompt_text, negative_text,
                        request_settings, detail["loras"], job["output_stem"],
                    )
                else:
                    request_settings = detail["settings"]
                    upload_id = detail["upload_id"]
                    upload_path = next(server.upload_directory.glob(f"{upload_id}.*"))
                    uploaded_name = f"{request_id}_{upload_path.name}"
                    uploaded_reference = await server.comfy.upload_image(upload_path, uploaded_name)
                    request_workflow, metadata_workflow = prepare_minimax(
                        api_workflow, ui_workflow, uploaded_reference, prompt_text,
                        request_settings, detail["loras"], job["output_stem"],
                    )
                metadata = {
                    "workflow": metadata_workflow,
                    "home_server_request": {
                        "request_id": request_id, "batch_id": job["batch_id"],
                        "prompt": prompt_text, "negative": negative_text,
                        "scenario": scenario.get("name") if scenario else None,
                        "wildcard_seed": wildcard_seed, "settings": request_settings,
                        "loras": detail["loras"],
                    },
                }
                prompt_id = await server.comfy.submit(request_workflow, metadata)
                server.database.set_job_accepted(
                    request_id, prompt_id, {"prompt": prompt_text, "negative": negative_text,
                                            "scenario": scenario.get("name") if scenario else None,
                                            "wildcard_seed": wildcard_seed, "settings": request_settings},
                )
            except Exception as exception:
                server.database.update_job(request_id, "failed", str(exception))
    finally:
        for job in jobs:
            upload_id = job["detail"].get("upload_id")
            if upload_id:
                for upload_path in server.upload_directory.glob(f"{upload_id}.*"):
                    upload_path.unlink(missing_ok=True)


async def _refresh_jobs(server: HomeServer) -> None:
    """ComfyUI queue와 history를 조회해 앱이 제출한 작업만 갱신합니다."""

    active_jobs = [job for job in server.database.list_jobs(limit=1000) if job["status"] not in FINAL_STATUSES and job["prompt_id"]]
    if not active_jobs:
        return
    try:
        queue = await server.comfy.queue()
    except Exception:
        return
    running_ids = {str(item[1]) for item in queue.get("queue_running", [])}
    pending_ids = {str(item[1]) for item in queue.get("queue_pending", [])}
    for job in active_jobs:
        prompt_id = job["prompt_id"]
        if prompt_id in running_ids:
            server.database.update_job(job["request_id"], "running")
        elif prompt_id in pending_ids:
            server.database.update_job(job["request_id"], "pending")
        else:
            try:
                history = await server.comfy.history(prompt_id)
            except Exception:
                continue
            record = history.get(prompt_id)
            if not record:
                continue
            status = record.get("status", {})
            status_name = str(status.get("status_str", ""))
            if status_name == "success":
                _normalize_single_output(server, job)
                server.database.update_job(job["request_id"], "completed")
            elif status_name in {"error", "interrupted"}:
                server.database.update_job(job["request_id"], "failed", status_name)


async def _monitor_jobs(server: HomeServer) -> None:
    """브라우저 접속 여부와 관계없이 활성 작업의 완료 상태를 확인합니다."""

    while True:
        try:
            await _refresh_jobs(server)
        except Exception:
            LOGGER.exception("작업 상태 확인 중 오류가 발생했습니다.")
        await asyncio.sleep(1)


def _normalize_single_output(server: HomeServer, job: dict[str, Any]) -> None:
    """출력 파일이 하나일 때 custom saver의 접미사를 제거합니다."""

    output_components = job["output_stem"].split("/")
    if not output_components or output_components[0] != server.config.managed_output_directory.name:
        return
    relative_stem = "/".join(output_components[1:])
    try:
        target_stem = server.managed_path(relative_stem)
    except ValueError:
        return
    output_folder = target_stem.parent
    if not output_folder.is_dir():
        return
    matching_files = [
        candidate for candidate in output_folder.glob(f"{target_stem.name}*")
        if candidate.is_file() and candidate.suffix.lower() in MEDIA_EXTENSIONS
    ]
    if len(matching_files) != 1:
        return
    source_file = matching_files[0]
    destination_file = output_folder / f"{target_stem.name}{source_file.suffix}"
    if source_file == destination_file or destination_file.exists():
        return
    try:
        source_file.rename(destination_file)
    except OSError:
        LOGGER.warning("완료 파일의 이름을 정리하지 못했습니다: %s", source_file)


app = create_app()
