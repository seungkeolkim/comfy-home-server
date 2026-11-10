"""Home 인증을 공유하는 스타일 프로젝트 저장 API를 제공합니다."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from .style_projects import GlobalStyleSettings, ProjectWriteInput, StyleRevisionConflict
from .workflows import load_workflows


LOGGER = logging.getLogger(__name__)


def create_style_project_router(server) -> APIRouter:
    """생성 Worker를 시작하지 않는 프로젝트 조회·설정 API만 등록합니다."""

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
            return server.database.style_projects.save_project(payload, server.config.workflow_directory, project_identifier)
        except StyleRevisionConflict as exception:
            raise HTTPException(409, str(exception)) from exception
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception

    @router.put("/api/style-settings")
    def update_style_global_settings(payload: GlobalStyleSettings):
        """작가 등록·기본 STR을 저장하되 기존 프로젝트에는 소급 적용하지 않습니다."""

        try:
            return server.database.style_projects.save_global_settings(payload)
        except StyleRevisionConflict as exception:
            raise HTTPException(409, str(exception)) from exception

    return router
