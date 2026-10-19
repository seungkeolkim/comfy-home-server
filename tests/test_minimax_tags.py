"""MiniMax의 공통 태그 검증·이미지별 추첨·원본 Snapshot 및 Metadata를 검증합니다."""

import json
import random

from pathlib import Path

from fastapi.testclient import TestClient

from home_server.tag_builder import resolve_tag_text
from test_application import FakeComfyClient, create_processing_test_app, wait_for_job_status
from test_minimax_generation import CapturingImageClient, add_input_images, wait_for_submissions


def create_minimax_tag_graph(client: TestClient) -> list[dict]:
    """같은 참조를 공유하는 두 그룹과 다단계·반복 참조를 가진 그래프를 만듭니다."""

    definitions = [
        ("동작", "ACTION", "동작 A", "[PAIR], {walk|run} __literal__", 1),
        ("두 사람", "PAIR", "인물 조합", "[ACTOR] and [ACTOR]", 1),
        ("인물 1", "ACTOR", "인물 A", "person A", 1),
        ("인물 2", "ACTOR", "인물 B", "person B", 3),
    ]
    entries = []
    for group_name, tag_key, entry_name, content, weight in definitions:
        group = client.post("/api/tags/groups", json={"name": group_name, "tag_key": tag_key}).json()
        entry = client.post("/api/tags/entries", json={
            "group_id": group["group_id"], "name": entry_name, "content": content, "weight": weight,
        }).json()
        entries.append(entry)
    return entries


def test_minimax_preview_and_image_requests_use_tag_snapshots_without_wildcards(tmp_path: Path, monkeypatch) -> None:
    """다단계 태그를 이미지마다 독립 추첨하고 접수 뒤 정의가 삭제되어도 원본·선택 경로를 보존합니다."""

    comfy_client = CapturingImageClient(block_upload=True)
    application = create_processing_test_app(tmp_path, comfy_client)
    server = application.state.home_server
    image_ids = add_input_images(server, [(f"folder/{image_number}.png", (64, 96)) for image_number in range(3)])
    body = {"prompt": "<Picture 1> [ACTION]\n[Scene]"}
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"})
            entries = create_minimax_tag_graph(client)
            selected_ids = [entry["tag_id"] for entry in entries]
            definitions_by_id = {
                definition["tag_id"]: definition for definition in server.database.get_selected_tag_definitions(selected_ids)
            }
            definitions = [definitions_by_id[tag_id] for tag_id in selected_ids]
            seeds = iter([1, 2, 3])
            monkeypatch.setattr("home_server.application.secrets.randbelow", lambda maximum: next(seeds))
            preview = client.post("/api/prompts/preview", json={
                "workflow": "minimax_h3", "body": body, "selected_tag_ids": selected_ids, "count": 3,
            })
            assert preview.status_code == 200, preview.text
            examples = preview.json()["examples"]
            assert len(examples) == 3
            assert len({example["prompt"] for example in examples}) > 1
            for example, tag_seed in zip(examples, (1, 2, 3), strict=True):
                expected_prompt, expected_path = resolve_tag_text(body["prompt"], definitions, random.Random(tag_seed))
                assert example["prompt"] == expected_prompt
                assert example["selected_path"] == expected_path
                assert "{walk|run} __literal__" in expected_prompt
                assert "[Scene]" in expected_prompt
                assert example["negative"] == ""
            assert comfy_client.wildcard_prompts == []
            saved_preset = client.post("/api/presets", json={"name": "영상 태그", "workflow": "minimax_h3", "body": body}).json()
            assert saved_preset["body"] == body
            seeds = iter([1, 2, 3])
            response = client.post("/api/batches", json={
                "workflow": "minimax_h3", "body": body, "selected_tag_ids": selected_ids,
                "output_ids": list(image_ids.values()), "input_scope": "folder", "input_directory": "folder",
            })
            assert response.status_code == 200, response.text
            assert comfy_client.upload_started.wait(3)
            job_id = response.json()["job_id"]
            assert client.delete(f"/api/tags/entries/{selected_ids[2]}").status_code == 200
            assert client.put(f"/api/tags/entries/{selected_ids[3]}", json={
                "group_id": entries[3]["group_id"], "name": "변경된 B", "content": "changed person", "weight": 1,
            }).status_code == 200
            comfy_client.release_upload.set()
            wait_for_submissions(comfy_client, 3)
            job = wait_for_job_status(client, job_id, "pending")
            saved_inputs = server.database.get_job_inputs(job_id)["inputs"]
            assert saved_inputs["body"] == body
            assert [entry["content"] for entry in saved_inputs["selected_tags"]] == [entry["content"] for entry in entries]
            for request_index, (request_workflow, metadata) in enumerate(comfy_client.submissions):
                result = job["requests"][request_index]["result"]
                assert result["prompt"] == examples[request_index]["prompt"]
                assert result["selected_path"] == examples[request_index]["selected_path"]
                assert result["tag_seed"] == request_index + 1
                assert result["wildcard_seed"] is None
                assert result["source_image"]["path"] == f"folder/{request_index}.png"
                director_inputs = request_workflow["2730"]["inputs"]
                assert director_inputs["prompt"] == director_inputs["external_prompt_overwrite"] == result["prompt"]
                assert json.loads(director_inputs["timeline_data"])["resolved_prompt"] == result["prompt"]
                assert json.loads(director_inputs["builder_state"])["simple_prompt"] == result["prompt"]
                assert metadata["home_server_request"]["selected_path"] == result["selected_path"]
                assert metadata["home_server_request"]["tag_seed"] == result["tag_seed"]
                metadata_director = next(node for node in metadata["workflow"]["nodes"] if str(node["id"]) == "2730")
                assert metadata_director["widgets_values_named"]["prompt"] == result["prompt"]
            assert comfy_client.wildcard_prompts == []
    finally:
        comfy_client.release_upload.set()


def test_minimax_rejects_missing_cyclic_and_deleted_tags_before_input_snapshot(tmp_path: Path) -> None:
    """두 API가 잘못된 그래프를 거부하며 임시 입력이나 빈 작업을 남기지 않는지 확인합니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    server = application.state.home_server
    image_ids = add_input_images(server, [("image.png", (64, 96))])
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"})
        entries = create_minimax_tag_graph(client)
        selected_ids = [entry["tag_id"] for entry in entries]
        base_payload = {"workflow": "minimax_h3", "body": {"prompt": "[ACTION]"}}
        invalid_selections = [[], selected_ids[:1], selected_ids[:2], ["deleted-id"], [selected_ids[0]] * 2]
        for selected_subset in invalid_selections:
            for endpoint in ("/api/prompts/preview", "/api/batches"):
                response = client.post(endpoint, json={
                    **base_payload, "selected_tag_ids": selected_subset,
                    "output_ids": list(image_ids.values()), "input_scope": "single",
                })
                assert response.status_code == 422, response.text
        client.put(f"/api/tags/entries/{selected_ids[1]}", json={
            "group_id": entries[1]["group_id"], "name": "순환", "content": "[ACTION]", "weight": 1,
        })
        for endpoint in ("/api/prompts/preview", "/api/batches"):
            rejected = client.post(endpoint, json={
                **base_payload, "selected_tag_ids": selected_ids, "output_ids": list(image_ids.values()), "input_scope": "single",
            })
            assert rejected.status_code == 422
            assert "cycle" in rejected.json()["detail"]
        assert server.database.list_jobs()["total"] == 0
        assert list(server.upload_directory.iterdir()) == []
