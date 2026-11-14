"""스타일 생성 계획·후보·Case Render의 소유 관계를 영속화합니다."""

import json
import sqlite3
from collections.abc import Callable

from .style_projects import browser_sampling_settings
from .style_generation_sizing import generation_sizing_from_plans
from .style_voting import ranked_candidate_statistics


class StyleGenerationStore:
    """이미지 상태는 CHS 요청에서 읽고 평가 구간별 저장 순위를 함께 조회합니다."""

    def __init__(self, connection_factory: Callable[[], sqlite3.Connection]) -> None:
        """현재 DB 파일을 여는 연결 Factory만 보관합니다."""

        self.connection_factory = connection_factory

    @staticmethod
    def prepare_schema(connection: sqlite3.Connection) -> None:
        """생성과 관리 Rename에 지금 필요한 테이블만 추가합니다."""

        job_columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
        if "origin" not in job_columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN origin TEXT NOT NULL DEFAULT 'general'")
        connection.execute("CREATE INDEX IF NOT EXISTS jobs_origin_created ON jobs(origin,created_at DESC)")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_generation_plans ("
            "plan_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES style_projects(project_id), "
            "evaluation_id TEXT NOT NULL REFERENCES style_evaluation_revisions(evaluation_id), "
            "project_revision INTEGER NOT NULL, operation_id TEXT NOT NULL UNIQUE, payload_hash TEXT NOT NULL, "
            "plan_json TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_candidates ("
            "candidate_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES style_projects(project_id), "
            "evaluation_id TEXT NOT NULL REFERENCES style_evaluation_revisions(evaluation_id), "
            "plan_id TEXT NOT NULL REFERENCES style_generation_plans(plan_id), "
            "label TEXT NOT NULL, components_json TEXT NOT NULL, fingerprint TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_candidate_renders ("
            "render_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES style_candidates(candidate_id), "
            "plan_id TEXT NOT NULL REFERENCES style_generation_plans(plan_id), case_id TEXT NOT NULL, "
            "request_id TEXT NOT NULL UNIQUE REFERENCES job_requests(request_id) ON DELETE RESTRICT, "
            "render_plan_json TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_job_ownership ("
            "job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE RESTRICT, "
            "project_id TEXT NOT NULL REFERENCES style_projects(project_id), "
            "plan_id TEXT NOT NULL REFERENCES style_generation_plans(plan_id), "
            "operation_id TEXT NOT NULL UNIQUE, sequence INTEGER NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_managed_folders ("
            "folder_id TEXT PRIMARY KEY REFERENCES job_folders(folder_id) ON DELETE RESTRICT, "
            "model_identifier TEXT NOT NULL, project_id TEXT UNIQUE REFERENCES style_projects(project_id))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_project_renames ("
            "operation_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES style_projects(project_id), "
            "state TEXT NOT NULL, plan_json TEXT NOT NULL, error_message TEXT)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS style_renders_candidate ON style_candidate_renders(candidate_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS style_renders_plan ON style_candidate_renders(plan_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS output_files_request ON output_files(request_id)")

    def project(self, project_identifier: str) -> sqlite3.Row:
        """소유 프로젝트가 없으면 다른 범위로 대신 처리하지 않습니다."""

        with self.connection_factory() as connection:
            row = connection.execute("SELECT * FROM style_projects WHERE project_id=?", (project_identifier,)).fetchone()
        if row is None:
            raise LookupError("프로젝트를 찾을 수 없습니다.")
        return row

    def plan(self, plan_identifier: str, project_identifier: str) -> dict:
        """요청한 프로젝트가 소유한 불변 생성 계획만 조회합니다."""

        with self.connection_factory() as connection:
            row = connection.execute(
                "SELECT * FROM style_generation_plans WHERE plan_id=? AND project_id=?",
                (plan_identifier, project_identifier),
            ).fetchone()
            if row is None:
                raise LookupError("생성 계획을 찾을 수 없습니다.")
            job_rows = connection.execute(
                "SELECT job_id FROM style_job_ownership WHERE plan_id=? ORDER BY sequence", (plan_identifier,),
            ).fetchall()
            evolution = connection.execute("SELECT status FROM style_evolution_batches WHERE plan_id=?", (plan_identifier,)).fetchone()
        plan = json.loads(row["plan_json"])
        plan.setdefault("generationNumber", 1)
        plan["sampling"] = browser_sampling_settings(plan["sampling"])
        return {**plan, "evolutionStatus": evolution[0] if evolution else None, "planIdentifier": plan_identifier,
                "operationIdentifier": row["operation_id"], "projectRevision": row["project_revision"], "jobIdentifiers": [row[0] for row in job_rows]}

    @staticmethod
    def browser_plan(row, job_identifiers: list[str]) -> dict:
        """같은 연결에서 읽은 계획·소유 Job·진화 상태를 Browser 형식으로 변환합니다."""

        plan = json.loads(row["plan_json"])
        plan.setdefault("generationNumber", 1)
        plan["sampling"] = browser_sampling_settings(plan["sampling"])
        return {**plan, "evolutionStatus": row["evolution_status"], "planIdentifier": row["plan_id"],
                "operationIdentifier": row["operation_id"], "projectRevision": row["project_revision"],
                "jobIdentifiers": job_identifiers}

    def results(self, project_identifier: str, summary: bool = False) -> dict:
        """카드용 Summary는 생성 Graph를 읽지 않고 Render·파일·계획을 일괄 조회합니다."""

        with self.connection_factory() as connection:
            project = connection.execute("SELECT * FROM style_projects WHERE project_id=?", (project_identifier,)).fetchone()
            if project is None:
                raise LookupError("프로젝트를 찾을 수 없습니다.")
            memberships = {row["candidate_id"]: dict(row) for row in connection.execute(
                "SELECT memberships.* FROM style_candidate_memberships AS memberships "
                "JOIN style_candidates USING(candidate_id) WHERE project_id=?", (project_identifier,))}
            plan_rows = connection.execute(
                "SELECT plans.*,batches.status AS evolution_status,EXISTS "
                "(SELECT 1 FROM style_candidate_renders WHERE plan_id=plans.plan_id) AS has_renders "
                "FROM style_generation_plans AS plans LEFT JOIN style_evolution_batches AS batches USING(plan_id) "
                "WHERE plans.project_id=? ORDER BY plans.created_at DESC", (project_identifier,),
            ).fetchall()
            jobs_by_plan = {}
            for row in connection.execute("SELECT plan_id,job_id FROM style_job_ownership WHERE project_id=? ORDER BY sequence", (project_identifier,)):
                jobs_by_plan.setdefault(row["plan_id"], []).append(row["job_id"])
            stored_plans = {row["plan_id"]: self.browser_plan(row, jobs_by_plan.get(row["plan_id"], [])) for row in plan_rows}
            plans = [stored_plans[row["plan_id"]] for row in plan_rows if row["evaluation_id"] == project["active_evaluation_id"] or row["has_renders"]]
            current_generation = connection.execute("SELECT generation_number FROM style_evolution_timelines WHERE evaluation_id=?", (project["active_evaluation_id"],)).fetchone()
            candidates = connection.execute(
                "SELECT * FROM style_candidates WHERE project_id=? AND (evaluation_id=? OR EXISTS "
                "(SELECT 1 FROM style_candidate_renders WHERE candidate_id=style_candidates.candidate_id)) ORDER BY rowid",
                (project_identifier, project["active_evaluation_id"]),
            ).fetchall()
            # 원본 JSON의 Graph는 전송하지 않고 상세 화면이 쓰는 필드만 읽습니다.
            detail_columns = ""
            detail_join = ""
            if not summary:
                detail_columns = (
                    ",json_extract(result_json,'$.prompt') AS prompt,json_extract(result_json,'$.negative') AS negative,"
                    "json_extract(result_json,'$.settings') AS settings_json,json_extract(result_json,'$.loras') AS loras_json"
                )
                detail_join = " JOIN request_results USING(request_id)"
            render_rows = connection.execute(
                "SELECT renders.*,requests.status,requests.error_message,requests.job_id" + detail_columns +
                " FROM style_candidate_renders AS renders JOIN style_candidates AS candidates USING(candidate_id) "
                "JOIN job_requests AS requests USING(request_id)" + detail_join +
                " WHERE candidates.project_id=? ORDER BY renders.rowid", (project_identifier,),
            ).fetchall()
            files_by_request = {}
            for row in connection.execute(
                "SELECT files.request_id,files.output_id,files.relative_path AS path,files.is_available,files.is_deleted "
                "FROM output_files AS files JOIN style_candidate_renders AS renders USING(request_id) "
                "JOIN style_candidates AS candidates USING(candidate_id) WHERE candidates.project_id=? ORDER BY files.output_id", (project_identifier,),
            ):
                output_file = dict(row)
                request_identifier = output_file.pop("request_id")
                files_by_request.setdefault(request_identifier, []).append(output_file)
            renders_by_candidate = {}
            for row in render_rows:
                render = {
                    "renderIdentifier": row["render_id"], "caseIdentifier": row["case_id"],
                    "requestIdentifier": row["request_id"], "jobIdentifier": row["job_id"],
                    "status": row["status"], "error": row["error_message"], "files": files_by_request.get(row["request_id"], []),
                }
                if not summary:
                    settings = json.loads(row["settings_json"]) if row["settings_json"] else None
                    render.update(prompt=row["prompt"], negative=row["negative"],
                                  settings=browser_sampling_settings(settings) if settings else None,
                                  loras=json.loads(row["loras_json"]) if row["loras_json"] else [])
                renders_by_candidate.setdefault(row["candidate_id"], []).append(render)
            results = []
            for candidate in candidates:
                membership = memberships[candidate["candidate_id"]]
                if membership["lifecycle"] in {"deleting", "deleted"}:
                    continue
                results.append({
                    "identifier": candidate["candidate_id"], "label": candidate["label"], "planIdentifier": candidate["plan_id"],
                    **self.candidate_display_identity(candidate, stored_plans[candidate["plan_id"]], membership["generation_number"]),
                    "evaluationIdentifier": candidate["evaluation_id"], "generationNumber": membership["generation_number"],
                    "lifecycle": membership["lifecycle"], "evolutionBatchIdentifier": membership["batch_id"],
                    "breedingMode": membership["breeding_mode"], "parentIdentifiers": json.loads(membership["parent_ids_json"]),
                    "components": json.loads(candidate["components_json"]), "renders": renders_by_candidate.get(candidate["candidate_id"], []),
                })
            arena_statistics = {row["evaluation_id"]: json.loads(row["state_json"])["statistics"] for row in connection.execute("SELECT evaluation_id,state_json FROM style_voting_arenas WHERE project_id=?", (project_identifier,))}
            pending_deletions = [json.loads(row[0]) for row in connection.execute("SELECT response_json FROM style_voting_commands WHERE project_id=? AND action='delete' AND json_extract(response_json,'$.status')='deleting' ORDER BY rowid", (project_identifier,))]
            for row in connection.execute("SELECT evaluation_id,result_json FROM style_evolution_batches WHERE project_id=? AND status='cancelled' AND result_json IS NOT NULL", (project_identifier,)):
                statistics = json.loads(row["result_json"]).get("cancelledStatistics", {})
                arena_statistics.setdefault(row["evaluation_id"], {}).update({identifier: value for identifier, value in statistics.items() if value is not None})
        evaluation_identifiers = {candidate["evaluationIdentifier"] for candidate in results}
        for evaluation_identifier in evaluation_identifiers:
            identifiers = [candidate["identifier"] for candidate in results if candidate["evaluationIdentifier"] == evaluation_identifier and candidate["renders"] and candidate["lifecycle"] in {"active", "evolving"}]
            rankings = {entry["identifier"]: entry for entry in ranked_candidate_statistics(identifiers, arena_statistics.get(evaluation_identifier, {}))}
            for candidate in results:
                if candidate["identifier"] in rankings:
                    candidate["statistics"] = rankings[candidate["identifier"]]
                elif candidate["evaluationIdentifier"] == evaluation_identifier and candidate["renders"]:
                    archived = ranked_candidate_statistics([candidate["identifier"]], arena_statistics.get(evaluation_identifier, {}))[0]
                    candidate["statistics"] = {**archived, "rank": None}
        submitted_plans = [plan for plan in reversed(plans) if plan["jobIdentifiers"]]
        batch_numbers = {plan["planIdentifier"]: index + 1 for index, plan in enumerate(submitted_plans)}
        for candidate in results:
            candidate["batchNumber"] = batch_numbers.get(candidate["planIdentifier"])
        return {"projectIdentifier": project_identifier, "activeEvaluationIdentifier": project["active_evaluation_id"], "currentGeneration": current_generation[0] if current_generation else 1, "candidates": results, "plans": plans, "pendingCandidateDeletions": pending_deletions,
                "generationSizing": generation_sizing_from_plans(list(stored_plans.values()))}

    @staticmethod
    def candidate_display_identity(candidate, plan: dict, generation_number: int) -> dict:
        """표시 이름은 기존·신규 파일명의 세대·조합 번호와 일치시킵니다."""

        for combination_index, combination in enumerate(plan["candidates"], 1):
            if combination["identifier"] == candidate["candidate_id"]:
                combination_number = combination.get("combinationNumber", combination_index)
                return {"combinationNumber": combination_number, "displayName": combination.get("displayName", f"세대{generation_number:03}-조합{combination_number:02}")}
        raise ValueError("생성 계획에서 조합 식별자를 찾을 수 없습니다.")
