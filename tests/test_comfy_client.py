"""ComfyUI 상태 요약과 지정 ID의 묶음 취소 계약을 검증합니다."""

import asyncio
import json
import threading
import time
from pathlib import Path

import httpx
import pytest

from home_server.comfy_client import ComfyClient


def test_queue_reads_small_job_summaries_without_workflow_payload() -> None:
    """상태 요약 API의 ID와 상태만 기존 queue 형태로 변환합니다."""

    def handle_request(request: httpx.Request) -> httpx.Response:
        """대기·실행 필터가 있는 요약 조회만 허용합니다."""

        assert request.url.path == "/api/jobs"
        assert request.url.params["status"] == "pending,in_progress"
        return httpx.Response(200, json={"jobs": [{"id": "running", "status": "in_progress"},
                                                 {"id": "pending", "status": "pending"}]})

    async def verify_queue() -> None:
        """실제 HTTP client의 transport만 교체해 변환 결과를 확인합니다."""

        client = ComfyClient("http://comfy.test")
        await client.client.aclose()
        client.client = httpx.AsyncClient(base_url=client.endpoint, transport=httpx.MockTransport(handle_request))
        try:
            assert await client.queue() == {"queue_running": [[0, "running"]], "queue_pending": [[0, "pending"]]}
        finally:
            await client.close()

    asyncio.run(verify_queue())


def test_batch_cancel_sends_only_selected_prompt_ids() -> None:
    """100개 대기 요청을 한 번에 제거하고 실행 경합은 지정 ID로만 취소합니다."""

    requested_identifiers = [f"prompt-{request_index}" for request_index in range(100)]
    requests = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        """묶음 취소의 경로와 본문만 수집합니다."""

        requests.append(request)
        if request.url.path == "/api/jobs":
            queue_reads = sum(record.url.path == "/api/jobs" for record in requests)
            if queue_reads == 1:
                return httpx.Response(200, json={"jobs": [{"id": identifier, "status": "pending"}
                    for identifier in requested_identifiers] + [{"id": "unrelated", "status": "pending"}]})
            return httpx.Response(200, json={"jobs": [{"id": "prompt-0", "status": "in_progress"},
                                                     {"id": "unrelated", "status": "pending"}]})
        return httpx.Response(200, json={"cancelled": True})

    async def verify_cancellation() -> None:
        """묶음 전송이 끝난 뒤 client 연결을 닫습니다."""

        client = ComfyClient("http://comfy.test")
        await client.client.aclose()
        client.client = httpx.AsyncClient(base_url=client.endpoint, transport=httpx.MockTransport(handle_request))
        try:
            await client.cancel_prompts(requested_identifiers)
        finally:
            await client.close()

    asyncio.run(verify_cancellation())
    assert [request.url.path for request in requests] == ["/api/jobs", "/queue", "/api/jobs", "/api/jobs/prompt-0/cancel"]
    assert json.loads(requests[1].content) == {"delete": requested_identifiers}


def test_older_comfy_server_falls_back_to_supported_queue_and_single_cancel() -> None:
    """요약·묶음 API가 없는 서버에서는 기존 지정 ID 조회·취소 계약을 유지합니다."""

    request_paths = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        """새 API만 404로 반환하고 구형 API는 정상 처리합니다."""

        request_paths.append(request.url.path)
        if request.url.path == "/api/jobs":
            return httpx.Response(404)
        if request.url.path == "/queue":
            return httpx.Response(200, json={"queue_running": [[0, "legacy"]], "queue_pending": []})
        return httpx.Response(200, json={"cancelled": True})

    async def verify_fallback() -> None:
        """구형 API의 응답과 지정 ID 취소를 확인합니다."""

        client = ComfyClient("http://comfy.test")
        await client.client.aclose()
        client.client = httpx.AsyncClient(base_url=client.endpoint, transport=httpx.MockTransport(handle_request))
        try:
            assert (await client.queue())["queue_running"] == [[0, "legacy"]]
            await client.cancel_prompts(["legacy"])
        finally:
            await client.close()

    asyncio.run(verify_fallback())
    assert request_paths == ["/api/jobs", "/queue", "/api/jobs", "/queue", "/api/jobs/legacy/cancel"]


@pytest.mark.parametrize("conversion", ["request_json", "history_json", "queue_json", "image_read"])
def test_slow_comfy_json_or_file_conversion_runs_outside_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conversion: str,
) -> None:
    """Workflow 직렬화·History 해석·Queue 구성·파일 읽기가 비동기 통신을 막지 않습니다."""

    from home_server.comfy_client import encode_json_payload

    conversion_started = threading.Event()
    release_conversion = threading.Event()
    conversion_on_event_loop = []
    captured_requests = []
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"test-image-bytes")

    def block_conversion() -> None:
        """변환 실행 Thread를 확인하고 긴 동기 처리를 재현합니다."""

        try:
            asyncio.get_running_loop()
            conversion_on_event_loop.append(True)
        except RuntimeError:
            conversion_on_event_loop.append(False)
        conversion_started.set()
        release_conversion.wait(3)

    def blocked_encode(payload) -> bytes:
        """ComfyUI로 전송할 Workflow의 JSON 변환을 멈춥니다."""

        block_conversion()
        return encode_json_payload(payload)

    class BlockingJsonResponse(httpx.Response):
        """History·Queue 응답의 JSON 해석 지연을 재현합니다."""

        def json(self, **keyword_arguments):
            """응답 JSON을 해석하는 Thread에서 지연을 발생시킵니다."""

            block_conversion()
            return super().json(**keyword_arguments)

    original_read_bytes = Path.read_bytes

    def blocked_image_read(selected_path: Path) -> bytes:
        """MiniMax 입력 파일 읽기를 멈춥니다."""

        block_conversion()
        return original_read_bytes(selected_path)

    def handle_request(request: httpx.Request) -> httpx.Response:
        """인코딩된 JSON·이미지 계약을 확인하고 응답을 제공합니다."""

        captured_requests.append(request)
        if conversion == "request_json":
            assert request.headers["content-type"] == "application/json"
            assert json.loads(request.content) == {"prompt": "한국어 Prompt", "seed": 7}
            return httpx.Response(200, json={"accepted": True})
        if conversion == "history_json":
            return BlockingJsonResponse(200, json={"prompt-id": {"outputs": {}}})
        if conversion == "queue_json":
            return BlockingJsonResponse(200, json={"jobs": [{"id": "running", "status": "in_progress"}]})
        assert b"test-image-bytes" in request.content
        return httpx.Response(200, json={"name": "image.png", "subfolder": "from_home_server"})

    if conversion == "request_json":
        monkeypatch.setattr("home_server.comfy_client.encode_json_payload", blocked_encode)
    if conversion == "image_read":
        monkeypatch.setattr(Path, "read_bytes", blocked_image_read)

    async def verify_conversion() -> None:
        """변환이 막힌 동안 Event Loop가 계속 실행되고 HTTP 처리 결과도 유지되는지 확인합니다."""

        client = ComfyClient("http://comfy.test")
        await client.client.aclose()
        client.client = httpx.AsyncClient(base_url=client.endpoint, transport=httpx.MockTransport(handle_request))
        if conversion == "request_json":
            operation = client.request_json("POST", "/prompt", json={"prompt": "한국어 Prompt", "seed": 7})
        elif conversion == "history_json":
            operation = client.history("prompt-id")
        elif conversion == "queue_json":
            operation = client.queue()
        else:
            operation = client.upload_image(image_path, "image.png")
        started = time.monotonic()
        conversion_task = asyncio.create_task(operation)
        try:
            assert await asyncio.to_thread(conversion_started.wait, 2)
            assert time.monotonic() - started < 1
            assert not conversion_task.done()
            assert conversion_on_event_loop == [False]
        finally:
            release_conversion.set()
            result = await conversion_task
            await client.close()
        expected_results = {
            "request_json": {"accepted": True}, "history_json": {"prompt-id": {"outputs": {}}},
            "queue_json": {"queue_running": [[0, "running"]], "queue_pending": []},
            "image_read": "from_home_server/image.png",
        }
        assert result == expected_results[conversion]

    asyncio.run(verify_conversion())
    assert len(captured_requests) == 1
