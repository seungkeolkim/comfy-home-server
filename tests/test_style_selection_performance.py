"""선별의 Read/Write 분리와 누적 이미지 Hash 재사용을 실제 SQLite에서 검증합니다."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import patch

import pytest

from home_server.style_checkpoint_files import StyleCheckpointFileStore
from home_server.database import Database
from home_server.style_evolution_store import StyleEvolutionStore
from home_server.style_voting_rules import league_match_weights
from test_style_evolution import evolution_view, prepare_evolution, rated_population
from test_style_voting import read_selection


def test_steady_selection_and_evolution_do_not_acquire_writer_slot(rated_population) -> None:
    """다른 Writer가 예약 잠금을 유지해도 기존 선별·진화 조회는 완료됩니다."""

    server, _, client, project, _ = rated_population
    selection = read_selection(client, project)
    evolution_view(client, project)
    with closing(server.database._connect()) as writer_connection:
        writer_connection.execute("BEGIN IMMEDIATE")
        with ThreadPoolExecutor(max_workers=2) as executor:
            selection_future = executor.submit(server.style_voting.read, project["identifier"], project["evaluationIdentifier"], "performance-test-browser")
            evolution_future = executor.submit(server.style_evolution.read_evolution, project["identifier"], project["evaluationIdentifier"])
            try:
                next_selection = selection_future.result(timeout=3)
                next_evolution = evolution_future.result(timeout=3)
            finally:
                writer_connection.rollback()
        assert next_selection["revision"] == selection["revision"]
        assert next_selection["match"] == selection["match"]
        assert next_evolution["votingRevision"] == selection["revision"]


def test_steady_reads_use_read_transactions_and_checkpoint_covering_index(rated_population) -> None:
    """변경 없는 Polling은 쓰기를 하지 않으며 목록은 큰 Snapshot을 읽지 않습니다."""

    server, _, client, project, _ = rated_population
    read_selection(client, project)
    evolution_view(client, project)
    statements = []
    original_connection_factory = server.database._connect

    def traced_connection():
        """검증 대상 요청의 SQL만 기록합니다."""

        connection = original_connection_factory()
        connection.set_trace_callback(statements.append)
        return connection

    with patch.object(server.database, "_connect", traced_connection):
        read_selection(client, project)
        evolution_view(client, project)
    assert "BEGIN" in statements
    assert not any(statement.startswith(("BEGIN IMMEDIATE", "INSERT", "UPDATE", "DELETE")) for statement in statements)
    with closing(original_connection_factory()) as connection:
        query_plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT generation_number,created_at FROM style_generation_checkpoints WHERE evaluation_id=? ORDER BY generation_number",
            (project["evaluationIdentifier"],),
        ).fetchall()
    assert any("COVERING INDEX style_checkpoint_listing" in row[3] for row in query_plan)


def test_evolution_batch_view_keeps_plan_in_same_read_snapshot(rated_population) -> None:
    """진화 진행 중 계획 조회가 별도 연결을 열어 Writer의 Commit과 교착하지 않습니다."""

    server, _, client, project, _ = rated_population
    plan = prepare_evolution(client, project)
    original_database_connection_factory = server.database._connect
    original_plan_connection_factory = server.style_generation.store.connection_factory
    with patch.object(server.database, "_connect", wraps=original_database_connection_factory) as database_connections:
        with patch.object(server.style_generation.store, "connection_factory", wraps=original_plan_connection_factory) as plan_connections:
            evolution = evolution_view(client, project)
    assert evolution["batch"]["plan"]["planIdentifier"] == plan["planIdentifier"]
    assert database_connections.call_count == 1
    assert plan_connections.call_count == 0


def test_checkpoint_hashes_survive_store_restart_and_detect_changed_or_missing_files(rated_population) -> None:
    """새 세대에는 기존 Hash를 재사용하되 변경 파일은 재계산하고 유실은 숨기지 않습니다."""

    server, _, client, project, plan = rated_population
    read_selection(client, project)
    with closing(server.database._connect()) as connection:
        state = json.loads(connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()[0])
    store = server.style_evolution.store
    with patch.object(StyleCheckpointFileStore, "calculate_file_hash", wraps=StyleCheckpointFileStore.calculate_file_hash) as calculate_hash:
        with closing(server.database._connect()) as connection, connection:
            first_checkpoint = store.create_generation_checkpoint(connection, project["identifier"], project["evaluationIdentifier"], 1, state, "performance-test")
        assert calculate_hash.call_count == len(plan["candidates"]) * len(plan["cases"])
        calculate_hash.reset_mock()
        restarted_store = StyleEvolutionStore(server)
        with closing(server.database._connect()) as connection, connection:
            second_checkpoint = restarted_store.create_generation_checkpoint(connection, project["identifier"], project["evaluationIdentifier"], 2, state, "performance-test")
        assert calculate_hash.call_count == 0
        with closing(server.database._connect()) as connection:
            first_snapshot = json.loads(connection.execute("SELECT snapshot_json FROM style_generation_checkpoints WHERE checkpoint_id=?", (first_checkpoint,)).fetchone()[0])
            second_snapshot = json.loads(connection.execute("SELECT snapshot_json FROM style_generation_checkpoints WHERE checkpoint_id=?", (second_checkpoint,)).fetchone()[0])
        assert first_snapshot["assets"] == second_snapshot["assets"]
        changed_asset, missing_asset = first_snapshot["assets"][:2]
        changed_path = server.managed_path(changed_asset["relative_path"])
        changed_bytes = changed_path.read_bytes() + b"changed-after-checkpoint"
        changed_path.write_bytes(changed_bytes)
        server.managed_path(missing_asset["relative_path"]).unlink()
        with closing(server.database._connect()) as connection, connection:
            changed_checkpoint = restarted_store.create_generation_checkpoint(connection, project["identifier"], project["evaluationIdentifier"], 3, state, "performance-test")
        assert calculate_hash.call_count == 1
        with closing(server.database._connect()) as connection:
            changed_snapshot = json.loads(connection.execute("SELECT snapshot_json FROM style_generation_checkpoints WHERE checkpoint_id=?", (changed_checkpoint,)).fetchone()[0])
        assets_by_identifier = {asset["output_id"]: asset for asset in changed_snapshot["assets"]}
        assert assets_by_identifier[changed_asset["output_id"]]["sha256"] == hashlib.sha256(changed_bytes).hexdigest()
        assert assets_by_identifier[missing_asset["output_id"]]["missingFile"] is True
        assert "sha256" not in assets_by_identifier[missing_asset["output_id"]]


def test_checkpoint_rejects_file_changed_while_hashing_and_rolls_back(rated_population) -> None:
    """Hash 도중 원본이 바뀌면 불완전한 Manifest와 Cache를 함께 Rollback합니다."""

    server, _, client, project, _ = rated_population
    read_selection(client, project)
    original_hash_function = StyleCheckpointFileStore.calculate_file_hash

    def hash_then_change_image(image_path) -> str:
        """실제 Hash 이후 파일을 바꿔 저장 중 외부 편집을 재현합니다."""

        digest = original_hash_function(image_path)
        image_path.write_bytes(image_path.read_bytes() + b"modified-during-hash")
        return digest

    with patch.object(StyleCheckpointFileStore, "calculate_file_hash", side_effect=hash_then_change_image):
        with pytest.raises(ValueError, match="이미지 파일이 변경"):
            with closing(server.database._connect()) as connection, connection:
                state = json.loads(connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()[0])
                server.style_evolution.store.create_generation_checkpoint(connection, project["identifier"], project["evaluationIdentifier"], 1, state, "performance-test")
    with closing(server.database._connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM style_generation_checkpoints").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM style_checkpoint_file_hashes").fetchone()[0] == 0


def test_league_weights_preserve_tied_rating_percentiles() -> None:
    """같은 Rating의 공동 순위와 미확정 후보의 가중치는 기존 정의와 일치합니다."""

    identifiers = [f"candidate-{index}" for index in range(100)]
    statistics = {identifier: {"rating": 10000 + index // 7, "matches": index % 13} for index, identifier in enumerate(identifiers)}
    expected_weights = []
    for identifier in identifiers:
        candidate = statistics[identifier]
        weight = 1 / (candidate["matches"] + 1)
        if candidate["matches"] >= 10:
            percentile = sum(other["rating"] >= candidate["rating"] for other in statistics.values()) / len(statistics)
            weight *= next(multiplier for boundary, multiplier in ((0.1, 1.0), (0.3, 0.9), (0.7, 0.6), (0.9, 0.3), (1.0, 0.1)) if percentile <= boundary)
        expected_weights.append(weight)
    assert league_match_weights({"statistics": statistics}, identifiers, identifiers) == expected_weights


def test_schema_21_upgrade_preserves_existing_arena_and_checkpoints(rated_population) -> None:
    """기존 DB를 올려도 평가 상태·후보·불변 Snapshot 본문은 변경되지 않습니다."""

    server, _, client, project, _ = rated_population
    selection = read_selection(client, project)
    with closing(server.database._connect()) as connection, connection:
        state_json = connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()[0]
        server.style_evolution.store.create_generation_checkpoint(connection, project["identifier"], project["evaluationIdentifier"], 1, json.loads(state_json), "migration-test")
        original_checkpoints = [tuple(row) for row in connection.execute("SELECT * FROM style_generation_checkpoints")]
        connection.execute("DROP TABLE style_checkpoint_file_hashes")
        for index_name in ("style_checkpoint_listing", "style_candidates_evaluation", "style_voting_pending_deletions", "style_votes_evaluation", "style_evolution_evaluation"):
            connection.execute("DROP INDEX " + index_name)
        connection.execute("PRAGMA user_version=21")
    upgraded_database = Database(server.database.database_path)
    with closing(upgraded_database._connect()) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 22
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert [tuple(row) for row in connection.execute("SELECT * FROM style_generation_checkpoints")] == original_checkpoints
        assert connection.execute("SELECT state_json FROM style_voting_arenas WHERE evaluation_id=?", (project["evaluationIdentifier"],)).fetchone()[0] == state_json
        assert connection.execute("SELECT COUNT(*) FROM style_checkpoint_file_hashes").fetchone()[0] == 0
    assert read_selection(client, project)["revision"] == selection["revision"]
