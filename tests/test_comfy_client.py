"""ComfyUI 상태 요약과 지정 ID의 묶음 취소 계약을 검증합니다."""

import asyncio
import json

import httpx

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
