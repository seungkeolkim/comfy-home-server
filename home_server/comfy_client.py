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
        """실행 중과 대기 중인 ComfyUI 요청을 조회합니다."""

        return await self.request_json("GET", "/queue")

    async def history(self, prompt_id: str) -> dict[str, Any]:
        """한 요청의 완료 기록을 조회합니다."""

        return await self.request_json("GET", f"/history/{prompt_id}")

    async def cancel_pending(self, prompt_id: str) -> None:
        """ComfyUI의 대기열에서 지정한 요청을 제거합니다."""

        response = await self.client.post("/queue", json={"delete": [prompt_id]})
        if response.is_error:
            raise RuntimeError(f"대기 작업 취소 실패: HTTP {response.status_code} {response.text[:500]}")
