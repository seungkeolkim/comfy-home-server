"""Home 인증 안에서 프로젝트 선별·Undo API를 제공합니다."""

import sqlite3

from fastapi import APIRouter, HTTPException, Query

from .style_projects import StyleRevisionConflict
from .style_candidate_deletion import StyleCandidateDeletionInput
from .style_voting import StyleCandidateRatingInput, StylePairInput, StyleUndoInput, StyleVoteInput


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

    @router.post("/api/style-projects/{project_identifier}/candidate-ratings")
    def update_candidate_ratings(project_identifier: str, payload: StyleCandidateRatingInput):
        """단건·다중 선택 조합의 Elo를 수정하고 최신 순위를 반환합니다."""

        return execute_selection_command(project_identifier, "rating", payload)

    @router.post("/api/style-projects/{project_identifier}/candidate-deletions")
    def delete_candidates(project_identifier: str, payload: StyleCandidateDeletionInput):
        """확인한 조합의 전체 Prompt·재시도 이미지를 CHS 삭제 경로로 폐기합니다."""

        try:
            return server.style_candidate_deletion.delete_candidates(project_identifier, payload)
        except StyleRevisionConflict as exception:
            raise HTTPException(409, str(exception)) from exception
        except LookupError as exception:
            raise HTTPException(404, str(exception)) from exception
        except ValueError as exception:
            raise HTTPException(422, str(exception)) from exception
        except sqlite3.Error as exception:
            raise HTTPException(409, "조합 폐기 상태를 DB에 반영하지 못했습니다. 최신 목록을 확인하고 다시 시도해 주세요.") from exception

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
