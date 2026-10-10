"""ComfyUI HTTP API와 통신합니다."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx


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
        """HTTP 오류의 본문을 포함해 API 응답을 처리합니다."""

        response = await self.client.request(method, path, **kwargs)
        if response.is_error:
            raise RuntimeError(f"ComfyUI {path}: HTTP {response.status_code} {response.text[:1000]}")
        return response.json()

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

        with image_path.open("rb") as image_file:
            response = await self.client.post(
                "/upload/image",
                files={"image": (file_name, image_file)},
                data={"type": "input", "subfolder": "from_home_server", "overwrite": "false"},
            )
        if response.is_error:
            raise RuntimeError(f"이미지 업로드 실패: HTTP {response.status_code} {response.text[:500]}")
        result = response.json()
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
        jobs = response.json()["jobs"]
        return {
            "queue_running": [[0, job["id"]] for job in jobs if job["status"] == "in_progress"],
            "queue_pending": [[0, job["id"]] for job in jobs if job["status"] == "pending"],
        }

    async def history(self, prompt_id: str) -> dict[str, Any]:
        """한 요청의 완료 기록을 조회합니다."""

        return await self.request_json("GET", f"/history/{prompt_id}", timeout=15)

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
            response = await self.client.post("/queue", json={"delete": pending_ids}, timeout=15)
            response.raise_for_status()
            # 대기열 조회 후 실행으로 넘어간 요청도 ID 기준으로 다시 확인합니다.
            queue = await self.queue()
        running_ids = [str(item[1]) for item in queue.get("queue_running", []) if str(item[1]) in selected_ids]
        for prompt_id in running_ids:
            await self.cancel_prompt(prompt_id)
