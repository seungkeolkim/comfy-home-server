"""Home 인증 안에서 프로젝트 선별·Undo API를 제공합니다."""

from fastapi import APIRouter, HTTPException, Query

from .style_projects import StyleRevisionConflict
from .style_voting import StylePairInput, StyleUndoInput, StyleVoteInput


def create_style_voting_router(server) -> APIRouter:
    """실제 Vote·Undo와 서버가 선택한 현재 Match 조회 경로를 등록합니다."""

    router = APIRouter()

    @router.get("/api/style-projects/{project_identifier}/selection")
    def read_selection(project_identifier: str, evaluationIdentifier: str = Query(min_length=1, max_length=100), clientIdentifier: str = Query(min_length=16, max_length=100)):
        """평가 조건이 같은 완료 후보들의 현재 A/B와 Undo 가능 여부를 읽습니다."""

        try:
            return server.style_voting.read(project_identifier, evaluationIdentifier, clientIdentifier)
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception

    @router.post("/api/style-projects/{project_identifier}/votes")
    def record_vote(project_identifier: str, payload: StyleVoteInput):
        """여러 Prompt를 보고 선택한 조합 한 표만 기록합니다."""

        return execute_selection_command(project_identifier, "vote", payload)

    @router.post("/api/style-projects/{project_identifier}/undo")
    def undo_vote(project_identifier: str, payload: StyleUndoInput):
        """최신 본인 선택의 점수·전적과 A/B 위치를 복구합니다."""

        return execute_selection_command(project_identifier, "undo", payload)

    @router.post("/api/style-projects/{project_identifier}/selection-pair")
    def select_pair(project_identifier: str, payload: StylePairInput):
        """필수 Placement가 아닌 현재 일반 비교의 A/B를 지정합니다."""

        return execute_selection_command(project_identifier, "pair", payload)

    def execute_selection_command(project_identifier: str, action: str, payload):
        """Revision 충돌과 소유·준비 상태 오류를 구별해 전달합니다."""

        try:
            return server.style_voting.execute(project_identifier, action, payload)
        except StyleRevisionConflict as exception:
            raise HTTPException(409, str(exception)) from exception
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception

    return router
