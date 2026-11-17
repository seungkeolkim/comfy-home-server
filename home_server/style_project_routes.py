"""Home 인증을 공유하는 스타일 프로젝트 저장 API를 제공합니다."""

import asyncio
import logging
import sqlite3

import httpx
from fastapi import APIRouter, HTTPException

from .style_projects import GlobalStyleSettings, ProjectWriteInput, StyleRevisionConflict
from .workflows import load_workflows
from .style_generation import StyleCandidateFavoriteInput, StyleGenerationPlanInput, StyleGenerationSubmitInput, StylePromptRegenerationInput
from .style_random_generation import RandomStyleGenerationPlanInput
from .style_project_rename import StyleProjectRenameService
from .style_lora_presets import StyleLoraPresetRegistrationInput
from .style_project_forks import ProjectForkInput, StyleProjectForkStore


LOGGER = logging.getLogger(__name__)


def create_style_project_router(server) -> APIRouter:
    """프로젝트 조회·설정과 명시적으로 확인한 생성 계획의 제출 API를 등록합니다."""

    router = APIRouter()

    @router.get("/api/style-workspace")
    async def style_workspace():
        """등록 이미지 Workflow와 설치 LoRA 목록을 프로젝트 설정과 함께 제공합니다."""

        api_workflow, _ = await asyncio.to_thread(load_workflows, server.config.workflow_directory, "anima")
        catalog_notice = ""
        try:
            lora_files = await server.comfy.list_loras()
        except Exception as exception:
            LOGGER.warning("스타일 설정 LoRA 목록 조회 실패: %s", type(exception).__name__)
            lora_files = []
            catalog_notice = "ComfyUI에서 LoRA 목록을 확인하지 못했습니다. 저장된 프로젝트 설정은 유지됩니다."
        return {
            "projects": await asyncio.to_thread(server.database.style_projects.list_projects),
            "globalSettings": await asyncio.to_thread(server.database.style_projects.global_settings),
            "workflows": [{
                "identifier": "anima", "name": "Anima", "outputKind": "image",
                "modelIdentifier": api_workflow["1"]["inputs"]["unet_name"],
                "supportedSettings": ["width", "height", "steps", "cfg"],
            }],
            "components": [{"identifier": f"lora:{file_name}", "name": file_name, "kind": "LoRA"} for file_name in lora_files],
            "catalogNotice": catalog_notice,
        }

    @router.get("/api/style-projects")
    def list_style_projects():
        """모든 기기에서 공유하는 실제 프로젝트 목록을 반환합니다."""

        return {"projects": server.database.style_projects.list_projects()}

    @router.get("/api/style-projects/{project_identifier}")
    def read_style_project(project_identifier: str):
        """하나의 프로젝트를 다시 열고 삭제된 소유 ID는 거부합니다."""

        for project in server.database.style_projects.list_projects():
            if project["identifier"] == project_identifier:
                return project
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")

    @router.get("/api/style-projects/{project_identifier}/fork-options")
    def read_project_fork_options(project_identifier: str):
        """0세대를 포함해 실제 저장된 세대별 설정의 Fork 선택지를 조회합니다."""

        try:
            return StyleProjectForkStore(server.database.style_projects, server.config.workflow_directory).options(project_identifier)
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception

    @router.post("/api/style-projects/{project_identifier}/forks", status_code=201)
    def fork_style_project(project_identifier: str, payload: ProjectForkInput):
        """이미지·조합·Elo·CHS 작업 없이 독립적인 새 프로젝트를 만듭니다."""

        try:
            return StyleProjectForkStore(server.database.style_projects, server.config.workflow_directory).create_fork(project_identifier, payload)
        except StyleRevisionConflict as exception:
            raise HTTPException(409, str(exception)) from exception
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception
        except sqlite3.Error as exception:
            LOGGER.warning("프로젝트 Fork 저장 실패: %s", type(exception).__name__)
            raise HTTPException(409, "프로젝트 Fork를 저장하지 못했습니다. 다시 시도해 주세요.") from exception

    @router.post("/api/style-projects", status_code=201)
    def create_style_project(payload: ProjectWriteInput):
        """후보·Vote·GPU 작업 없이 Fresh 프로젝트를 생성합니다."""

        return save_style_project(payload)

    @router.put("/api/style-projects/{project_identifier}")
    def update_style_project(project_identifier: str, payload: ProjectWriteInput):
        """Revision을 검사한 뒤 설정과 평가 Snapshot을 저장합니다."""

        return save_style_project(payload, project_identifier)

    def save_style_project(payload: ProjectWriteInput, project_identifier: str | None = None):
        """저장 오류를 기존 초안을 보존할 수 있는 HTTP 응답으로 변환합니다."""

        try:
            if project_identifier:
                return StyleProjectRenameService(server.style_generation).save_project(project_identifier, payload)
            return server.database.style_projects.save_project(payload, server.config.workflow_directory, project_identifier)
        except StyleRevisionConflict as exception:
            raise HTTPException(409, str(exception)) from exception
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception
        except OSError as exception:
            raise HTTPException(409, "출력 폴더 이름을 변경하지 못했습니다. 파일 사용 상태를 확인하고 같은 요청을 다시 시도해 주세요.") from exception
        except sqlite3.Error as exception:
            LOGGER.warning("스타일 프로젝트 설정 저장 실패: %s", type(exception).__name__)
            raise HTTPException(409, "프로젝트 설정을 저장하지 못했습니다. 다시 시도해 주세요.") from exception

    @router.put("/api/style-projects/{project_identifier}/candidates/{candidate_identifier}/favorite")
    def set_candidate_favorite(project_identifier: str, candidate_identifier: str, payload: StyleCandidateFavoriteInput):
        """그림체 좋아요를 명시적인 값으로 저장하며 다른 프로젝트의 조합은 거부합니다."""

        try:
            with server.style_generation.mutation_lock:
                return server.style_generation.store.set_candidate_favorite(project_identifier, candidate_identifier, payload.isFavorite)
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception

    @router.put("/api/style-projects/{project_identifier}/candidates/{candidate_identifier}/lora-preset")
    def set_candidate_lora_preset(project_identifier: str, candidate_identifier: str, payload: StyleLoraPresetRegistrationInput):
        """생성된 그림체의 LoRA를 CHS 조합으로 등록·해제하며 원본 그림체는 유지합니다."""

        try:
            with server.style_generation.mutation_lock:
                return server.database.style_lora_presets.set_registration(project_identifier, candidate_identifier, payload.isRegistered)
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception

    @router.get("/api/style-projects/{project_identifier}/generation-options")
    def style_generation_options(project_identifier: str):
        """프로젝트에서 허용한 성분·STR로만 A/B 조합을 준비합니다."""

        try:
            return server.style_generation.options(project_identifier)
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception

    @router.post("/api/style-projects/{project_identifier}/random-generation-plans", status_code=201)
    async def create_random_style_generation_plan(project_identifier: str, payload: RandomStyleGenerationPlanInput):
        """허용 범위에서 초기 조합을 추첨하되 Preview에서는 GPU 작업을 만들지 않습니다."""

        return await create_style_generation_plan(project_identifier, payload)

    @router.post("/api/style-projects/{project_identifier}/generation-plans", status_code=201)
    async def create_style_generation_plan(project_identifier: str, payload: StyleGenerationPlanInput):
        """GPU 제출 없이 실제 공통 조건과 장수를 고정합니다."""

        try:
            return await server.style_generation.create_plan(project_identifier, payload)
        except StyleRevisionConflict as exception:
            raise HTTPException(409, str(exception)) from exception
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception
        except RuntimeError as exception:
            raise HTTPException(502, str(exception)) from exception
        except httpx.HTTPError as exception:
            raise HTTPException(502, "ComfyUI 사전 확인에 연결하지 못했습니다. 생성 작업은 접수하지 않았습니다.") from exception

    @router.post("/api/style-projects/{project_identifier}/prompt-regeneration-plans", status_code=201)
    async def create_prompt_regeneration_plan(project_identifier: str, payload: StylePromptRegenerationInput):
        """저장과 GPU 제출을 분리하고 같은 조합의 새 Prompt 장수만 준비합니다."""

        try:
            return await server.style_generation.create_prompt_regeneration_plan(project_identifier, payload)
        except StyleRevisionConflict as exception:
            raise HTTPException(409, str(exception)) from exception
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception
        except (RuntimeError, httpx.HTTPError) as exception:
            raise HTTPException(502, "ComfyUI를 확인하지 못했습니다. 생성 작업은 접수하지 않았습니다.") from exception

    @router.post("/api/style-projects/{project_identifier}/generation-plans/{plan_identifier}/submit")
    async def submit_style_generation_plan(project_identifier: str, plan_identifier: str, payload: StyleGenerationSubmitInput):
        """확인한 RenderPlan을 Home 제출·감시 경로에 연결합니다."""

        from .application import _submit_requests

        try:
            await server.style_generation.preflight_plan(project_identifier, plan_identifier, payload.retryFailedOnly)
            job_identifier, requests = await asyncio.to_thread(server.style_generation.submit_plan, project_identifier, plan_identifier, payload)
        except StyleRevisionConflict as exception:
            raise HTTPException(409, str(exception)) from exception
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        except (ValueError, OSError) as exception:
            raise HTTPException(422, str(exception)) from exception
        except RuntimeError as exception:
            raise HTTPException(502, str(exception)) from exception
        except httpx.HTTPError as exception:
            raise HTTPException(502, "ComfyUI 사전 확인에 연결하지 못했습니다. 생성 작업은 접수하지 않았습니다.") from exception
        if requests:
            submission_task = asyncio.create_task(_submit_requests(server, requests))
            server.submission_tasks.add(submission_task)
            submission_task.add_done_callback(server.submission_tasks.discard)
        return {"jobIdentifier": job_identifier, "requestIdentifiers": [request["request_id"] for request in requests]}

    @router.get("/api/style-projects/{project_identifier}/generation-results")
    def style_generation_results(project_identifier: str, summary: bool = False):
        """Browser 종료 뒤에도 추적된 실제 이미지와 실패 상태를 조회합니다."""

        try:
            return server.style_generation.store.results(project_identifier, summary=summary)
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception

    @router.put("/api/style-settings")
    def update_style_global_settings(payload: GlobalStyleSettings):
        """작가 등록·기본 STR을 저장하되 기존 프로젝트에는 소급 적용하지 않습니다."""

        try:
            return server.database.style_projects.save_global_settings(payload)
        except StyleRevisionConflict as exception:
            raise HTTPException(409, str(exception)) from exception

    return router
