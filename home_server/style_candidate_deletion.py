"""CHS의 기존 파일 삭제와 영속 명령을 이용해 조합의 전체 Prompt 결과를 폐기합니다."""

import json
import logging
from datetime import datetime, timezone

from pydantic import Field

from .style_projects import StyleRevisionConflict, encode_snapshot, snapshot_hash
from .style_voting import StyleVotingCommand


LOGGER = logging.getLogger(__name__)


class StyleCandidateDeletionInput(StyleVotingCommand):
    """확인창에서 선택한 조합 전체를 같은 평가 Revision에 묶습니다."""

    candidateIdentifiers: list[str] = Field(min_length=1, max_length=100)


class StyleCandidateDeletionService:
    """파일 삭제 중 중단돼도 같은 명령으로 남은 파일을 이어서 지웁니다."""

    def __init__(self, server) -> None:
        """기존 생성 Lock·Voting Command·Output Catalog를 공유합니다."""

        self.server = server

    def delete_candidates(self, project_identifier: str, payload: StyleCandidateDeletionInput) -> dict:
        """전체 소유·진행·삭제 보호를 먼저 검사하고 확인한 조합만 폐기합니다."""

        with self.server.style_generation.mutation_lock:
            operation = self.prepare_deletion(project_identifier, payload)
            if operation["status"] == "deleted":
                return operation
            return self.finish_deletion(payload.operationIdentifier)

    def prepare_deletion(self, project_identifier: str, payload: StyleCandidateDeletionInput) -> dict:
        """파일보다 먼저 영속 명령을 저장해 중단·부분 실패 뒤에도 대상이 변하지 않게 합니다."""

        request_hash = snapshot_hash({"projectIdentifier": project_identifier, "action": "delete", **payload.model_dump()})
        with self.server.database._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT payload_hash,response_json FROM style_voting_commands WHERE operation_id=?", (payload.operationIdentifier,)).fetchone()
            if existing:
                if existing["payload_hash"] != request_hash:
                    raise StyleRevisionConflict("같은 요청 ID로 다른 조합을 폐기할 수 없습니다.")
                return json.loads(existing["response_json"])
            voting = self.server.style_voting
            candidates, ready_identifiers = voting.load_evaluation_candidates(connection, project_identifier, payload.evaluationIdentifier)
            revision, state = voting.load_arena(connection, project_identifier, payload.evaluationIdentifier)
            if revision != payload.expectedRevision:
                raise StyleRevisionConflict("선별 상태가 바뀌었습니다. 최신 그림체를 확인한 뒤 다시 폐기해 주세요.")
            if connection.execute("SELECT 1 FROM style_evolution_batches WHERE project_id=? AND evaluation_id=? AND status IN ('planned','active')", (project_identifier, payload.evaluationIdentifier)).fetchone():
                raise StyleRevisionConflict("준비·진행 중인 진화를 확정하거나 취소한 뒤 조합을 폐기해 주세요.")
            identifiers = payload.candidateIdentifiers
            if len(set(identifiers)) != len(identifiers):
                raise ValueError("같은 조합을 중복 선택할 수 없습니다.")
            output_identifiers = []
            for identifier in identifiers:
                candidate = connection.execute(
                    "SELECT lifecycle FROM style_candidates JOIN style_candidate_memberships USING(candidate_id) "
                    "WHERE candidate_id=? AND project_id=? AND style_candidates.evaluation_id=? AND EXISTS(SELECT 1 FROM style_candidate_renders WHERE candidate_id=style_candidates.candidate_id)",
                    (identifier, project_identifier, payload.evaluationIdentifier),
                ).fetchone()
                if not candidate or candidate["lifecycle"] in {"deleting", "deleted"}:
                    raise LookupError("폐기할 프로젝트의 생성된 조합을 찾을 수 없습니다.")
                requests = connection.execute(
                    "SELECT requests.status,jobs.deletion_protected FROM style_candidate_renders JOIN job_requests AS requests USING(request_id) JOIN jobs USING(job_id) WHERE candidate_id=?",
                    (identifier,),
                ).fetchall()
                if any(request["status"] in {"submitting", "pending", "running", "cancelling"} for request in requests):
                    raise StyleRevisionConflict("선택한 조합의 생성·취소 작업을 마친 뒤 폐기해 주세요.")
                if any(request["deletion_protected"] for request in requests):
                    raise StyleRevisionConflict("삭제 보호된 작업의 조합입니다. 작업에서 보호를 해제한 뒤 폐기해 주세요.")
                output_identifiers.extend(row[0] for row in connection.execute("SELECT output_id FROM output_files JOIN style_candidate_renders USING(request_id) WHERE candidate_id=?", (identifier,)))
            for identifier in identifiers:
                connection.execute("UPDATE style_candidate_memberships SET lifecycle='deleting' WHERE candidate_id=?", (identifier,))
                state["statistics"].pop(identifier, None)
            state.update(match=None, placement=None, undoStack=[], lastPair=[], skippedTies=[])
            remaining = [candidate for candidate in candidates if candidate["identifier"] not in identifiers]
            remaining_ready = [identifier for identifier in ready_identifiers if identifier not in identifiers]
            voting.synchronize_candidates(state, remaining, remaining_ready)
            voting.save_arena(connection, payload.evaluationIdentifier, revision + 1, state)
            operation = {"status": "deleting", "operationIdentifier": payload.operationIdentifier, "projectIdentifier": project_identifier,
                         "evaluationIdentifier": payload.evaluationIdentifier, "candidateIdentifiers": identifiers,
                         "outputIdentifiers": sorted(set(output_identifiers)), "requestPayload": payload.model_dump(), "error": ""}
            connection.execute("INSERT INTO style_voting_commands VALUES(?,?,?,?,?,?,?)", (payload.operationIdentifier, project_identifier, payload.evaluationIdentifier, "delete", request_hash, encode_snapshot(operation), datetime.now(timezone.utc).isoformat()))
            return operation

    def finish_deletion(self, operation_identifier: str) -> dict:
        """이미 지운 파일은 건너뛰고 CHS의 경로·보호·Cache 처리를 그대로 사용합니다."""

        from .application import delete_recorded_output

        with self.server.database._connect() as connection:
            row = connection.execute("SELECT response_json FROM style_voting_commands WHERE operation_id=? AND action='delete'", (operation_identifier,)).fetchone()
        operation = json.loads(row[0])
        if operation["status"] == "deleted":
            return operation
        try:
            for output_identifier in operation["outputIdentifiers"]:
                delete_recorded_output(self.server, output_identifier)
        except Exception as exception:
            operation["error"] = "일부 이미지 파일을 삭제하지 못했습니다. 파일 사용 상태를 확인하고 조합 폐기를 다시 시도해 주세요."
            with self.server.database._connect() as connection:
                connection.execute("UPDATE style_voting_commands SET response_json=? WHERE operation_id=?", (encode_snapshot(operation), operation_identifier))
            LOGGER.warning("조합 폐기 보류: operation_id=%s error_type=%s", operation_identifier, type(exception).__name__)
            raise StyleRevisionConflict(operation["error"]) from exception
        with self.server.database._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for identifier in operation["candidateIdentifiers"]:
                connection.execute("UPDATE style_candidate_memberships SET lifecycle='deleted' WHERE candidate_id=? AND lifecycle='deleting'", (identifier,))
            operation.update(status="deleted", error="", deletedCandidateCount=len(operation["candidateIdentifiers"]), deletedOutputCount=len(operation["outputIdentifiers"]))
            connection.execute("UPDATE style_voting_commands SET response_json=? WHERE operation_id=?", (encode_snapshot(operation), operation_identifier))
        return operation

    def recover_pending_deletions(self) -> None:
        """재시작 전에 확인한 폐기 명령만 복구하며 실패한 대상은 UI 재시도로 남깁니다."""

        with self.server.database._connect() as connection:
            identifiers = [row[0] for row in connection.execute("SELECT operation_id FROM style_voting_commands WHERE action='delete' AND json_extract(response_json,'$.status')='deleting' ORDER BY rowid")]
        with self.server.style_generation.mutation_lock:
            for identifier in identifiers:
                try:
                    self.finish_deletion(identifier)
                except StyleRevisionConflict:
                    LOGGER.warning("재시작 후 조합 폐기 재시도 필요: operation_id=%s", identifier)
