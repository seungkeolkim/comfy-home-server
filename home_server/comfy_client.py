"""ComfyUI HTTP API와 통신합니다."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx


def encode_json_payload(payload: Any) -> bytes:
    """큰 Workflow JSON의 직렬화와 UTF-8 변환을 Worker에서 완료합니다."""

    return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def queue_from_response(response: httpx.Response) -> dict[str, Any]:
    """ComfyUI JSON 해석과 대기·실행 ID 목록 구성을 Worker에서 수행합니다."""

    running_requests = []
    pending_requests = []
    for job in response.json()["jobs"]:
        if job["status"] == "in_progress":
            running_requests.append([0, job["id"]])
        elif job["status"] == "pending":
            pending_requests.append([0, job["id"]])
    return {"queue_running": running_requests, "queue_pending": pending_requests}


class ComfyClient:
    """ComfyUI의 queue, wildcard, model 목록을 호출합니다."""

    def __init__(self, endpoint: str) -> None:
        """ComfyUI 주소를 보관하고 HTTP client를 생성합니다."""

        self.endpoint = endpoint
        self.client = httpx.AsyncClient(base_url=endpoint, timeout=120)

    async def close(self) -> None:
        """HTTP 연결을 종료합니다."""

        await self.client.aclose()

    async def request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        """HTTP 통신은 비동기로 수행하고 요청·응답 JSON 변환은 Worker로 옮깁니다."""

        if "json" in kwargs:
            kwargs["content"] = await asyncio.to_thread(encode_json_payload, kwargs.pop("json"))
            request_headers = httpx.Headers(kwargs.pop("headers", None))
            request_headers.setdefault("Content-Type", "application/json")
            kwargs["headers"] = request_headers
        response = await self.client.request(method, path, **kwargs)
        if response.is_error:
            raise RuntimeError(f"ComfyUI {path}: HTTP {response.status_code} {response.text[:1000]}")
        return await asyncio.to_thread(response.json)

    async def list_loras(self) -> list[str]:
        """ComfyUI가 인식하는 LoRA 이름을 조회합니다."""

        result = await self.request_json("GET", "/models/loras")
        return [str(name) for name in result]

    async def populate_wildcards(self, text: str, seed: int) -> str:
        """설치된 Impact Pack으로 Prompt wildcard를 확장합니다."""

        if "{" not in text and "__" not in text:
            return text
        result = await self.request_json("POST", "/impact/wildcards", json={"text": text, "seed": seed})
        return str(result["text"])

    async def upload_image(self, image_path: Path, file_name: str) -> str:
        """MiniMax 입력 이미지를 ComfyUI input에 업로드합니다."""

        image_bytes = await asyncio.to_thread(image_path.read_bytes)
        response = await self.client.post(
            "/upload/image",
            files={"image": (file_name, image_bytes)},
            data={"type": "input", "subfolder": "from_home_server", "overwrite": "false"},
        )
        if response.is_error:
            raise RuntimeError(f"이미지 업로드 실패: HTTP {response.status_code} {response.text[:500]}")
        result = await asyncio.to_thread(response.json)
        name = str(result["name"])
        subfolder = str(result.get("subfolder", "")).strip("/\\")
        return f"{subfolder}/{name}" if subfolder else name

    async def submit(self, workflow: dict[str, Any], metadata: dict[str, Any]) -> str:
        """Workflow를 queue에 제출하고 접수된 prompt ID를 반환합니다."""

        result = await self.request_json(
            "POST", "/prompt",
            json={"prompt": workflow, "extra_data": {"extra_pnginfo": metadata}},
        )
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI가 prompt_id를 반환하지 않았습니다: {result}")
        return str(prompt_id)

    async def queue(self) -> dict[str, Any]:
        """Workflow 본문을 포함하지 않는 ComfyUI 상태 목록을 queue 형태로 반환합니다."""

        response = await self.client.get("/api/jobs", params={"status": "pending,in_progress"}, timeout=15)
        if response.status_code in {404, 405}:
            return await self.request_json("GET", "/queue")
        response.raise_for_status()
        return await asyncio.to_thread(queue_from_response, response)

    async def history(self, prompt_id: str) -> dict[str, Any]:
        """한 요청의 완료 기록을 조회합니다."""

        return await self.request_json("GET", f"/history/{prompt_id}", timeout=15)

    async def free_memory(self) -> None:
        """Model unload와 execution cache 해제를 요청하고 빈 성공 응답을 처리합니다."""

        response = await self.client.post(
            "/free", json={"unload_models": True, "free_memory": True}, timeout=15,
        )
        response.raise_for_status()

    async def system_resources(self) -> dict[str, Any]:
        """설치된 DaSiWa API에서 Docker가 아닌 ComfyUI host의 자원 상태를 읽습니다."""

        return await self.request_json("GET", "/dasiwa/system-monitor", timeout=2)

    async def cancel_prompt(self, prompt_id: str) -> bool:
        """ComfyUI에서 지정한 대기·실행 요청만 취소합니다."""

        result = await self.request_json("POST", f"/api/jobs/{prompt_id}/cancel", timeout=15)
        return bool(result.get("cancelled"))

    async def cancel_prompts(self, prompt_ids: list[str]) -> None:
        """선택한 대기 ID만 한 번에 제거한 뒤 실행으로 넘어간 ID만 원자적으로 취소합니다."""

        selected_ids = set(prompt_ids)
        queue = await self.queue()
        pending_ids = [str(item[1]) for item in queue.get("queue_pending", []) if str(item[1]) in selected_ids]
        if pending_ids:
            request_bytes = await asyncio.to_thread(encode_json_payload, {"delete": pending_ids})
            response = await self.client.post(
                "/queue", content=request_bytes, headers={"Content-Type": "application/json"}, timeout=15,
            )
            response.raise_for_status()
            # 대기열 조회 후 실행으로 넘어간 요청도 ID 기준으로 다시 확인합니다.
            queue = await self.queue()
        running_ids = [str(item[1]) for item in queue.get("queue_running", []) if str(item[1]) in selected_ids]
        for prompt_id in running_ids:
            await self.cancel_prompt(prompt_id)
