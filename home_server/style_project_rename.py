"""프로젝트 이름·분류·출력 폴더 변경을 중단 후에도 일관되게 마칩니다."""

import json
import logging

from .output_directories import resolve_output_directory
from .output_roots import STYLE_OUTPUT_PREFIX
from .style_projects import ProjectWriteInput, StyleRevisionConflict, encode_snapshot, evaluation_without_seed


LOGGER = logging.getLogger(__name__)


class StyleProjectRenameService:
    """불변 생성 기록은 보존하고 현재 Asset 위치만 갱신합니다."""

    def __init__(self, generation_service) -> None:
        """생성 제출과 같은 프로젝트 변경 Lock을 공유합니다."""

        self.generation_service = generation_service
        self.server = generation_service.server

    def save_project(self, project_identifier: str, payload: ProjectWriteInput) -> dict:
        """출력이 있는 프로젝트의 이름 변경만 관리 Rename으로 전달합니다."""

        with self.generation_service.mutation_lock:
            project = self.generation_service.store.project(project_identifier)
            old_settings = json.loads(project["settings_json"])
            binding = json.loads(project["storage_binding_json"])
            with self.server.database._connect() as connection:
                operation = connection.execute("SELECT * FROM style_project_renames WHERE operation_id=?", (payload.operationIdentifier,)).fetchone()
            if operation:
                plan = json.loads(operation["plan_json"])
                if plan["payload"] != payload.model_dump() or operation["project_id"] != project_identifier:
                    raise StyleRevisionConflict("다른 이름 변경 요청에 사용한 ID입니다.")
                return self.finish_operation(payload.operationIdentifier)
            with self.server.database._connect() as connection:
                if connection.execute("SELECT 1 FROM style_evolution_batches WHERE project_id=? AND status IN ('planned','active')", (project_identifier,)).fetchone():
                    raise StyleRevisionConflict("준비·진행 중인 진화를 확정하거나 취소한 뒤 프로젝트 설정을 변경해 주세요.")
                if connection.execute("SELECT 1 FROM style_project_renames WHERE project_id=? AND state!='completed'", (project_identifier,)).fetchone():
                    raise StyleRevisionConflict("진행 중인 폴더 이름 변경을 먼저 복구해야 합니다.")
            if binding["state"] != "created" or old_settings["name"] == payload.settings.name:
                return self.server.database.style_projects.save_project(payload, self.server.config.workflow_directory, project_identifier)
            if project["revision"] != payload.expectedRevision:
                raise StyleRevisionConflict("프로젝트가 변경됐습니다. 최신 설정을 다시 불러와 주세요.")
            with self.server.database._connect() as connection:
                previous_contract = json.loads(connection.execute("SELECT contract_json FROM style_evaluation_revisions WHERE evaluation_id=?", (project["active_evaluation_id"],)).fetchone()[0])
            next_contract = self.server.database.style_projects.evaluation_contract(payload.settings.model_dump(), self.server.config.workflow_directory, previous_contract)
            if evaluation_without_seed(previous_contract) != evaluation_without_seed(next_contract):
                raise StyleRevisionConflict("이미지가 있는 프로젝트의 이름 변경과 Prompt·생성 조건 변경을 함께 적용할 수 없습니다.")
            with self.server.database._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute(
                    "SELECT 1 FROM style_job_ownership JOIN job_requests USING(job_id) WHERE project_id=? "
                    "AND status IN ('submitting','pending','running','cancelling') LIMIT 1", (project_identifier,),
                ).fetchone():
                    raise StyleRevisionConflict("이 프로젝트의 생성·취소 작업이 끝난 뒤 이름을 변경해 주세요.")
                if connection.execute("SELECT 1 FROM style_project_renames WHERE project_id=? AND state!='completed'", (project_identifier,)).fetchone():
                    raise StyleRevisionConflict("앞선 이름 변경 복구를 먼저 완료해야 합니다.")
                target_binding = {**binding, "project_folder": f"{payload.settings.name}__{project_identifier}"}
                plan = {"source": binding, "target": target_binding, "payload": payload.model_dump()}
                connection.execute("INSERT INTO style_project_renames VALUES(?,?,'prepared',?,NULL)",
                                   (payload.operationIdentifier, project_identifier, encode_snapshot(plan)))
            return self.finish_operation(payload.operationIdentifier)

    def finish_operation(self, operation_identifier: str) -> dict:
        """파일 Rename 이후 DB 반영 중 중단돼도 같은 Operation을 재개합니다."""

        with self.generation_service.mutation_lock:
            with self.server.database._connect() as connection:
                operation = connection.execute("SELECT * FROM style_project_renames WHERE operation_id=?", (operation_identifier,)).fetchone()
            project_identifier = operation["project_id"]
            if operation["state"] == "completed":
                return self.server.database.style_projects.project_from_row(self.generation_service.store.project(project_identifier))
            plan = json.loads(operation["plan_json"])
            source_relative = f"{plan['source']['model_folder']}/{plan['source']['project_folder']}"
            target_relative = f"{plan['target']['model_folder']}/{plan['target']['project_folder']}"
            source_prefix = STYLE_OUTPUT_PREFIX + source_relative + "/"
            target_prefix = STYLE_OUTPUT_PREFIX + target_relative + "/"
            try:
                source_directory = resolve_output_directory(self.server.style_output_directory, source_relative, must_exist=False)
                target_directory = resolve_output_directory(self.server.style_output_directory, target_relative, must_exist=False)
                if source_directory.exists() and target_directory.exists():
                    raise ValueError("변경할 폴더가 이미 존재해 덮어쓰지 않았습니다.")
                if source_directory.exists():
                    source_directory.rename(target_directory)
                elif not target_directory.exists():
                    raise ValueError("원래 출력 폴더를 찾을 수 없습니다.")
                with self.server.database._connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    old_paths = [row[0] for row in connection.execute(
                        "SELECT relative_path FROM output_files WHERE substr(relative_path,1,?)=?", (len(source_prefix), source_prefix),
                    )]
                    connection.execute(
                        "UPDATE output_files SET relative_path=? || substr(relative_path,?) WHERE substr(relative_path,1,?)=?",
                        (target_prefix, len(source_prefix) + 1, len(source_prefix), source_prefix),
                    )
                    request_rows = connection.execute(
                        "SELECT request_id,result_json FROM request_results JOIN job_requests USING(request_id) "
                        "JOIN style_job_ownership USING(job_id) WHERE project_id=?", (project_identifier,),
                    ).fetchall()
                    for request_row in request_rows:
                        result = json.loads(request_row["result_json"])
                        if "output_paths" not in result:
                            continue
                        result["output_paths"] = [target_prefix + path[len(source_prefix):] if path.startswith(source_prefix) else path for path in result["output_paths"]]
                        connection.execute("UPDATE request_results SET result_json=? WHERE request_id=?", (encode_snapshot(result), request_row["request_id"]))
                    connection.execute("UPDATE job_folders SET name=? WHERE folder_id=?", (plan["target"]["project_folder"], plan["target"]["folder_id"]))
                    saved_project = self.server.database.style_projects.save_project(
                        ProjectWriteInput(**plan["payload"]), self.server.config.workflow_directory, project_identifier,
                        connection=connection, storage_binding_override=plan["target"],
                    )
                    connection.execute("UPDATE style_project_renames SET state='completed',error_message=NULL WHERE operation_id=?", (operation_identifier,))
                for old_path in old_paths:
                    self.server.thumbnail_cache.invalidate(self.server.expected_managed_path(old_path))
                return saved_project
            except Exception as exception:
                with self.server.database._connect() as connection:
                    connection.execute("UPDATE style_project_renames SET state='pending_error',error_message=? WHERE operation_id=?", (str(exception), operation_identifier))
                raise

    def recover(self) -> None:
        """기동 시 미완료 Rename만 재개하고 다른 프로젝트의 사용은 막지 않습니다."""

        with self.server.database._connect() as connection:
            operations = connection.execute("SELECT operation_id FROM style_project_renames WHERE state!='completed'").fetchall()
        for operation in operations:
            try:
                self.finish_operation(operation[0])
            except Exception:
                LOGGER.exception("스타일 프로젝트 Rename 복구 미완료: operation_id=%s", operation[0])
