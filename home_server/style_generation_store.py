"""스타일 생성 계획·후보·Case Render의 소유 관계를 영속화합니다."""

import json
import sqlite3
from collections.abc import Callable

from .style_projects import browser_sampling_settings
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
        plan = json.loads(row["plan_json"])
        plan["sampling"] = browser_sampling_settings(plan["sampling"])
        return {**plan, "planIdentifier": plan_identifier,
                "projectRevision": row["project_revision"], "jobIdentifiers": [row[0] for row in job_rows]}

    def results(self, project_identifier: str) -> dict:
        """기존 실제 Render와 현재 미제출 계획을 조회하며 Seed 변경 뒤에도 결과를 보존합니다."""

        project = self.project(project_identifier)
        with self.connection_factory() as connection:
            candidates = connection.execute(
                "SELECT * FROM style_candidates WHERE project_id=? AND (evaluation_id=? OR EXISTS "
                "(SELECT 1 FROM style_candidate_renders WHERE candidate_id=style_candidates.candidate_id)) ORDER BY rowid",
                (project_identifier, project["active_evaluation_id"]),
            ).fetchall()
            results = []
            for candidate in candidates:
                render_rows = connection.execute(
                    "SELECT renders.*,job_requests.status,job_requests.error_message,job_requests.job_id,"
                    "job_requests.prompt_id,request_results.result_json FROM style_candidate_renders AS renders "
                    "JOIN job_requests USING(request_id) JOIN request_results USING(request_id) "
                    "WHERE candidate_id=? ORDER BY renders.rowid", (candidate["candidate_id"],),
                ).fetchall()
                renders = []
                for render_row in render_rows:
                    result = json.loads(render_row["result_json"])
                    files = [dict(row) for row in connection.execute(
                        "SELECT output_id,relative_path AS path,is_available,is_deleted FROM output_files WHERE request_id=?",
                        (render_row["request_id"],),
                    )]
                    renders.append({
                        "renderIdentifier": render_row["render_id"], "caseIdentifier": render_row["case_id"],
                        "requestIdentifier": render_row["request_id"], "jobIdentifier": render_row["job_id"],
                        "status": render_row["status"], "error": render_row["error_message"], "files": files,
                        "prompt": result.get("prompt"), "negative": result.get("negative"),
                        "settings": browser_sampling_settings(result["settings"]) if result.get("settings") else None, "loras": result.get("loras", []),
                    })
                results.append({"identifier": candidate["candidate_id"], "label": candidate["label"], "planIdentifier": candidate["plan_id"],
                                "evaluationIdentifier": candidate["evaluation_id"],
                                "components": json.loads(candidate["components_json"]), "renders": renders})
            plan_identifiers = [row[0] for row in connection.execute(
                "SELECT plan_id FROM style_generation_plans WHERE project_id=? AND (evaluation_id=? OR EXISTS "
                "(SELECT 1 FROM style_candidate_renders WHERE plan_id=style_generation_plans.plan_id)) ORDER BY created_at DESC",
                (project_identifier, project["active_evaluation_id"]),
            )]
            arena_statistics = {row["evaluation_id"]: json.loads(row["state_json"])["statistics"] for row in connection.execute("SELECT evaluation_id,state_json FROM style_voting_arenas WHERE project_id=?", (project_identifier,))}
        evaluation_identifiers = {candidate["evaluationIdentifier"] for candidate in results}
        for evaluation_identifier in evaluation_identifiers:
            identifiers = [candidate["identifier"] for candidate in results if candidate["evaluationIdentifier"] == evaluation_identifier and candidate["renders"]]
            rankings = {entry["identifier"]: entry for entry in ranked_candidate_statistics(identifiers, arena_statistics.get(evaluation_identifier, {}))}
            for candidate in results:
                if candidate["identifier"] in rankings:
                    candidate["statistics"] = rankings[candidate["identifier"]]
        plans = [self.plan(identifier, project_identifier) for identifier in plan_identifiers]
        submitted_plans = [plan for plan in reversed(plans) if plan["jobIdentifiers"]]
        batch_numbers = {plan["planIdentifier"]: index + 1 for index, plan in enumerate(submitted_plans)}
        for candidate in results:
            candidate["batchNumber"] = batch_numbers.get(candidate["planIdentifier"])
        return {"projectIdentifier": project_identifier, "activeEvaluationIdentifier": project["active_evaluation_id"], "candidates": results, "plans": plans}
