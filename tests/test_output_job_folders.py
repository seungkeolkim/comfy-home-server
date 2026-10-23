"""결과물의 작업 분류 조회와 선택·미리보기 범위 및 소속 변경 반영을 검증합니다."""

from pathlib import Path

from fastapi.testclient import TestClient

from test_application import FakeComfyClient, create_processing_test_app
from test_output_catalog import add_catalog_test_request


def test_output_folder_scope_covers_descendants_selection_and_neighbors(tmp_path: Path) -> None:
    """DB 분류로 영상·이미지를 함께 조회하고 페이지·보호·미리보기 범위를 일치시킵니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    database = server.database
    parent_identifier = database.job_folders.save_folder("인물", None)
    child_identifier = database.job_folders.save_folder("표정", parent_identifier)
    other_identifier = database.job_folders.save_folder("배경", None)
    for job_identifier, folder_identifier, output_paths in (
        ("parent-job", parent_identifier, ["same/261023_120000_4.png"]),
        ("child-job", child_identifier, ["different/261023_120000_3.mp4", "different/261023_120000_2.png"]),
        ("other-job", other_identifier, ["same/261023_120000_1.png"]),
        ("unassigned-job", None, ["same/unassigned.png"]),
    ):
        request_identifier = add_catalog_test_request(database, job_identifier)
        database.complete_request(request_identifier, output_paths)
        database.job_folders.move_jobs([job_identifier], folder_identifier)
    database.set_job_deletion_protection("child-job", True)

    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        listing = client.get("/api/outputs", params={"folder_id": parent_identifier}).json()
        assert listing["total"] == 3
        assert [output_file["kind"] for output_file in listing["files"]] == ["image", "video", "image"]
        output_identifiers = [output_file["output_id"] for output_file in listing["files"]]
        page = client.get("/api/outputs", params={"folder_id": parent_identifier, "page_size": 2, "page": 2}).json()
        assert page["total_pages"] == 2
        assert [output_file["output_id"] for output_file in page["files"]] == output_identifiers[2:]
        candidates = client.get("/api/outputs/selection-candidates", params={"folder_id": parent_identifier}).json()
        assert set(candidates["output_ids"]) == set(output_identifiers)
        assert candidates["deletable_output_ids"] == [output_identifiers[0]]
        assert client.get("/api/outputs/deletion-candidates", params={"folder_id": parent_identifier}).json() == {
            "output_ids": [output_identifiers[0]],
        }
        neighbors = client.get(f"/api/outputs/{output_identifiers[1]}/neighbors", params={"folder_id": parent_identifier}).json()
        assert neighbors["previous"]["output_id"] == output_identifiers[0]
        assert neighbors["next"]["output_id"] == output_identifiers[2]
        assert client.get(f"/api/outputs/{output_identifiers[0]}/neighbors", params={"folder_id": child_identifier}).status_code == 404
        assert client.get("/api/outputs", params={"folder_id": child_identifier}).json()["total"] == 2
        assert client.get("/api/outputs", params={"folder_id": "unassigned"}).json()["total"] == 1
        for endpoint in ("/api/outputs", "/api/outputs/selection-candidates", "/api/outputs/deletion-candidates",
                         f"/api/outputs/{output_identifiers[0]}/neighbors"):
            assert client.get(endpoint, params={"folder_id": "missing-folder"}).status_code == 404


def test_output_folder_scope_tracks_assignments_and_keeps_orphan_files_unassigned(tmp_path: Path) -> None:
    """분류·이력 삭제와 파일 이동 뒤에도 현재 소속을 반영하며 외부 파일은 미분류에 남깁니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    database = server.database
    parent_identifier = database.job_folders.save_folder("상위", None)
    child_identifier = database.job_folders.save_folder("하위", parent_identifier)
    other_identifier = database.job_folders.save_folder("별도", None)
    request_identifier = add_catalog_test_request(database)
    database.complete_request(request_identifier, ["original.png"])
    database.job_folders.move_jobs(["catalog-job"], child_identifier)
    server.config.managed_output_directory.mkdir(parents=True, exist_ok=True)
    (server.config.managed_output_directory / "original.png").write_bytes(b"preserved file")
    (server.config.managed_output_directory / "external.mp4").write_bytes(b"external file")

    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        client.post("/api/outputs/sync")
        assert client.get("/api/outputs", params={"folder_id": "unassigned"}).json()["total"] == 1
        database.job_folders.move_jobs(["catalog-job"], other_identifier)
        assert client.get("/api/outputs", params={"folder_id": parent_identifier}).json()["total"] == 0
        listing = client.get("/api/outputs", params={"folder_id": other_identifier}).json()
        assert listing["total"] == 1
        output_identifier = listing["files"][0]["output_id"]
        assert client.post("/api/outputs/move", json={"source": "original.png", "destination_folder": "moved"}).status_code == 200
        assert client.get("/api/outputs", params={"folder_id": other_identifier}).json()["files"][0]["path"] == "moved/original.png"
        database.job_folders.delete_folder(other_identifier)
        assert client.get("/api/outputs", params={"folder_id": other_identifier}).status_code == 404
        assert client.get("/api/outputs", params={"folder_id": "unassigned"}).json()["total"] == 2
        assert client.delete("/api/jobs/catalog-job").status_code == 200
        unassigned_listing = client.get("/api/outputs", params={"folder_id": "unassigned"}).json()
        assert unassigned_listing["total"] == 2
        assert all(output_file["job_id"] is None for output_file in unassigned_listing["files"])
        neighbors = client.get(f"/api/outputs/{output_identifier}/neighbors", params={"folder_id": "unassigned"}).json()
        assert neighbors["current"]["path"] == "moved/original.png"
        assert (server.config.managed_output_directory / "moved/original.png").is_file()
