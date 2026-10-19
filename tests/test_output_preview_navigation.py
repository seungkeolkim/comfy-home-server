"""미리보기의 페이지 경계·NULL/Seed 정렬·작업/요청 범위와 현재 경로를 검증합니다."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_server.database import Database
from home_server.output_catalog import OutputCatalog
from test_application import FakeComfyClient, create_processing_test_app
from test_output_catalog import add_catalog_test_request


@pytest.mark.parametrize("filter_kind", ["all", "job", "request", "prefix"])
def test_preview_neighbors_follow_listing_order_across_pages_and_null_values(tmp_path: Path, filter_kind: str) -> None:
    """목록과 동일한 양방향 순서를 유지하며 64장 경계·동률·NULL·큰 Seed를 처리합니다."""

    database = Database(tmp_path / "navigation.sqlite3")
    first_request = add_catalog_test_request(database, "first-job")
    second_request = add_catalog_test_request(database, "second-job")
    first_paths = [f"selected/261015_090102_{seed}.png" for seed in range(70)]
    first_paths.extend(["selected/261015_090102_18446744073709551615.mp4", "selected/plain.png", "selected/another.png"])
    database.complete_request(first_request, first_paths)
    database.complete_request(second_request, ["other/261015_090102_50.png", "other/unknown.webm"])
    catalog = OutputCatalog(database.database_path)
    with sqlite3.connect(database.database_path) as connection:
        connection.execute("UPDATE output_files SET seed=NULL WHERE relative_path LIKE '%another.png'")
        connection.execute("UPDATE output_files SET generated_at=NULL WHERE relative_path='selected/261015_090102_2.png'")
        connection.execute("UPDATE output_files SET is_deleted=1 WHERE relative_path='selected/261015_090102_3.png'")
        connection.execute("UPDATE output_files SET is_available=0 WHERE relative_path='selected/261015_090102_4.png'")
    filters = {}
    if filter_kind == "job":
        filters["job_id"] = "first-job"
    elif filter_kind == "request":
        filters["request_id"] = first_request
    elif filter_kind == "prefix":
        filters["prefix"] = "selected/"
    listing = catalog.list_files(1, 100, **filters)["files"]
    for file_index, output_file in enumerate(listing):
        neighbors = catalog.get_file_neighbors(output_file["output_id"], **filters)
        assert neighbors["current"] == {key: output_file[key] for key in ("output_id", "path", "name", "kind", "deletion_protected")}
        expected_previous = listing[file_index - 1] if file_index > 0 else None
        expected_next = listing[file_index + 1] if file_index + 1 < len(listing) else None
        for direction, expected_file in (("previous", expected_previous), ("next", expected_next)):
            if expected_file is None:
                assert neighbors[direction] is None
            else:
                assert neighbors[direction] == {key: expected_file[key] for key in ("output_id", "path", "name", "kind")}
    page_boundary = catalog.list_files(1, 64, **filters)["files"][-1]
    assert catalog.get_file_neighbors(page_boundary["output_id"], **filters)["next"]["output_id"] == listing[64]["output_id"]


def test_preview_navigation_api_preserves_source_scope_and_rejects_removed_sources(tmp_path: Path) -> None:
    """원본 작업/요청 밖으로 이동하지 않으며 이동된 경로·삭제 상태·인증을 재검증합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    first_request = add_catalog_test_request(server.database, "first-job")
    second_request = add_catalog_test_request(server.database, "second-job")
    server.database.complete_request(first_request, ["source/a.png", "source/b.mp4"])
    server.database.complete_request(second_request, ["other/c.png"])
    with sqlite3.connect(server.database.database_path) as connection:
        output_ids = dict(connection.execute("SELECT relative_path,output_id FROM output_files"))
        connection.execute("UPDATE output_files SET relative_path='moved/b.mp4' WHERE relative_path='source/b.mp4'")
    image_identifier = output_ids["source/a.png"]
    video_identifier = output_ids["source/b.mp4"]
    with TestClient(application) as client:
        endpoint = f"/api/outputs/{image_identifier}/neighbors"
        assert client.get(endpoint).status_code == 401
        client.post("/api/login", json={"password": "test"})
        response = client.get(endpoint, params={"job_id": "first-job"})
        assert response.status_code == 200
        neighbors = response.json()
        assert neighbors["next"]["path"] == "moved/b.mp4"
        assert neighbors["next"]["kind"] == "video"
        assert neighbors["previous"] is None
        assert client.get(endpoint, params={"request_id": first_request}).json() == neighbors
        assert client.get(endpoint, params={"prefix": "source/"}).json() == {"previous": None, "next": None, "current": neighbors["current"]}
        server.database.set_job_deletion_protection("first-job", True)
        assert client.get(endpoint).json()["current"]["deletion_protected"] is True
        server.database.set_job_deletion_protection("first-job", False)
        for invalid_parameters in ({"job_id": "second-job"}, {"request_id": second_request}, {"job_id": "missing"}):
            assert client.get(endpoint, params=invalid_parameters).status_code == 404
        assert client.get(endpoint, params={"job_id": "first-job", "request_id": first_request}).status_code == 422
        assert client.get(endpoint, params={"prefix": "../"}).status_code == 422
        assert client.get("/api/outputs/999999/neighbors").status_code == 404
        with sqlite3.connect(server.database.database_path) as connection:
            connection.execute("UPDATE output_files SET is_deleted=1 WHERE output_id=?", (video_identifier,))
        assert client.get(endpoint, params={"job_id": "first-job"}).json() == {"previous": None, "next": None, "current": neighbors["current"]}
        assert client.get(f"/api/outputs/{video_identifier}/neighbors").status_code == 404
        assert server.database.delete_job("first-job")
        assert client.get(endpoint, params={"job_id": "first-job"}).status_code == 404
