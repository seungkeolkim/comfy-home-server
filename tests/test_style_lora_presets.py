"""스타일 LoRA 등록의 원본 보존·출처·수명·Rename·Migration을 검증합니다."""

import copy
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor

from home_server.database import Database
from test_style_favorites import favorite_independent_rows
from test_style_generation import StyleComfyClient, prepare_style_generation, submit_and_wait
from test_style_management import management_payload
from test_style_voting import read_selection


def candidate_registration_endpoint(project, candidate):
    """프로젝트와 원본 조합의 소유 관계를 경로에 고정합니다."""

    return f"/api/style-projects/{project['identifier']}/candidates/{candidate['identifier']}/lora-preset"


def test_registration_is_persistent_idempotent_and_uses_the_frozen_lora_snapshot(tmp_path):
    """별표·점수·원본을 유지하고 LoRA STR·독립 CLIP을 다른 Session에서도 보존합니다."""

    application, client, project, payload = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan, _, _ = submit_and_wait(client, project, payload)
        candidate = plan["candidates"][0]
        endpoint = candidate_registration_endpoint(project, candidate)
        read_selection(client, project)
        before = favorite_independent_rows(application.state.home_server.database.database_path)
        first = client.put(endpoint, json={"isRegistered": True})
        assert first.status_code == 200, first.text
        registered = first.json()
        assert client.put(endpoint, json={"isRegistered": True}).json() == registered
        assert favorite_independent_rows(application.state.home_server.database.database_path) == before
        presets = client.get("/api/loras/presets").json()
        assert len(presets) == 1
        preset = presets[0]
        assert preset["preset_id"] == registered["loraPresetIdentifier"]
        assert preset["name"] == f"[스타일] {project['name']} · 세대001-조합01"
        assert preset["loras"] == [{"name": "example.safetensors", "strength": 0.4, "clip_strength": 0}]
        assert preset["style_source"]["project_id"] == project["identifier"]
        assert preset["style_source"]["candidate_id"] == candidate["identifier"]
        assert preset["style_source"]["model_identifier"]
        assert preset["style_source"]["source_available"] is True
        assert preset["style_source"]["modified"] is False
        client.cookies.clear()
        assert client.put(endpoint, json={"isRegistered": False}).status_code == 401
        client.post("/api/login", json={"password": "test"})
        for summary in (True, False):
            results = client.get(f"/api/style-projects/{project['identifier']}/generation-results", params={"summary": summary}).json()
            assert results["candidates"][0]["loraPresetIdentifier"] == preset["preset_id"]
        for _ in range(2):
            assert client.put(endpoint, json={"isRegistered": False}).json()["isRegistered"] is False
        assert client.get("/api/loras/presets").json() == []
        assert favorite_independent_rows(application.state.home_server.database.database_path) == before
    finally:
        client.__exit__(None, None, None)


def test_registration_checks_owner_submission_boolean_and_lora_presence(tmp_path):
    """잘못된 소유·미제출·작가 전용 조합은 preset을 만들지 않습니다."""

    application, client, project, payload = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        payload["combinations"][1] = {"components": [{"identifier": "artist:example", "strength": 0.6}]}
        plan = client.post(f"/api/style-projects/{project['identifier']}/generation-plans", json=payload).json()
        endpoint = candidate_registration_endpoint(project, plan["candidates"][0])
        assert client.put(endpoint, json={"isRegistered": True}).status_code == 404
        submit_and_wait(client, project, payload)
        other = client.post("/api/style-projects", json={"operationIdentifier": uuid.uuid4().hex, "settings": {**project["settings"], "name": "다른 프로젝트"}}).json()
        assert client.put(candidate_registration_endpoint(other, plan["candidates"][0]), json={"isRegistered": True}).status_code == 404
        for invalid in ({"isRegistered": "false"}, {"isRegistered": 1}, {}, {"isRegistered": True, "name": "override"}):
            assert client.put(endpoint, json=invalid).status_code == 422
        response = client.put(candidate_registration_endpoint(project, plan["candidates"][1]), json={"isRegistered": True})
        assert response.status_code == 422 and "LoRA가 없습니다" in response.json()["detail"]
        assert client.get("/api/loras/presets").json() == []
        with application.state.home_server.database._connect() as connection:
            assert connection.execute("SELECT count(*) FROM style_lora_preset_sources").fetchone()[0] == 0
    finally:
        client.__exit__(None, None, None)


def test_chs_deletion_copy_and_edit_are_independent_and_concurrent_registration_is_unique(tmp_path):
    """동시 등록은 하나이고 CHS의 편집·복사·삭제를 원본으로 되돌리거나 전파하지 않습니다."""

    application, client, project, payload = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan, _, _ = submit_and_wait(client, project, payload)
        candidate = plan["candidates"][0]
        store = application.state.home_server.database.style_lora_presets
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(store.set_registration, project["identifier"], candidate["identifier"], True) for _ in range(8)]
            identifiers = {future.result()["loraPresetIdentifier"] for future in futures}
        assert len(identifiers) == 1
        preset = client.get("/api/loras/presets").json()[0]
        edited = {"name": "내가 수정한 조합", "workflow": preset["workflow"], "loras": [{**preset["loras"][0], "strength": 0.77}]}
        assert client.put(f"/api/loras/presets/{preset['preset_id']}", json=edited).status_code == 200
        assert client.put(candidate_registration_endpoint(project, candidate), json={"isRegistered": True}).json()["presetName"] == edited["name"]
        assert client.get("/api/loras/presets").json()[0]["style_source"]["modified"] is True
        copied = client.post("/api/loras/presets", json={**edited, "name": "일반 복사본"}).json()
        presets = {item["preset_id"]: item for item in client.get("/api/loras/presets").json()}
        assert presets[copied["preset_id"]]["style_source"] is None
        assert client.delete(f"/api/loras/presets/{preset['preset_id']}").status_code == 200
        results = client.get(f"/api/style-projects/{project['identifier']}/generation-results?summary=true").json()
        assert results["candidates"][0]["loraPresetIdentifier"] is None
        assert client.get("/api/loras/presets").json()[0]["preset_id"] == copied["preset_id"]
    finally:
        client.__exit__(None, None, None)


def test_retirement_and_candidate_deletion_keep_registered_snapshot(tmp_path):
    """퇴역·원본 폐기 뒤에도 CHS 등록본을 보관하고 사라진 원본 링크만 비활성화합니다."""

    application, client, project, payload = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan, _, _ = submit_and_wait(client, project, payload)
        candidate = plan["candidates"][0]
        endpoint = candidate_registration_endpoint(project, candidate)
        assert client.put(endpoint, json={"isRegistered": True}).status_code == 200
        original = client.get("/api/loras/presets").json()[0]
        with application.state.home_server.database._connect() as connection:
            connection.execute("UPDATE style_candidate_memberships SET lifecycle='retired' WHERE candidate_id=?", (candidate["identifier"],))
        assert client.get("/api/loras/presets").json()[0] == original
        deletion = client.post(f"/api/style-projects/{project['identifier']}/candidate-deletions", json=management_payload(client, project, [candidate["identifier"]]))
        assert deletion.status_code == 200, deletion.text
        remaining = client.get("/api/loras/presets").json()[0]
        assert remaining["loras"] == original["loras"]
        assert remaining["style_source"]["source_available"] is False
        assert client.delete(f"/api/loras/presets/{remaining['preset_id']}").status_code == 200
        with application.state.home_server.database._connect() as connection:
            assert connection.execute("SELECT count(*) FROM style_lora_preset_sources").fetchone()[0] == 0
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        client.__exit__(None, None, None)


def test_project_rename_updates_automatic_names_and_preserves_manual_names(tmp_path):
    """실제 출력 폴더 Rename과 같은 Transaction에서 전체 이름·출처를 갱신합니다."""

    _, client, project, payload = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan, _, _ = submit_and_wait(client, project, payload)
        for candidate in plan["candidates"]:
            assert client.put(candidate_registration_endpoint(project, candidate), json={"isRegistered": True}).status_code == 200
        presets = client.get("/api/loras/presets").json()
        manual = presets[0]
        assert client.put(f"/api/loras/presets/{manual['preset_id']}", json={"name": "수동 별칭", "workflow": manual["workflow"], "loras": manual["loras"]}).status_code == 200
        settings = copy.deepcopy(project["settings"])
        settings["name"] = "긴 프로젝트 이름을 유지하는 등록 이름 확인 " + "가" * 45
        response = client.put(f"/api/style-projects/{project['identifier']}", json={"settings": settings, "expectedRevision": project["revision"], "operationIdentifier": uuid.uuid4().hex})
        assert response.status_code == 200, response.text
        for preset in client.get("/api/loras/presets").json():
            assert preset["style_source"]["project_name"] == settings["name"]
            assert len(preset["name"]) <= 120
            if preset["preset_id"] == manual["preset_id"]:
                assert preset["name"] == "수동 별칭"
            else:
                assert settings["name"] in preset["name"]
    finally:
        client.__exit__(None, None, None)


def test_schema_nineteen_migration_preserves_all_original_rows_and_backup(tmp_path):
    """19→20은 기존 테이블을 수정하지 않고 검증한 Backup 뒤 출처 테이블만 추가합니다."""

    application, client, project, payload = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        submit_and_wait(client, project, payload)
        client.post("/api/loras/presets", json={"name": "일반 조합 보존", "workflow": "anima", "loras": [{"name": "example.safetensors", "strength": 0.5}]})
    finally:
        client.__exit__(None, None, None)
    database_path = application.state.home_server.database.database_path
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE style_lora_preset_sources")
        connection.execute("PRAGMA user_version=19")
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        before = {table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall() for table in tables}
    Database(database_path)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 20
        assert connection.execute("SELECT count(*) FROM style_lora_preset_sources").fetchone()[0] == 0
        for table in tables:
            assert connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall() == before[table]
    backups = list((database_path.parent / "backups").glob("*_before_style_lora_presets_*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 19
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
