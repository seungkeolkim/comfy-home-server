"""그림체 좋아요의 영속성·프로젝트 경계·삭제와 18→19 Migration을 검증합니다."""

import sqlite3
import uuid

from home_server.database import DATABASE_SCHEMA_VERSION, Database
from test_style_generation import StyleComfyClient, prepare_style_generation, submit_and_wait
from test_style_management import management_payload
from test_style_voting import read_selection, vote_input


def favorite_independent_rows(database_path):
    """좋아요가 변경해서는 안 되는 생성·프로젝트·투표·일반 즐겨찾기 행을 읽습니다."""
    with sqlite3.connect(database_path) as connection:
        return {
            table_name: connection.execute(f"SELECT * FROM {table_name} ORDER BY rowid").fetchall()
            for table_name in ("style_projects", "style_candidates", "style_generation_plans", "style_voting_arenas", "style_vote_events", "request_favorites")
        }


def test_favorites_are_idempotent_persistent_and_independent_from_votes(tmp_path):
    """좋아요는 재시도·다른 Session에 유지되고 기존 Elo·Undo와 생성 상태를 바꾸지 않습니다."""
    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan, _, _ = submit_and_wait(client, project, plan_input)
        endpoint = f"/api/style-projects/{project['identifier']}"
        candidate_identifier = plan["candidates"][0]["identifier"]
        favorite_endpoint = f"{endpoint}/candidates/{candidate_identifier}/favorite"
        vote = client.post(endpoint + "/votes", json=vote_input(read_selection(client, project)))
        assert vote.status_code == 200, vote.text
        database_path = application.state.home_server.database.database_path
        before = favorite_independent_rows(database_path)
        for _ in range(2):
            response = client.put(favorite_endpoint, json={"isFavorite": True})
            assert response.status_code == 200, response.text
            assert response.json() == {"candidateIdentifier": candidate_identifier, "isFavorite": True}
        results = client.get(endpoint + "/generation-results?summary=true").json()
        assert {candidate["identifier"]: candidate["isFavorite"] for candidate in results["candidates"]} == {
            candidate["identifier"]: candidate["identifier"] == candidate_identifier for candidate in plan["candidates"]
        }
        assert favorite_independent_rows(database_path) == before
        client.cookies.clear()
        assert client.put(favorite_endpoint, json={"isFavorite": False}).status_code == 401
        assert client.post("/api/login", json={"password": "test"}).status_code == 200
        restored = client.get(endpoint + "/generation-results").json()
        assert restored["candidates"][0]["isFavorite"] is True
        for _ in range(2):
            assert client.put(favorite_endpoint, json={"isFavorite": False}).status_code == 200
        assert client.get(endpoint + "/generation-results?summary=true").json()["candidates"][0]["isFavorite"] is False
        assert favorite_independent_rows(database_path) == before
    finally:
        client.__exit__(None, None, None)


def test_favorite_requires_generated_candidate_owned_by_project_and_strict_boolean(tmp_path):
    """미제출·다른 프로젝트·없는 조합과 모호한 문자열 Bool은 저장하지 않습니다."""
    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        endpoint = f"/api/style-projects/{project['identifier']}"
        preview = client.post(endpoint + "/generation-plans", json=plan_input).json()
        identifier = preview["candidates"][0]["identifier"]
        favorite_endpoint = f"{endpoint}/candidates/{identifier}/favorite"
        assert client.put(favorite_endpoint, json={"isFavorite": True}).status_code == 404
        submit_and_wait(client, project, plan_input)
        other = client.post("/api/style-projects", json={"operationIdentifier": uuid.uuid4().hex, "settings": {**project["settings"], "name": "다른 프로젝트"}}).json()
        assert client.put(f"/api/style-projects/{other['identifier']}/candidates/{identifier}/favorite", json={"isFavorite": True}).status_code == 404
        assert client.put(f"{endpoint}/candidates/missing/favorite", json={"isFavorite": True}).status_code == 404
        for invalid_payload in ({"isFavorite": "false"}, {"isFavorite": 1}, {}, {"isFavorite": True, "rating": 0}):
            assert client.put(favorite_endpoint, json=invalid_payload).status_code == 422
        with application.state.home_server.database._connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM style_candidate_favorites").fetchone()[0] == 0
    finally:
        client.__exit__(None, None, None)


def test_retirement_keeps_favorite_and_candidate_deletion_removes_it(tmp_path):
    """퇴역 뒤에도 좋아요는 남고 조합 전체 폐기·재시도 뒤에는 DB에서도 사라집니다."""
    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        plan, _, _ = submit_and_wait(client, project, plan_input)
        endpoint = f"/api/style-projects/{project['identifier']}"
        identifier = plan["candidates"][0]["identifier"]
        favorite_endpoint = f"{endpoint}/candidates/{identifier}/favorite"
        assert client.put(favorite_endpoint, json={"isFavorite": True}).status_code == 200
        with application.state.home_server.database._connect() as connection:
            connection.execute("UPDATE style_candidate_memberships SET lifecycle='retired' WHERE candidate_id=?", (identifier,))
        retired = client.get(endpoint + "/generation-results?summary=true").json()["candidates"][0]
        assert retired["lifecycle"] == "retired" and retired["isFavorite"] is True
        payload = management_payload(client, project, [identifier])
        for _ in range(2):
            response = client.post(endpoint + "/candidate-deletions", json=payload)
            assert response.status_code == 200, response.text
        assert client.put(favorite_endpoint, json={"isFavorite": True}).status_code == 404
        remaining = client.get(endpoint + "/generation-results?summary=true").json()["candidates"]
        assert all(candidate["identifier"] != identifier for candidate in remaining)
        with application.state.home_server.database._connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM style_candidate_favorites").fetchone()[0] == 0
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        client.__exit__(None, None, None)


def test_schema_eighteen_migration_preserves_data_and_creates_verified_backup(tmp_path):
    """18→19은 원본 Backup을 만들고 기존 그림체·Job·Elo를 그대로 보존합니다."""
    application, client, project, plan_input = prepare_style_generation(tmp_path, StyleComfyClient())
    try:
        submit_and_wait(client, project, plan_input)
        read_selection(client, project)
    finally:
        client.__exit__(None, None, None)
    database_path = application.state.home_server.database.database_path
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE style_candidate_favorites")
        connection.execute("PRAGMA user_version=18")
        table_names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        before = {table_name: connection.execute(f"SELECT * FROM {table_name} ORDER BY rowid").fetchall() for table_name in table_names}
    Database(database_path)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == DATABASE_SCHEMA_VERSION
        assert connection.execute("SELECT COUNT(*) FROM style_candidate_favorites").fetchone()[0] == 0
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        for table_name in table_names:
            assert connection.execute(f"SELECT * FROM {table_name} ORDER BY rowid").fetchall() == before[table_name]
    backups = list((database_path.parent / "backups").glob(f"{database_path.stem}_before_style_candidate_favorites_*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 18
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='style_candidate_favorites'").fetchone() is None
