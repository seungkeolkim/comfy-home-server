"""스타일 그림체를 독립된 CHS LoRA preset으로 등록하고 출처를 보관합니다."""

import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, StrictBool


class StyleLoraPresetRegistrationInput(BaseModel):
    """응답 유실 뒤 재전송해도 상태가 뒤집히지 않도록 등록 여부를 명시합니다."""

    model_config = ConfigDict(extra="forbid")
    isRegistered: StrictBool


def generated_style_lora_preset_name(project_name: str, generation_number: int, combination_number: int) -> str:
    """프로젝트 전체 이름과 원본 세대·조합 번호를 120자 이내 이름으로 구성합니다."""

    return f"[스타일] {project_name} · 세대{generation_number:03}-조합{combination_number:02}"


class StyleLoraPresetStore:
    """등록본은 기존 preset에 저장하고 원본 삭제와 독립적인 출처만 추가 관리합니다."""

    def __init__(self, connection_factory: Callable[[], sqlite3.Connection]) -> None:
        """등록과 CHS 목록이 같은 SQLite 연결 규칙을 사용하게 합니다."""

        self.connection_factory = connection_factory

    @staticmethod
    def prepare_schema(connection: sqlite3.Connection) -> None:
        """CHS preset 삭제만 Cascade하고 원본 그림체의 삭제에는 Snapshot을 유지합니다."""

        connection.execute(
            "CREATE TABLE IF NOT EXISTS style_lora_preset_sources ("
            "preset_id TEXT PRIMARY KEY REFERENCES lora_presets(preset_id) ON DELETE CASCADE, "
            "candidate_id TEXT NOT NULL UNIQUE, project_id TEXT NOT NULL, evaluation_id TEXT NOT NULL, "
            "project_name TEXT NOT NULL, generation_number INTEGER NOT NULL, combination_number INTEGER NOT NULL, "
            "model_identifier TEXT NOT NULL, generated_name TEXT NOT NULL, original_loras_json TEXT NOT NULL)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS style_lora_presets_project ON style_lora_preset_sources(project_id)")

    def set_registration(self, project_identifier: str, candidate_identifier: str, is_registered: bool) -> dict:
        """원본 소유를 확인하고 한 Transaction에서 preset과 출처를 함께 등록·해제합니다."""

        from .style_generation_store import StyleGenerationStore

        with self.connection_factory() as connection:
            connection.execute("BEGIN IMMEDIATE")
            candidate = connection.execute(
                "SELECT candidates.*,memberships.lifecycle,memberships.generation_number,projects.settings_json,"
                "evaluations.contract_json,plans.plan_json FROM style_candidates AS candidates "
                "JOIN style_candidate_memberships AS memberships USING(candidate_id) "
                "JOIN style_projects AS projects USING(project_id) "
                "JOIN style_evaluation_revisions AS evaluations ON evaluations.evaluation_id=candidates.evaluation_id "
                "JOIN style_generation_plans AS plans ON plans.plan_id=candidates.plan_id "
                "WHERE candidates.candidate_id=? AND candidates.project_id=? AND EXISTS "
                "(SELECT 1 FROM style_candidate_renders WHERE candidate_id=candidates.candidate_id)",
                (candidate_identifier, project_identifier),
            ).fetchone()
            if candidate is None or candidate["lifecycle"] in {"deleting", "deleted"}:
                raise LookupError("LoRA 조합으로 등록할 프로젝트의 생성된 그림체를 찾을 수 없습니다.")
            existing = connection.execute(
                "SELECT presets.preset_id,presets.name FROM style_lora_preset_sources AS sources "
                "JOIN lora_presets AS presets USING(preset_id) WHERE candidate_id=?", (candidate_identifier,),
            ).fetchone()
            if not is_registered:
                if existing:
                    connection.execute("DELETE FROM lora_presets WHERE preset_id=?", (existing["preset_id"],))
                return {"candidateIdentifier": candidate_identifier, "isRegistered": False, "loraPresetIdentifier": None, "presetName": None}
            if existing:
                return {"candidateIdentifier": candidate_identifier, "isRegistered": True,
                        "loraPresetIdentifier": existing["preset_id"], "presetName": existing["name"]}
            selected_loras = []
            for component in json.loads(candidate["components_json"]):
                if not component["identifier"].startswith("lora:"):
                    continue
                selected_loras.append({"name": component["identifier"][5:], "strength": component["strength"],
                                       "clip_strength": component.get("clip_strength", component["strength"])})
            if not selected_loras:
                raise ValueError("이 그림체에는 등록할 LoRA가 없습니다.")
            settings = json.loads(candidate["settings_json"])
            contract = json.loads(candidate["contract_json"])
            identity = StyleGenerationStore.candidate_display_identity(candidate, json.loads(candidate["plan_json"]), candidate["generation_number"])
            preset_identifier = uuid.uuid4().hex
            preset_name = generated_style_lora_preset_name(settings["name"], candidate["generation_number"], identity["combinationNumber"])
            saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            loras_json = json.dumps(selected_loras, ensure_ascii=False)
            connection.execute("INSERT INTO lora_presets VALUES(?,?,?,?,?,?)", (
                preset_identifier, preset_name, contract["workflow"]["identifier"], loras_json, saved_at, saved_at,
            ))
            connection.execute("INSERT INTO style_lora_preset_sources VALUES(?,?,?,?,?,?,?,?,?,?)", (
                preset_identifier, candidate_identifier, project_identifier, candidate["evaluation_id"], settings["name"],
                candidate["generation_number"], identity["combinationNumber"], contract["workflow"]["model_identifier"], preset_name, loras_json,
            ))
        return {"candidateIdentifier": candidate_identifier, "isRegistered": True,
                "loraPresetIdentifier": preset_identifier, "presetName": preset_name}

    @staticmethod
    def preset_sources(connection: sqlite3.Connection) -> dict:
        """LoRA 목록의 출처·모델·원본 이동 가능 여부를 파일 접근 없이 일괄 조회합니다."""

        rows = connection.execute(
            "SELECT sources.*,presets.name AS current_name,presets.loras_json AS current_loras_json,"
            "(projects.project_id IS NOT NULL AND memberships.lifecycle NOT IN ('deleting','deleted')) AS source_available "
            "FROM style_lora_preset_sources AS sources JOIN lora_presets AS presets USING(preset_id) "
            "LEFT JOIN style_projects AS projects ON projects.project_id=sources.project_id "
            "LEFT JOIN style_candidate_memberships AS memberships ON memberships.candidate_id=sources.candidate_id"
        ).fetchall()
        sources = {}
        for row in rows:
            sources[row["preset_id"]] = {
                "project_id": row["project_id"], "candidate_id": row["candidate_id"], "evaluation_id": row["evaluation_id"],
                "project_name": row["project_name"], "generation_number": row["generation_number"],
                "combination_number": row["combination_number"], "model_identifier": row["model_identifier"],
                "source_available": bool(row["source_available"]),
                "automatic_name": row["current_name"] == row["generated_name"],
                "modified": json.loads(row["original_loras_json"]) != json.loads(row["current_loras_json"]),
            }
        return sources

    @staticmethod
    def rename_project_registrations(connection: sqlite3.Connection, project_identifier: str, project_name: str) -> None:
        """자동 이름만 프로젝트 Rename에 맞추고 사용자가 직접 붙인 이름은 보존합니다."""

        rows = connection.execute(
            "SELECT sources.*,presets.name FROM style_lora_preset_sources AS sources "
            "JOIN lora_presets AS presets USING(preset_id) WHERE project_id=?", (project_identifier,),
        ).fetchall()
        for row in rows:
            generated_name = generated_style_lora_preset_name(project_name, row["generation_number"], row["combination_number"])
            if row["name"] == row["generated_name"] and row["name"] != generated_name:
                connection.execute("UPDATE lora_presets SET name=?,updated_at=? WHERE preset_id=?", (
                    generated_name, datetime.now(timezone.utc).isoformat(timespec="seconds"), row["preset_id"],
                ))
            connection.execute("UPDATE style_lora_preset_sources SET project_name=?,generated_name=? WHERE preset_id=?",
                               (project_name, generated_name, row["preset_id"]))
