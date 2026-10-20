"""인증 경계와 실제 ComfyUI 해제 요청의 본문·빈 응답·실패 처리를 검증합니다."""

from pathlib import Path
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from home_server.comfy_client import ComfyClient
from test_application import FakeComfyClient, create_processing_test_app


@pytest.mark.parametrize("upstream_result", ["accepted", "http_error", "timeout"])
def test_free_memory_proxies_both_flags_after_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream_result: str,
) -> None:
    """확인된 사용자 요청만 전달하고 빈 200은 접수, 통신 실패는 502로 반환합니다."""

    captured_requests = []

    def handle_memory_request(request: httpx.Request) -> httpx.Response:
        """운영 ComfyUI를 호출하지 않고 해제 요청의 wire format을 기록합니다."""

        captured_requests.append(request)
        if upstream_result == "timeout":
            raise httpx.ReadTimeout("test timeout", request=request)
        return httpx.Response(200 if upstream_result == "accepted" else 500)

    async def request_memory_release() -> None:
        """실제 ComfyClient로 Mock transport에 해제 요청을 전달합니다."""

        memory_client = ComfyClient("http://comfy.test")
        await memory_client.close()
        memory_client.client = httpx.AsyncClient(
            base_url=memory_client.endpoint, transport=httpx.MockTransport(handle_memory_request),
        )
        try:
            await memory_client.free_memory()
        finally:
            await memory_client.close()

    fake_comfy = FakeComfyClient()
    monkeypatch.setattr(fake_comfy, "free_memory", request_memory_release, raising=False)
    application = create_processing_test_app(tmp_path, fake_comfy)
    with TestClient(application) as client:
        assert client.post("/api/comfy/free-memory").status_code == 401
        client.post("/api/login", json={"password": "test"})
        assert client.post(
            "/api/comfy/free-memory", headers={"Origin": "http://untrusted.test"},
        ).status_code == 403
        assert captured_requests == []

        response = client.post("/api/comfy/free-memory")
        if upstream_result == "accepted":
            assert response.status_code == 200
            assert response.json() == {"accepted": True}
        else:
            assert response.status_code == 502
            assert "요청하지 못했습니다" in response.json()["detail"]

    assert len(captured_requests) == 1
    assert captured_requests[0].method == "POST"
    assert captured_requests[0].url.path == "/free"
    assert json.loads(captured_requests[0].content) == {"unload_models": True, "free_memory": True}
