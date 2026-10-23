"""Host 지표 변환·오류 복구·공통 Snapshot과 2초 수집 수명주기를 검증합니다."""

import asyncio
from pathlib import Path
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from home_server.comfy_client import ComfyClient
from home_server.system_resources import SystemResourceMonitor, normalize_system_resources
from test_application import FakeComfyClient, create_processing_test_app


def create_resource_snapshot() -> dict:
    """GPU 두 개 중 첫 번째 장비의 실제 용량과 사용률을 구분할 응답을 만듭니다."""

    return {
        "cpu_percent": 12.5, "ram": {"used": 24 * 1024**3, "total": 96 * 1024**3},
        "gpus": [
            {"name": "RTX 5080", "utilization": 75, "memory_used": 8 * 1024**3, "memory_total": 16 * 1024**3},
            {"name": "Integrated GPU", "utilization": 1, "memory_total": 2 * 1024**3},
        ],
    }


def test_system_resource_normalization_keeps_host_values_and_first_gpu() -> None:
    """CPU·RAM은 host 전체, GPU·VRAM은 첫 번째 GPU 수치로 변환합니다."""

    normalized = normalize_system_resources(create_resource_snapshot())
    assert normalized["status"] == "ready"
    assert normalized["cpu_percent"] == 12.5
    assert normalized["ram_percent"] == 25
    assert normalized["gpu_name"] == "RTX 5080"
    assert normalized["gpu_percent"] == 75
    assert normalized["vram_percent"] == 50
    assert normalized["vram_used_bytes"] == 8 * 1024**3
    assert normalized["updated_at"]


@pytest.mark.parametrize("invalid_value", [None, "N/A", True, -1, float("nan"), float("inf"), 101])
def test_unknown_or_invalid_resource_percentage_is_not_reported_as_zero(invalid_value) -> None:
    """조회 불가 값과 비정상 수치를 유효한 0%로 바꾸지 않습니다."""

    snapshot = create_resource_snapshot()
    snapshot["cpu_percent"] = invalid_value
    snapshot["gpus"][0]["utilization"] = invalid_value
    normalized = normalize_system_resources(snapshot)
    assert normalized["status"] == "partial"
    assert normalized["cpu_percent"] is None
    assert normalized["gpu_percent"] is None


def test_resource_collection_clears_stale_data_and_recovers_after_failure() -> None:
    """성공 뒤 연결 오류나 잘못된 응답이 오면 과거 수치를 제거하고 다음 성공 때 복구합니다."""

    async def verify_failure_recovery() -> None:
        """실제 HTTP client와 가짜 transport로 오류·정상 응답을 순서대로 전달합니다."""

        upstream_results = [create_resource_snapshot(), None, [], create_resource_snapshot()]

        def handle_resource_request(request: httpx.Request) -> httpx.Response:
            """호출 경로와 2초 timeout을 검사하고 통신 실패도 재현합니다."""

            assert request.url.path == "/dasiwa/system-monitor"
            assert request.extensions["timeout"]["read"] == 2
            response_body = upstream_results.pop(0)
            if response_body is None:
                raise httpx.ConnectError("offline", request=request)
            return httpx.Response(200, json=response_body)

        comfy_client = ComfyClient("http://comfy.test")
        await comfy_client.close()
        comfy_client.client = httpx.AsyncClient(
            base_url=comfy_client.endpoint, transport=httpx.MockTransport(handle_resource_request),
        )
        resource_monitor = SystemResourceMonitor()
        try:
            for expected_status in ("ready", "unavailable", "unavailable", "ready"):
                await resource_monitor.refresh(comfy_client)
                assert resource_monitor.snapshot["status"] == expected_status
                if expected_status == "unavailable":
                    assert resource_monitor.snapshot["vram_used_bytes"] is None
                    assert resource_monitor.snapshot["updated_at"] is None
        finally:
            await comfy_client.close()

    asyncio.run(verify_failure_recovery())


def test_resource_endpoint_shares_two_second_sampler_and_requires_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """접속·요청 건수가 수집 횟수를 늘리지 않고 서버 수명주기에 따라 단일 수집합니다."""

    sample_times = []
    fake_comfy = FakeComfyClient()

    async def collect_resource_snapshot() -> dict:
        """수집 시각을 기록해 사용자 요청과 무관한 주기를 검증합니다."""

        sample_times.append(time.monotonic())
        return create_resource_snapshot()

    monkeypatch.setattr(fake_comfy, "system_resources", collect_resource_snapshot)
    application = create_processing_test_app(tmp_path, fake_comfy)
    with TestClient(application) as client:
        assert client.get("/api/system-resources").status_code == 401
        client.post("/api/login", json={"password": "test"})
        for request_number in range(10):
            response = client.get("/api/system-resources")
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["gpu_name"] == "RTX 5080"
        assert len(sample_times) == 1
        time.sleep(2.1)
        assert len(sample_times) == 2
        assert 1.9 <= sample_times[1] - sample_times[0] <= 2.5
