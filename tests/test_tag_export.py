"""실제 ComfyUI나 운영 DB 없이 태그 JSON 다운로드의 보존 범위를 검증합니다."""

from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from test_application import FakeComfyClient, create_processing_test_app


def test_tag_export_requires_login_and_supports_empty_catalog(tmp_path: Path) -> None:
    """미인증 다운로드를 거부하고 태그가 없어도 유효한 교환 파일을 제공합니다."""

    app = create_processing_test_app(tmp_path, FakeComfyClient())
    with TestClient(app) as client:
        assert client.get("/api/tags/export").status_code == 401
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        response = client.get("/api/tags/export")

    assert response.status_code == 200
    exported_definitions = response.json()
    assert set(exported_definitions) == {"format", "schema_version", "exported_at", "groups"}
    assert exported_definitions["format"] == "comfy-home-server.tags"
    assert exported_definitions["schema_version"] == 1
    assert exported_definitions["groups"] == []
    exported_timestamp = datetime.fromisoformat(exported_definitions["exported_at"])
    assert exported_timestamp.utcoffset() == timedelta(0)
    expected_filename = f"tags_{exported_timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    assert response.headers["content-disposition"] == f'attachment; filename="{expected_filename}"'
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-store"


def test_tag_export_preserves_all_definitions_without_internal_state(tmp_path: Path) -> None:
    """빈 그룹·동일 이름·공유 참조·긴 원문·weight를 보존하고 DB는 변경하지 않습니다."""

    comfy_client = FakeComfyClient()
    app = create_processing_test_app(tmp_path, comfy_client)
    database = app.state.home_server.database
    database.save_tag_group("first-group", "조명", "LIGHTING", False)
    database.save_tag_group("second-group", "조명", "LIGHTING", True)
    database.save_tag_group("empty-group", "비어 있는 그룹", "EMPTY", False)
    long_content = 'soft window light, [DETAIL]\n"한글 본문"과 \\ 경로\n' + "원문 보존 " * 1000
    database.save_tag_entry("first-tag", {
        "group_id": "first-group", "name": "같은 이름", "content": long_content, "weight": 5.0,
    })
    database.save_tag_entry("second-tag", {
        "group_id": "first-group", "name": "같은 이름", "content": "warm sunlight", "weight": 0.25,
    })
    database.save_tag_entry("third-tag", {
        "group_id": "second-group", "name": "같은 이름", "content": "warm sunlight", "weight": 1.0,
    })

    with TestClient(app) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        definitions_before_export = client.get("/api/tags").json()
        response = client.get("/api/tags/export")
        definitions_after_export = client.get("/api/tags").json()

    assert response.status_code == 200
    expected_groups = []
    for source_group in definitions_before_export["groups"]:
        expected_tags = []
        for source_tag in definitions_before_export["entries"]:
            if source_tag["group_id"] == source_group["group_id"]:
                expected_tags.append({
                    "name": source_tag["name"], "content": source_tag["content"], "weight": source_tag["weight"],
                })
        expected_groups.append({"name": source_group["name"], "tag_key": source_group["tag_key"], "tags": expected_tags})

    assert response.json()["groups"] == expected_groups
    assert len(expected_groups) == 3
    assert sum(len(group["tags"]) for group in expected_groups) == 3
    assert long_content in [tag["content"] for group in response.json()["groups"] for tag in group["tags"]]
    assert "조명" in response.content.decode("utf-8")
    assert '\n  "format":' in response.text
    assert definitions_after_export == definitions_before_export
    assert comfy_client.submissions == []
