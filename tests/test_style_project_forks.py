"""정적 세대 Snapshot·0세대 Fork·전적 출처·생성 데이터 격리를 검증합니다."""

import copy
import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from home_server.database import DATABASE_SCHEMA_VERSION, Database
from home_server.style_projects import snapshot_hash
from test_style_component_statistics import component_statistics
from test_style_evolution import prepare_evolution, rated_population, submit_existing_plan, wait_for_plan
from test_style_generation import StyleComfyClient, prepare_style_generation, submit_and_wait
from test_style_management import management_payload
from test_style_population_replenishment import confirmed_population
from test_style_voting import read_selection, undo_input, vote_input


@pytest.fixture
def forkable_project(tmp_path):
    """서로 다른 성분의 실제 대결과 불변 1세대 Snapshot이 있는 프로젝트를 만듭니다."""

    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan_input["combinations"] = [
            {"components": [{"identifier": "artist:example", "strength": 0.5}]},
            {"components": [{"identifier": "lora:example.safetensors", "strength": 0.7}]},
        ]
        _, _, results = submit_and_wait(client, project, plan_input)
        endpoint = f"/api/style-projects/{project['identifier']}"
        response = client.post(endpoint + "/votes", json=vote_input(read_selection(client, project)))
        assert response.status_code == 200, response.text
        selection = response.json()
        server = application.state.home_server
        with server.database._connect() as connection:
            row = connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()
            server.style_evolution.store.create_generation_checkpoint(connection, project["identifier"], project["evaluationIdentifier"], 1, json.loads(row[0]), "before-first-evolution")
        yield server, client, project, plan_input, results, selection
    finally:
        client.__exit__(None, None, None)


def fork_payload(client, project: dict, snapshot_identifier: str | None = None, name: str = "독립 Fork", include_statistics: bool = False) -> dict:
    """선택한 세대의 최신 Snapshot Revision과 통계 복사 옵션으로 명령을 만듭니다."""

    options = snapshot_options(client, project)
    snapshot_identifier = snapshot_identifier or options["currentSnapshotIdentifier"]
    selected = next((snapshot for snapshot in options["snapshots"] if snapshot["identifier"] == snapshot_identifier), None)
    return {"name": name, "expectedSnapshotRevision": selected["revision"] if selected else 1,
            "sourceSnapshotIdentifier": snapshot_identifier, "includeComponentStatistics": include_statistics, "operationIdentifier": uuid.uuid4().hex}


def snapshot_options(client, project: dict) -> dict:
    """실제 Fork Dialog가 사용하는 확정 세대 목록을 조회합니다."""

    response = client.get(f"/api/style-projects/{project['identifier']}/fork-options")
    assert response.status_code == 200, response.text
    return response.json()


def create_fork(client, project: dict, snapshot_identifier: str | None = None, name: str = "독립 Fork", include_statistics: bool = False) -> dict:
    """API로 새 프로젝트를 만들며 어떤 생성 요청도 직접 제출하지 않습니다."""

    response = client.post(f"/api/style-projects/{project['identifier']}/forks", json=fork_payload(client, project, snapshot_identifier, name, include_statistics))
    assert response.status_code == 201, response.text
    return response.json()


def assert_fork_has_no_generation_state(server, project: dict) -> None:
    """조합·이미지·Elo·Vote·CHS 작업 소유 관계가 원본에서 넘어오지 않았는지 확인합니다."""

    with server.database._connect() as connection:
        for table in ("style_candidates", "style_generation_plans", "style_job_ownership", "style_voting_arenas", "style_voting_commands", "style_evolution_batches"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project["identifier"],)).fetchone()[0] == 0, table
    assert project["candidateCount"] == 0
    assert project["generation"] == 0
    assert project["storageBinding"]["state"] == "not_created"


def test_initial_fork_copies_saved_settings_without_any_scores_or_history(forkable_project) -> None:
    """승패가 있는 원본도 0세대 Fork에서는 현재 저장 설정만 복사합니다."""

    server, client, source, _, _, _ = forkable_project
    settings = copy.deepcopy(source["settings"])
    settings["promptCases"][0]["prompt"] = "saved new prompt"
    settings["seed"] = 18446744073709551615
    settings["componentPolicies"]["lora:example.safetensors"].update(enabled=False, minimumStrength=0.55, maximumStrength=0.55)
    response = client.put(f"/api/style-projects/{source['identifier']}", json={"settings": settings, "operationIdentifier": uuid.uuid4().hex, "expectedRevision": source["revision"]})
    assert response.status_code == 200, response.text
    source = response.json()
    created = create_fork(client, source)
    expected_settings = {**source["settings"], "name": created["name"]}
    assert created["settings"] == expected_settings
    assert created["identifier"] != source["identifier"]
    assert created["evaluationIdentifier"] != source["evaluationIdentifier"]
    assert created["storageBinding"]["project_folder"] != source["storageBinding"]["project_folder"]
    assert created["forkSource"]["generationNumber"] == 1
    assert_fork_has_no_generation_state(server, created)
    statistics = component_statistics(client, created)["components"]
    assert all(value["matches"] == value["wins"] == value["score"] == value["inheritedMatches"] == 0 for value in statistics.values())


def test_confirmed_fork_copies_historical_settings_and_only_component_win_loss(forkable_project) -> None:
    """과거 세대는 이후 설정·점수 변경과 무관하며 가져온 전적을 새 관측과 분리합니다."""

    server, client, source, _, _, _ = forkable_project
    snapshot = snapshot_options(client, source)["snapshots"][0]
    expected_statistics = component_statistics(client, source)["components"]
    current_settings = copy.deepcopy(source["settings"])
    current_settings["componentPolicies"]["artist:example"]["enabled"] = False
    updated = client.put(f"/api/style-projects/{source['identifier']}", json={"settings": current_settings, "operationIdentifier": uuid.uuid4().hex, "expectedRevision": source["revision"]})
    assert updated.status_code == 200, updated.text
    created = create_fork(client, source, snapshot["identifier"], include_statistics=True)
    assert created["settings"] == {**current_settings, "name": created["name"]}
    assert created["forkSource"]["snapshotIdentifier"] == snapshot["identifier"]
    assert created["forkSource"]["generationNumber"] == 1
    assert_fork_has_no_generation_state(server, created)
    for identifier, statistics in component_statistics(client, created)["components"].items():
        assert statistics["wins"] == expected_statistics[identifier]["wins"]
        assert statistics["losses"] == expected_statistics[identifier]["losses"]
        assert statistics["inheritedMatches"] == expected_statistics[identifier]["matches"]
        assert statistics["localMatches"] == statistics["localScore"] == statistics["ratedCombinationCount"] == 0
        assert statistics["score"] == statistics["inheritedScore"] == expected_statistics[identifier]["score"]


def test_fork_generates_own_images_and_elo_then_adds_own_component_observations(forkable_project) -> None:
    """새 생성은 독립 경로·초기 Elo로 시작하고 새 전적을 원본에 역반영하지 않습니다."""

    server, client, source, source_plan_input, _, _ = forkable_project
    original_statistics = component_statistics(client, source)["components"]
    snapshot = snapshot_options(client, source)["snapshots"][0]
    created = create_fork(client, source, snapshot["identifier"], include_statistics=True)
    plan_input = copy.deepcopy(source_plan_input)
    plan_input.update(expectedRevision=created["revision"], operationIdentifier=uuid.uuid4().hex)
    _, _, results = submit_and_wait(client, created, plan_input)
    selection = read_selection(client, created)
    assert all(statistics["rating"] == 10000 and statistics["matches"] == 0 and not statistics["rated"] for statistics in selection["rankings"])
    for candidate in results["candidates"]:
        for render in candidate["renders"]:
            assert created["identifier"] in render["files"][0]["path"]
            assert source["identifier"] not in render["files"][0]["path"]
    assert client.post(f"/api/style-projects/{created['identifier']}/votes", json=vote_input(selection)).status_code == 200
    statistics = component_statistics(client, created)["components"]
    assert all(value["localMatches"] == 1 and value["inheritedMatches"] == 1 and value["matches"] == 2 for value in statistics.values())
    assert component_statistics(client, source)["components"] == original_statistics
    with server.database._connect() as connection:
        row = connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (created["evaluationIdentifier"],)).fetchone()
        server.style_evolution.store.create_generation_checkpoint(connection, created["identifier"], created["evaluationIdentifier"], 1, json.loads(row[0]), "before-first-evolution")
    nested = create_fork(client, created, snapshot_options(client, created)["snapshots"][0]["identifier"], "두 번째 Fork", include_statistics=True)
    nested_statistics = component_statistics(client, nested)["components"]
    assert all(value["inheritedMatches"] == 2 and value["localMatches"] == value["localScore"] == 0 for value in nested_statistics.values())
    assert all(value["score"] == statistics[identifier]["score"] for identifier, value in nested_statistics.items())


def test_snapshot_and_fork_survive_original_image_deletion_and_snapshot_unlink(forkable_project) -> None:
    """원본 이미지·전적 정리와 Snapshot 제거가 이미 Fork한 설정·승패를 바꾸지 않습니다."""

    server, client, source, _, results, _ = forkable_project
    snapshot = snapshot_options(client, source)["snapshots"][0]
    created = create_fork(client, source, snapshot["identifier"], include_statistics=True)
    before = component_statistics(client, created)["components"]
    identifiers = [candidate["identifier"] for candidate in results["candidates"]]
    deleted = client.post(f"/api/style-projects/{source['identifier']}/candidate-deletions", json=management_payload(client, source, identifiers))
    assert deleted.status_code == 200, deleted.text
    assert sum(value["matches"] for value in component_statistics(client, source)["components"].values()) == 0
    after_deletion = create_fork(client, source, snapshot["identifier"], "삭제 이후 Fork", include_statistics=True)
    assert component_statistics(client, after_deletion)["components"] == before
    with server.database._connect() as connection:
        connection.execute("DELETE FROM style_project_generation_snapshots WHERE snapshot_id=?", (snapshot["identifier"],))
    assert component_statistics(client, created)["components"] == before
    assert client.get(f"/api/style-projects/{created['identifier']}").json()["forkSource"]["generationNumber"] == 1


def test_fork_commands_are_idempotent_and_concurrent_safe(forkable_project) -> None:
    """같은 Operation ID를 동시에 보내도 새 프로젝트 하나만 만들고 다른 내용은 거부합니다."""

    server, client, source, _, _, _ = forkable_project
    endpoint = f"/api/style-projects/{source['identifier']}/forks"
    payload = fork_payload(client, source)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: client.post(endpoint, json=payload), range(2)))
    assert all(response.status_code == 201 for response in responses)
    assert responses[0].json()["identifier"] == responses[1].json()["identifier"]
    assert client.post(endpoint, json=payload).json() == responses[0].json()
    assert client.post(endpoint, json={**payload, "name": "다른 내용"}).status_code == 409
    with server.database._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM style_project_forks WHERE operation_id=?", (payload["operationIdentifier"],)).fetchone()[0] == 1


def test_invalid_fork_scope_revision_name_and_snapshot_do_not_create_projects(forkable_project) -> None:
    """소유가 다른 Snapshot·오래된 설정·손상·잘못된 이름을 전체 거부합니다."""

    server, client, source, _, _, _ = forkable_project
    endpoint = f"/api/style-projects/{source['identifier']}/forks"
    snapshot = snapshot_options(client, source)["snapshots"][0]
    stale_payload = fork_payload(client, source)
    stale_payload["expectedSnapshotRevision"] += 1
    assert client.post(endpoint, json=stale_payload).status_code == 409
    for invalid_name in ("", " ", "bad/name", "CON"):
        assert client.post(endpoint, json=fork_payload(client, source, name=invalid_name)).status_code == 422
    assert client.post(endpoint, json=fork_payload(client, source, "missing-snapshot")).status_code == 404
    foreign = create_fork(client, source)
    assert client.post(f"/api/style-projects/{foreign['identifier']}/forks", json=fork_payload(client, foreign, snapshot["identifier"])).status_code == 404
    before_count = len(client.get("/api/style-projects").json()["projects"])
    with server.database._connect() as connection:
        connection.execute("UPDATE style_project_generation_snapshots SET snapshot_json='{}' WHERE snapshot_id=?", (snapshot["identifier"],))
    corrupt_payload = {**stale_payload, "expectedSnapshotRevision": snapshot["revision"]}
    assert client.post(endpoint, json=corrupt_payload).status_code == 409
    assert len(client.get("/api/style-projects").json()["projects"]) == before_count


def test_fork_write_failure_rolls_back_new_project(forkable_project) -> None:
    """출처·승패 저장 실패 시 빈 프로젝트나 평가 조건도 남기지 않습니다."""

    server, client, source, _, _, _ = forkable_project
    before = client.get("/api/style-projects").json()
    with server.database._connect() as connection:
        connection.execute("CREATE TRIGGER refuse_project_fork BEFORE INSERT ON style_project_forks BEGIN SELECT RAISE(ABORT,'fixture fork failure'); END")
    response = client.post(f"/api/style-projects/{source['identifier']}/forks", json=fork_payload(client, source))
    assert response.status_code == 409, response.text
    assert client.get("/api/style-projects").json() == before


def test_confirmed_generations_automatically_capture_static_snapshots(confirmed_population) -> None:
    """실제 세대 확정과 같은 Transaction에서 정적 Snapshot을 기록합니다."""

    server, client, source, _ = confirmed_population
    options = snapshot_options(client, source)
    assert [snapshot["generationNumber"] for snapshot in options["snapshots"]] == [2, 1, 0]
    with server.database._connect() as connection:
        rows = connection.execute("SELECT snapshot_json,snapshot_hash FROM style_project_generation_snapshots WHERE project_id=?", (source["identifier"],)).fetchall()
    for row in rows:
        document = json.loads(row["snapshot_json"])
        assert set(document) == {"format", "settings", "componentStatistics", "workflow"}
        assert set(document["workflow"]) == {"identifier", "modelIdentifier", "apiHash", "uiHash"}
        assert all(set(value) == {"wins", "losses", "matches", "score"} for value in document["componentStatistics"].values())
        assert snapshot_hash(document) == row["snapshot_hash"]


def test_backfill_uses_undo_state_at_checkpoint_and_migration_preserves_existing_data(forkable_project) -> None:
    """Checkpoint 이후 Undo를 과거에 소급하지 않고 20→21의 기존 업무 데이터를 유지합니다."""

    server, client, source, _, _, selection = forkable_project
    snapshot_identifier = snapshot_options(client, source)["snapshots"][0]["identifier"]
    with server.database._connect() as connection:
        original_document = json.loads(connection.execute("SELECT snapshot_json FROM style_project_generation_snapshots WHERE snapshot_id=?", (snapshot_identifier,)).fetchone()[0])
    undo = client.post(f"/api/style-projects/{source['identifier']}/undo", json=undo_input(selection))
    assert undo.status_code == 200, undo.text
    with server.database._connect() as connection:
        source_rows = [tuple(row) for row in connection.execute("SELECT * FROM style_projects ORDER BY project_id")]
        connection.execute("UPDATE style_evolution_timelines SET generation_number=2 WHERE evaluation_id=?", (source["evaluationIdentifier"],))
        connection.execute("DROP TABLE style_project_forks")
        connection.execute("DROP TABLE style_project_generation_snapshots")
        connection.execute("PRAGMA user_version=20")
    migrated = Database(server.database.database_path)
    with migrated._connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == DATABASE_SCHEMA_VERSION
        assert [tuple(row) for row in connection.execute("SELECT * FROM style_projects ORDER BY project_id")] == source_rows
        row = connection.execute("SELECT snapshot_json FROM style_project_generation_snapshots WHERE project_id=? AND generation_number=1", (source["identifier"],)).fetchone()
        assert json.loads(row[0]) == original_document
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    backups = list((server.database.database_path.parent / "backups").glob("*_before_style_project_forks_*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 20


def test_open_evolution_is_not_a_fork_option_but_does_not_block_settings_copy(rated_population) -> None:
    """진행 중 후보·선별은 복사하지 않고 직전 안정 세대와 0세대만 제공합니다."""

    server, _, client, source, _ = rated_population
    plan = prepare_evolution(client, source, 1)
    assert plan["generationNumber"] == 2
    submit_existing_plan(client, source, plan)
    wait_for_plan(client, source, plan)
    options = snapshot_options(client, source)
    assert [snapshot["generationNumber"] for snapshot in options["snapshots"]] == [1, 0]
    created = create_fork(client, source)
    assert_fork_has_no_generation_state(server, created)


def save_source_settings(client, source: dict, settings: dict) -> dict:
    """실제 설정 저장 API로 Snapshot과 프로젝트 Revision을 함께 갱신합니다."""

    response = client.put(f"/api/style-projects/{source['identifier']}", json={
        "settings": settings, "expectedRevision": source["revision"], "operationIdentifier": uuid.uuid4().hex,
    })
    assert response.status_code == 200, response.text
    return response.json()


def read_snapshot_document(server, snapshot_identifier: str) -> dict:
    """Fork 전용 문서를 읽어 이미지가 없는 정적 설정의 변경 범위를 비교합니다."""

    with server.database._connect() as connection:
        row = connection.execute("SELECT snapshot_json FROM style_project_generation_snapshots WHERE snapshot_id=?", (snapshot_identifier,)).fetchone()
    return json.loads(row[0])


def test_generation_zero_snapshot_tracks_settings_and_rejects_stale_forks(tmp_path) -> None:
    """이미지 없이도 0세대 설정을 갱신하고 오래된 Dialog의 Fork는 거부합니다."""

    application, client, source, _ = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        server = application.state.home_server
        assert source["generation"] == 0
        original_snapshot = snapshot_options(client, source)["snapshots"][0]
        stale_payload = fork_payload(client, source)
        settings = copy.deepcopy(source["settings"])
        settings["componentPolicies"]["artist:example"].update(enabled=False, minimumStrength=0.35, maximumStrength=0.75)
        settings["componentPolicies"]["lora:example.safetensors"].update(minimumStrength=0.65, maximumStrength=0.65)
        settings["promptCases"][0]["name"] = "새 이름"
        settings["promptCases"][0]["prompt"] = "new zero generation prompt"
        updated = save_source_settings(client, source, settings)
        assert updated["generation"] == 0
        assert updated["evaluationIdentifier"] != source["evaluationIdentifier"]
        snapshots = snapshot_options(client, source)["snapshots"]
        assert len(snapshots) == 1
        assert snapshots[0]["identifier"] == original_snapshot["identifier"]
        assert snapshots[0]["revision"] == original_snapshot["revision"] + 1
        assert client.post(f"/api/style-projects/{source['identifier']}/forks", json=stale_payload).status_code == 409
        created = create_fork(client, updated)
        assert created["forkSource"]["generationNumber"] == 0
        assert created["settings"] == {**updated["settings"], "name": created["name"]}
        assert_fork_has_no_generation_state(server, created)
        unchanged = save_source_settings(client, updated, updated["settings"])
        assert snapshot_options(client, unchanged)["snapshots"][0]["revision"] == snapshots[0]["revision"]
    finally:
        client.__exit__(None, None, None)


def test_current_generation_settings_updates_preserve_all_older_generations(confirmed_population) -> None:
    """세대가 바뀐 뒤 Prompt·사용 여부·STR 변경은 현재 세대 문서만 갱신합니다."""

    server, client, source, _ = confirmed_population
    before = snapshot_options(client, source)["snapshots"]
    historical_documents = {snapshot["identifier"]: read_snapshot_document(server, snapshot["identifier"]) for snapshot in before[1:]}
    settings = copy.deepcopy(source["settings"])
    settings["name"] = "이름도 바꾼 현재 프로젝트"
    settings["componentPolicies"]["artist:example"].update(enabled=False, minimumStrength=0.45, maximumStrength=0.9)
    updated = save_source_settings(client, source, settings)
    settings = copy.deepcopy(updated["settings"])
    settings["promptCases"][0]["prompt"] = "new generation two prompt"
    updated = save_source_settings(client, updated, settings)
    after = snapshot_options(client, updated)["snapshots"]
    assert [snapshot["generationNumber"] for snapshot in after] == [2, 1, 0]
    assert after[0]["identifier"] == before[0]["identifier"]
    assert after[0]["revision"] == before[0]["revision"] + 2
    assert after[0]["evaluationIdentifier"] == updated["evaluationIdentifier"]
    for identifier, document in historical_documents.items():
        assert read_snapshot_document(server, identifier) == document
    created = create_fork(client, updated, after[1]["identifier"])
    assert created["forkSource"]["generationNumber"] == 1
    assert created["settings"] == {**historical_documents[after[1]["identifier"]]["settings"], "name": created["name"]}
    assert_fork_has_no_generation_state(server, created)


def test_inherited_component_scores_reach_evolution_without_copying_style_elo(rated_population) -> None:
    """±Score는 이후 추첨에 반영하되 새 조합 Elo와 전적은 초기값으로 시작합니다."""

    server, _, client, source, _ = rated_population
    source = save_source_settings(client, source, source["settings"])
    source_scores = {identifier: value["score"] for identifier, value in component_statistics(client, source)["components"].items()}
    assert any(source_scores.values())
    created = create_fork(client, source, include_statistics=True)
    response = client.post(f"/api/style-projects/{created['identifier']}/random-generation-plans", json={
        "expectedRevision": created["revision"], "operationIdentifier": uuid.uuid4().hex, "combinationCount": 10,
    })
    assert response.status_code == 201, response.text
    initial_plan = response.json()
    submit_existing_plan(client, created, initial_plan)
    results = wait_for_plan(client, created, initial_plan)
    selection = read_selection(client, created)
    assert all(value["rating"] == 10000 and value["matches"] == 0 for value in selection["rankings"])
    with server.database._connect() as connection:
        row = connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (created["evaluationIdentifier"],)).fetchone()
        arena = json.loads(row[0])
        for candidate in results["candidates"]:
            arena["statistics"][candidate["identifier"]].update(rating=10000, matches=3, wins=1, placed=True)
        arena.update(match=None, placement=None)
        connection.execute("UPDATE style_voting_arenas SET state_json=?,revision=revision+1 WHERE evaluation_id=?", (json.dumps(arena), created["evaluationIdentifier"]))
    displayed = component_statistics(client, created)["components"]
    plan = prepare_evolution(client, created, 1)
    provenance = plan["selection"]
    assert provenance["componentPriorScores"] == source_scores
    assert provenance["componentScores"] == {identifier: value["score"] for identifier, value in displayed.items()}
    assert provenance["componentPreferenceMultipliers"] == {identifier: value["selectionMultiplier"] for identifier, value in displayed.items()}


def test_failed_snapshot_save_rolls_back_project_settings(forkable_project) -> None:
    """Snapshot만 저장되지 않는 불완전한 설정 변경을 Transaction 단위로 되돌립니다."""

    server, client, source, _, _, _ = forkable_project
    endpoint = f"/api/style-projects/{source['identifier']}"
    before = client.get(endpoint).json()
    settings = copy.deepcopy(before["settings"])
    settings["componentPolicies"]["artist:example"]["minimumStrength"] = 0.3
    with server.database._connect() as connection:
        connection.execute("CREATE TRIGGER refuse_settings_snapshot BEFORE UPDATE ON style_project_generation_snapshots BEGIN SELECT RAISE(ABORT,'fixture snapshot failure'); END")
    response = client.put(endpoint, json={"settings": settings, "expectedRevision": before["revision"], "operationIdentifier": uuid.uuid4().hex})
    assert response.status_code == 409, response.text
    assert client.get(endpoint).json() == before


def test_fork_endpoints_require_existing_home_authentication(forkable_project) -> None:
    """Snapshot 열람과 Fork 생성은 Home의 로그인 보호를 그대로 사용합니다."""

    _, client, source, _, _, _ = forkable_project
    payload = fork_payload(client, source)
    client.cookies.clear()
    assert client.get(f"/api/style-projects/{source['identifier']}/fork-options").status_code == 401
    assert client.post(f"/api/style-projects/{source['identifier']}/forks", json=payload).status_code == 401
