"""Anima Prompt 분리와 독립 작업의 일괄 등록·추첨·취소 경계를 검증합니다."""

from itertools import count
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import home_server.application as application_module
from home_server.anima_prompt_sections import split_anima_prompt_sections
from home_server.tag_builder import MAX_PROMPT_LENGTH
from test_application import FakeComfyClient, create_processing_test_app
from test_submission_worker import GatedSubmissionClient, wait_for_admission


@pytest.mark.parametrize("prompt_text,expected_prompts", [
    ("  portrait\r\nwith details  ", ["  portrait\r\nwith details  "]),
    ("first\n-----\nsecond", ["first", "second"]),
    ("first\r\n  ------\t\r\nsecond", ["first", "second"]),
    ("-----\nfirst\n-----\n \n-----\nsecond\n-----", ["first", "second"]),
    ("first ----- second\n----\nthird", ["first ----- second\n----\nthird"]),
    ("first\n----- comment\nsecond", ["first\n----- comment\nsecond"]),
])
def test_prompt_separator_only_splits_standalone_lines(prompt_text: str, expected_prompts: list[str]) -> None:
    """단독 구분자와 빈 블록을 해석하고 구분자가 없는 원문과 공통 Negative는 보존합니다."""

    negative_prompt = "avoid\n-----\nunchanged"
    original_body = {"prompt": prompt_text, "negative": negative_prompt}
    prompt_sections = split_anima_prompt_sections(original_body)
    assert [section["prompt"] for section in prompt_sections] == expected_prompts
    assert all(section["negative"] == negative_prompt for section in prompt_sections)
    assert original_body == {"prompt": prompt_text, "negative": negative_prompt}


@pytest.mark.parametrize("prompt_text", [None, 123, "", " \r\n", "-----\n  \n------"])
def test_empty_prompt_sections_are_rejected(prompt_text) -> None:
    """유효한 본문이 없는 입력은 작업을 만들기 전에 거부합니다."""

    with pytest.raises(ValueError, match="Anima Prompt"):
        split_anima_prompt_sections({"prompt": prompt_text})


def test_prompt_length_limit_is_applied_per_section() -> None:
    """전체 원문이 길어도 각 블록의 기존 길이 제한을 충족하면 허용합니다."""

    full_section = "a" * MAX_PROMPT_LENGTH
    assert len(split_anima_prompt_sections({"prompt": f"{full_section}\n-----\n{full_section}"})) == 2
    with pytest.raises(ValueError, match="Prompt 2:.*길이 제한"):
        split_anima_prompt_sections({"prompt": "first\n-----\n" + "a" * (MAX_PROMPT_LENGTH + 1)})


def create_prompt_section_tags(client: TestClient) -> list[str]:
    """태그 확장 결과의 구분자 줄도 보존되는 캐릭터·공통 Prompt 후보를 만듭니다."""

    selected_identifiers = []
    for tag_key, contents in (("CHR_GIRL", ["character A", "character B"]), ("PROMPT_NET", ["quality\n-----\nlighting"])):
        group_response = client.post("/api/tags/groups", json={"name": tag_key, "tag_key": tag_key})
        group_response.raise_for_status()
        for content_index, content in enumerate(contents, start=1):
            entry_response = client.post("/api/tags/entries", json={
                "group_id": group_response.json()["group_id"], "name": f"{tag_key} {content_index}",
                "content": content, "weight": 1,
            })
            entry_response.raise_for_status()
            selected_identifiers.append(entry_response.json()["tag_id"])
    return selected_identifiers


def test_two_prompt_sections_create_six_independent_requests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """2개 Prompt에 각 3장을 적용하고 원본·Snapshot·확정 Prompt와 Queue 순서를 분리합니다."""

    fake_client = FakeComfyClient()
    application = create_processing_test_app(tmp_path, fake_client)
    generation_seeds = count(100)
    resolved_tag_seeds = []
    original_resolver = application_module.resolve_anima_prompts

    def next_generation_seed(upper_bound: int) -> int:
        """요청별 추첨과 sampling이 다시 수행되는지 확인할 Seed를 제공합니다."""

        return next(generation_seeds)

    def record_tag_resolution(body: dict, selected_tags: list[dict], seed: int):
        """캐릭터 중복 여부 대신 실제 독립 추첨 호출과 Seed를 관찰합니다."""

        resolved_tag_seeds.append(seed)
        return original_resolver(body, selected_tags, seed)

    monkeypatch.setattr(application_module.secrets, "randbelow", next_generation_seed)
    monkeypatch.setattr(application_module, "resolve_anima_prompts", record_tag_resolution)
    prompt_texts = ["[CHR_GIRL] is cooking, [PROMPT_NET]", "[CHR_GIRL] is eating spaghetti, [PROMPT_NET]"]
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        selected_identifiers = create_prompt_section_tags(client)
        folder_response = client.post("/api/job-folders", json={"name": "여러 상황"})
        folder_response.raise_for_status()
        folder_identifier = folder_response.json()["folder_id"]
        response = client.post("/api/batches", json={
            "workflow": "anima", "body": {"prompt": "\n-----\n".join(prompt_texts), "negative": "blurry"},
            "selected_tag_ids": selected_identifiers, "count": 3, "description": "식사 상황",
            "folder_id": folder_identifier, "settings": {"width": 768, "height": 1024, "steps": 12, "cfg": 1},
            "loras": [{"name": "example.safetensors", "strength": 0.8, "clip_strength": 0.5}],
        })
        assert response.status_code == 200, response.text
        submission = response.json()
        assert submission["job_count"] == 2
        assert submission["request_count"] == 6
        assert len(set(submission["request_ids"])) == 6
        assert "job_id" not in submission
        assert len(submission["jobs"]) == 2
        assert [job["section_index"] for job in submission["jobs"]] == [1, 2]
        assert all(len(job["request_ids"]) == 3 for job in submission["jobs"])
        job_identifiers = [job["job_id"] for job in submission["jobs"]]
        jobs = [wait_for_admission(client, job_identifier) for job_identifier in job_identifiers]
        assert [metadata["home_server_request"]["job_id"] for _, metadata in fake_client.submissions] == [job_identifiers[0]] * 3 + [job_identifiers[1]] * 3
        assert resolved_tag_seeds == [100, 102, 104, 106, 108, 110]
        assert [metadata["home_server_request"]["settings"]["seed"] for _, metadata in fake_client.submissions] == [101, 103, 105, 107, 109, 111]
        submission_identifiers = set()
        for section_index, job in enumerate(jobs, start=1):
            assert job["request_count"] == 3
            assert job["description"] == "식사 상황"
            assert job["folder_id"] == folder_identifier
            assert job["inputs"]["body"] == {"prompt": prompt_texts[section_index - 1], "negative": "blurry"}
            assert job["inputs"]["prompt_section"]["section_index"] == section_index
            submission_identifiers.add(job["inputs"]["prompt_section"]["submission_identifier"])
            for request in job["requests"]:
                assert "[CHR_GIRL]" not in request["result"]["prompt"]
                assert "quality\n-----\nlighting" in request["result"]["prompt"]
                assert request["result"]["negative"] == "blurry"
            restored_inputs = client.get(f"/api/jobs/{job['job_id']}/inputs").json()["inputs"]
            assert restored_inputs["body"] == job["inputs"]["body"]
            assert len(restored_inputs["selected_tags"]) == 3
            assert {tag["tag_id"] for tag in restored_inputs["selected_tags"]} == set(selected_identifiers)
        assert len(submission_identifiers) == 1
        summaries = client.get("/api/jobs", params={"summary": True}).json()["items"]
        assert {job["summary"]["prompt_section"]["section_index"] for job in summaries} == {1, 2}
        assert all(graph["51"]["inputs"]["value"] == 1 for graph, _ in fake_client.submissions)
        assert all(metadata["home_server_request"]["prompt_section"]["section_count"] == 2 for _, metadata in fake_client.submissions)


def test_preview_groups_sections_and_preset_preserves_complete_source(tmp_path: Path) -> None:
    """Preset 원문을 그대로 저장하고 Prompt별 미리보기는 독립 묶음으로 반환합니다."""

    fake_client = FakeComfyClient()
    application = create_processing_test_app(tmp_path, fake_client)
    source_body = {"prompt": "  cooking\r\n-----\r\neating  ", "negative": "blurry"}
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        preset_response = client.post("/api/presets", json={"workflow": "anima", "name": "여러 상황", "body": source_body})
        assert preset_response.status_code == 200
        assert preset_response.json()["body"] == source_body
        preview_response = client.post("/api/prompts/preview", json={"workflow": "anima", "body": source_body, "count": 2})
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        assert len(preview["examples"]) == 4
        assert [section["prompt"] for section in preview["prompt_sections"]] == ["cooking", "eating"]
        for section in preview["prompt_sections"]:
            assert [example["index"] for example in section["examples"]] == [1, 2]
            assert all(example["prompt"] == section["prompt"] and example["negative"] == "blurry" for example in section["examples"])
        assert fake_client.submissions == []
        assert client.get("/api/jobs").json()["total"] == 0


@pytest.mark.parametrize("endpoint", ["/api/batches", "/api/prompts/preview"])
def test_invalid_later_section_is_rejected_before_any_job_or_preview(tmp_path: Path, endpoint: str) -> None:
    """두 번째 블록의 누락 참조가 앞 작업 저장이나 미리보기 호출을 남기지 않습니다."""

    fake_client = FakeComfyClient()
    application = create_processing_test_app(tmp_path, fake_client)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        response = client.post(endpoint, json={"workflow": "anima", "body": {"prompt": "cooking\n-----\n[MISSING]"}})
        assert response.status_code == 422
        assert "Prompt 2" in response.json()["detail"]
        assert client.get("/api/jobs").json()["total"] == 0
        assert fake_client.wildcard_prompts == []
        assert fake_client.submissions == []


def test_job_storage_failure_rolls_back_every_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """두 번째 Job 저장이 실패하면 첫 Job과 하위 요청까지 같은 Transaction에서 되돌립니다."""

    application = create_processing_test_app(tmp_path, FakeComfyClient())
    database = application.state.home_server.database
    original_add_job = database.add_job
    stored_job_count = 0

    def fail_second_job(*arguments, **keyword_arguments) -> None:
        """실제 INSERT를 수행한 뒤 두 번째 저장에서 오류를 발생시킵니다."""

        nonlocal stored_job_count
        original_add_job(*arguments, **keyword_arguments)
        stored_job_count += 1
        if stored_job_count == 2:
            raise ValueError("두 번째 작업 저장 실패")

    monkeypatch.setattr(database, "add_job", fail_second_job)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        response = client.post("/api/batches", json={"workflow": "anima", "body": {"prompt": "cooking\n-----\neating"}, "count": 3})
        assert response.status_code == 422
        assert stored_job_count == 2
        assert client.get("/api/jobs").json()["total"] == 0
        assert not application.state.home_server.submission_worker.busy
        with database._connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM job_requests").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM job_inputs").fetchone()[0] == 0


def test_cancelling_one_section_preserves_other_jobs_and_queue_order(tmp_path: Path) -> None:
    """앞 작업 접수 중 뒤 블록을 취소해도 앞 작업과 다음 일반 작업은 정상 접수합니다."""

    fake_client = GatedSubmissionClient()
    application = create_processing_test_app(tmp_path, fake_client)
    try:
        with TestClient(application) as client:
            client.post("/api/login", json={"password": "test"}).raise_for_status()
            response = client.post("/api/batches", json={"workflow": "anima", "body": {"prompt": "cooking\n-----\neating"}, "count": 3})
            response.raise_for_status()
            first_job, second_job = response.json()["jobs"]
            assert fake_client.first_submission_started.wait(3)
            cancellation = client.post(f"/api/jobs/{second_job['job_id']}/cancel")
            cancellation.raise_for_status()
            following_submission = client.post("/api/batches", json={"workflow": "anima", "body": {"prompt": "walking"}})
            following_submission.raise_for_status()
            fake_client.release_first_submission.set()
            first_job_result = wait_for_admission(client, first_job["job_id"])
            second_job_result = wait_for_admission(client, second_job["job_id"])
            wait_for_admission(client, following_submission.json()["job_id"])
            assert first_job_result["status_counts"] == {"pending": 3}
            assert second_job_result["status_counts"] == {"cancelled": 3}
            assert [metadata["home_server_request"]["job_id"] for _, metadata in fake_client.submissions] == [first_job["job_id"]] * 3 + [following_submission.json()["job_id"]]
    finally:
        fake_client.release_first_submission.set()


def test_shutdown_after_group_save_stops_all_unsubmitted_jobs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """일괄 저장 직후 Worker 접수가 닫혀도 어느 블록도 submitting으로 남기지 않습니다."""

    fake_client = FakeComfyClient()
    application = create_processing_test_app(tmp_path, fake_client)
    server = application.state.home_server
    original_store = application_module.store_anima_prompt_section_requests

    def save_and_stop_accepting(*arguments):
        """일괄 Commit 뒤 Queue 접수 이전의 종료 경합을 재현합니다."""

        request_batches = original_store(*arguments)
        server.submission_worker.accepting = False
        return request_batches

    monkeypatch.setattr(application_module, "store_anima_prompt_section_requests", save_and_stop_accepting)
    with TestClient(application) as client:
        client.post("/api/login", json={"password": "test"}).raise_for_status()
        response = client.post("/api/batches", json={"workflow": "anima", "body": {"prompt": "cooking\n-----\neating"}, "count": 3})
        assert response.status_code == 503
        jobs = client.get("/api/jobs").json()["items"]
        assert len(jobs) == 2
        assert all(job["status_counts"] == {"stopped": 3} for job in jobs)
        assert fake_client.submissions == []
