"""CHS의 기존 파일 삭제와 영속 명령을 이용해 조합의 전체 Prompt 결과를 폐기합니다."""

import json
import logging
from datetime import datetime, timezone

from pydantic import Field

from .style_projects import StyleRevisionConflict, encode_snapshot, snapshot_hash
from .style_voting import StyleVotingCommand, ranked_candidate_statistics
from .style_deletion_cleanup import remove_deleted_candidate_history
from .style_voting_rules import remove_deleted_candidate_state


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
            if operation["status"] == "deleted" and operation.get("cleanupVersion") == 2:
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
            voting.load_evaluation_candidates(connection, project_identifier, payload.evaluationIdentifier, verify_files=False)
            revision, state = voting.load_arena(connection, project_identifier, payload.evaluationIdentifier)
            if revision != payload.expectedRevision:
                raise StyleRevisionConflict("선별 상태가 바뀌었습니다. 최신 그림체를 확인한 뒤 다시 폐기해 주세요.")
            if connection.execute("SELECT 1 FROM style_evolution_batches WHERE project_id=? AND evaluation_id=? AND status IN ('planned','active')", (project_identifier, payload.evaluationIdentifier)).fetchone():
                raise StyleRevisionConflict("준비·진행 중인 진화를 확정하거나 취소한 뒤 조합을 폐기해 주세요.")
            identifiers = payload.candidateIdentifiers
            if len(set(identifiers)) != len(identifiers):
                raise ValueError("같은 조합을 중복 선택할 수 없습니다.")
            active_population_count = connection.execute(
                "SELECT COUNT(*) FROM style_candidate_memberships AS memberships "
                "JOIN style_candidates USING(candidate_id) WHERE project_id=? "
                "AND memberships.evaluation_id=? AND lifecycle='active'",
                (project_identifier, payload.evaluationIdentifier),
            ).fetchone()[0]
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
                connection.execute("DELETE FROM style_candidate_favorites WHERE candidate_id=?", (identifier,))
            remove_deleted_candidate_state(state, identifiers)
            state.update(match=None, placement=None, undoStack=[], lastPair=[], skippedTies=[])
            promoted_identifiers = self.replenish_active_candidates(
                connection, project_identifier, payload.evaluationIdentifier, state, active_population_count,
            )
            remaining, remaining_ready = voting.load_evaluation_candidates(connection, project_identifier, payload.evaluationIdentifier)
            voting.synchronize_candidates(state, remaining, remaining_ready)
            voting.save_arena(connection, payload.evaluationIdentifier, revision + 1, state)
            operation = {"status": "deleting", "operationIdentifier": payload.operationIdentifier, "projectIdentifier": project_identifier,
                         "evaluationIdentifier": payload.evaluationIdentifier, "candidateIdentifiers": identifiers,
                         "promotedCandidateIdentifiers": promoted_identifiers,
                         "outputIdentifiers": sorted(set(output_identifiers)), "requestPayload": payload.model_dump(), "error": ""}
            connection.execute("INSERT INTO style_voting_commands VALUES(?,?,?,?,?,?,?)", (payload.operationIdentifier, project_identifier, payload.evaluationIdentifier, "delete", request_hash, encode_snapshot(operation), datetime.now(timezone.utc).isoformat()))
            return operation

    def replenish_active_candidates(self, connection, project_identifier: str, evaluation_identifier: str, state: dict, population_count: int) -> list[str]:
        """삭제 전 활성 수까지 이미지가 준비된 보관 조합을 기존 순위대로 승격합니다."""

        membership_rows = connection.execute(
            "SELECT candidate_id,lifecycle FROM style_candidate_memberships AS memberships "
            "JOIN style_candidates USING(candidate_id) WHERE project_id=? AND memberships.evaluation_id=?",
            (project_identifier, evaluation_identifier),
        ).fetchall()
        active_count = sum(row["lifecycle"] == "active" for row in membership_rows)
        vacancy_count = population_count - active_count
        retired_identifiers = {row["candidate_id"] for row in membership_rows if row["lifecycle"] == "retired"}
        if vacancy_count <= 0 or not retired_identifiers:
            return []
        voting = self.server.style_voting
        candidates, ready_identifiers = voting.load_evaluation_candidates(
            connection, project_identifier, evaluation_identifier, verify_files=False, include_retired=True,
        )
        candidates_by_identifier = {candidate["identifier"]: candidate for candidate in candidates}
        available_identifiers = [identifier for identifier in ready_identifiers if identifier in retired_identifiers]
        ranked_candidates = ranked_candidate_statistics(available_identifiers, state["statistics"])
        promoted_identifiers = []
        for candidate in ranked_candidates:
            candidate_identifier = candidate["identifier"]
            if not candidate["rated"] or not voting.candidate_files_exist(candidates_by_identifier[candidate_identifier]):
                continue
            # Elo·승패·계보와 파일은 유지하고 생존 상태만 바꿉니다.
            connection.execute(
                "UPDATE style_candidate_memberships SET lifecycle='active' WHERE candidate_id=? AND lifecycle='retired'",
                (candidate_identifier,),
            )
            promoted_identifiers.append(candidate_identifier)
            if len(promoted_identifiers) == vacancy_count:
                break
        return promoted_identifiers

    def finish_deletion(self, operation_identifier: str) -> dict:
        """이미 지운 파일은 건너뛰고 CHS의 경로·보호·Cache 처리를 그대로 사용합니다."""

        from .application import delete_recorded_output

        with self.server.database._connect() as connection:
            row = connection.execute("SELECT response_json FROM style_voting_commands WHERE operation_id=? AND action='delete'", (operation_identifier,)).fetchone()
        operation = json.loads(row[0])
        if operation["status"] == "deleted" and operation.get("cleanupVersion") == 2:
            return operation
        try:
            for output_identifier in operation["outputIdentifiers"]:
                delete_recorded_output(self.server, output_identifier)
            with self.server.database._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                for identifier in operation["candidateIdentifiers"]:
                    connection.execute("UPDATE style_candidate_memberships SET lifecycle='deleted' WHERE candidate_id=? AND lifecycle IN ('deleting','deleted')", (identifier,))
                cleanup = remove_deleted_candidate_history(connection, operation["candidateIdentifiers"])
                arena = connection.execute("SELECT revision,state_json FROM style_voting_arenas WHERE evaluation_id=?", (operation["evaluationIdentifier"],)).fetchone()
                state = json.loads(arena["state_json"])
                if remove_deleted_candidate_state(state, operation["candidateIdentifiers"]):
                    self.server.style_voting.save_arena(connection, operation["evaluationIdentifier"], arena["revision"] + 1, state)
                operation.update(status="deleted", error="", cleanupVersion=2, deletedCandidateCount=len(operation["candidateIdentifiers"]),
                                 deletedOutputCount=len(operation["outputIdentifiers"]), **cleanup)
                connection.execute("UPDATE style_voting_commands SET response_json=? WHERE operation_id=?", (encode_snapshot(operation), operation_identifier))
        except Exception as exception:
            operation["status"] = "deleting"
            operation["error"] = "일부 이미지 또는 생성 이력을 정리하지 못했습니다. 조합 폐기를 다시 시도해 주세요."
            with self.server.database._connect() as connection:
                connection.execute("UPDATE style_voting_commands SET response_json=? WHERE operation_id=?", (encode_snapshot(operation), operation_identifier))
            LOGGER.warning("조합 폐기 보류: operation_id=%s error_type=%s", operation_identifier, type(exception).__name__)
            raise StyleRevisionConflict(operation["error"]) from exception
        return operation

    def recover_pending_deletions(self) -> None:
        """미완료 폐기와 이전 방식으로 삭제한 조합의 잔여 생성 이력만 복구·정리합니다."""

        with self.server.database._connect() as connection:
            identifiers = [row[0] for row in connection.execute(
                "SELECT operation_id FROM style_voting_commands WHERE action='delete' AND "
                "(json_extract(response_json,'$.status')='deleting' OR "
                "(json_extract(response_json,'$.status')='deleted' AND COALESCE(json_extract(response_json,'$.cleanupVersion'),0)<2)) ORDER BY rowid",
            )]
        with self.server.style_generation.mutation_lock:
            for identifier in identifiers:
                try:
                    self.finish_deletion(identifier)
                except StyleRevisionConflict:
                    LOGGER.warning("재시작 후 조합 폐기 재시도 필요: operation_id=%s", identifier)
