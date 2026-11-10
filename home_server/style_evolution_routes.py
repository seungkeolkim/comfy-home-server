"""Home 인증 안에서 다음 세대 준비·확정·취소 API를 제공합니다."""

import asyncio

import httpx
from fastapi import APIRouter, HTTPException, Query

from .style_evolution import EvolutionActionInput, EvolutionPlanInput
from .style_projects import StyleRevisionConflict


def create_style_evolution_router(server) -> APIRouter:
    """생성 제출은 기존 Generation API로 재사용하고 세대 전환만 등록합니다."""

    router = APIRouter()

    @router.get("/api/style-projects/{project_identifier}/evolution")
    def read_evolution(project_identifier: str, evaluationIdentifier: str = Query(min_length=1, max_length=100)):
        """진화 준비 조건·진행 상태·확정 가능 여부를 조회합니다."""

        try:
            return server.style_evolution.read_evolution(project_identifier, evaluationIdentifier)
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception

    @router.post("/api/style-projects/{project_identifier}/evolution-plans", status_code=201)
    async def prepare_evolution(project_identifier: str, payload: EvolutionPlanInput):
        """GPU 제출 없이 고정 부모와 자녀 조합·실제 생성 장수를 준비합니다."""

        try:
            return await server.style_evolution.prepare_evolution_plan(project_identifier, payload)
        except StyleRevisionConflict as exception:
            raise HTTPException(409, str(exception)) from exception
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception
        except (RuntimeError, httpx.HTTPError) as exception:
            raise HTTPException(502, "ComfyUI 사전 확인에 실패했습니다. 생성 작업은 접수하지 않았습니다.") from exception

    @router.post("/api/style-projects/{project_identifier}/evolution-batches/{batch_identifier}/{action}")
    async def finish_evolution(project_identifier: str, batch_identifier: str, action: str, payload: EvolutionActionInput):
        """최신 평가 결과로 확정하거나 자녀만 취소하고 취소 Worker를 깨웁니다."""

        if action not in {"confirm", "cancel"}:
            raise HTTPException(404, "세대 처리 경로를 찾을 수 없습니다.")
        try:
            result = await asyncio.to_thread(server.style_evolution.execute_evolution_action, project_identifier, batch_identifier, action, payload)
        except StyleRevisionConflict as exception:
            raise HTTPException(409, str(exception)) from exception
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception
        if action == "cancel":
            for job_identifier in result.get("jobIdentifiers", []):
                for request in server.database.get_job(job_identifier)["requests"]:
                    server.cancellation_retry_after.pop(request["request_id"], None)
            server.cancellation_wakeup.set()
        return result

    return router
