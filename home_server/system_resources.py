"""ComfyUI host의 자원 상태를 수집하고 모든 브라우저에 같은 Snapshot을 제공합니다."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from .comfy_client import ComfyClient


RESOURCE_POLL_INTERVAL_SECONDS = 2
LOGGER = logging.getLogger(__name__)


def resource_number(value: Any, maximum: float | None = None) -> float | None:
    """누락·음수·비정상 수치는 0으로 오인하지 않도록 제외합니다."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        return None
    return float(value)


def memory_resources(used: Any, total: Any) -> tuple[float | None, float | None, float | None]:
    """Memory 사용량과 전체 용량이 유효할 때만 사용률을 계산합니다."""

    used_bytes = resource_number(used)
    total_bytes = resource_number(total)
    if total_bytes is None or total_bytes == 0:
        return None, None, None
    if used_bytes is None or used_bytes > total_bytes:
        return None, total_bytes, None
    return used_bytes, total_bytes, used_bytes / total_bytes * 100


def empty_system_resources() -> dict[str, Any]:
    """조회 전이나 연결 실패 시 표시할 명시적인 미확인 상태를 만듭니다."""

    return {
        "status": "unavailable", "updated_at": None,
        "cpu_percent": None, "ram_used_bytes": None, "ram_total_bytes": None, "ram_percent": None,
        "gpu_name": None, "gpu_percent": None,
        "vram_used_bytes": None, "vram_total_bytes": None, "vram_percent": None,
    }


def normalize_system_resources(snapshot: dict[str, Any]) -> dict[str, Any]:
    """DaSiWa 응답에서 CPU·RAM과 첫 번째 GPU의 필요한 수치만 추립니다."""

    memory = snapshot.get("ram") or {}
    graphics_devices = snapshot.get("gpus") or []
    graphics_device = graphics_devices[0] if graphics_devices else {}
    memory_used, memory_total, memory_percent = memory_resources(memory.get("used"), memory.get("total"))
    video_memory_used, video_memory_total, video_memory_percent = memory_resources(
        graphics_device.get("memory_used"), graphics_device.get("memory_total"),
    )
    result = {
        "cpu_percent": resource_number(snapshot.get("cpu_percent"), 100),
        "ram_used_bytes": memory_used, "ram_total_bytes": memory_total, "ram_percent": memory_percent,
        "gpu_name": str(graphics_device.get("name") or "") or None,
        "gpu_percent": resource_number(graphics_device.get("utilization"), 100),
        "vram_used_bytes": video_memory_used, "vram_total_bytes": video_memory_total,
        "vram_percent": video_memory_percent,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    percentages = [result[field] for field in ("cpu_percent", "ram_percent", "gpu_percent", "vram_percent")]
    if all(value is not None for value in percentages):
        result["status"] = "ready"
    elif any(value is not None for value in percentages):
        result["status"] = "partial"
    else:
        result["status"] = "unavailable"
    return result


class SystemResourceMonitor:
    """단일 수집 Task가 갱신하는 최신 host 자원 상태를 보관합니다."""

    def __init__(self) -> None:
        """첫 조회 전에는 모든 지표를 미확인 상태로 준비합니다."""

        self.snapshot = empty_system_resources()
        self.collection_failed: bool | None = None

    async def refresh(self, comfy_client: ComfyClient) -> None:
        """통신·응답 오류가 작업 처리를 중단하거나 이전 값을 현재 값으로 남기지 않게 합니다."""

        try:
            snapshot = normalize_system_resources(await comfy_client.system_resources())
        except Exception as exception:
            snapshot = empty_system_resources()
            if self.collection_failed is not True:
                LOGGER.warning("ComfyUI host 자원 조회 실패: %s", type(exception).__name__)
            self.collection_failed = True
        else:
            if self.collection_failed:
                LOGGER.info("ComfyUI host 자원 조회 복구")
            self.collection_failed = False
        self.snapshot = snapshot
