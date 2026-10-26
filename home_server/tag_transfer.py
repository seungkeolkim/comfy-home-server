"""태그 교환 JSON과 Import 정책을 DB 변경 전에 검증합니다."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TagImportEntry(BaseModel):
    """태그 본문과 weight를 검증하되 export된 원문은 바꾸지 않습니다."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120, strict=True)
    content: str = Field(min_length=1, max_length=8000, strict=True)
    weight: float = Field(default=1.0, gt=0, allow_inf_nan=False, strict=True)

    @field_validator("name", "content")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        """공백만 있는 입력은 거부하고 정상 원문의 공백과 줄바꿈은 보존합니다."""

        if not value.strip():
            raise ValueError("태그 이름과 본문은 비어 있을 수 없습니다.")
        return value


class TagImportGroup(BaseModel):
    """참조태그가 같은 여러 그룹과 비어 있는 그룹을 허용합니다."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120, strict=True)
    tag_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=64, strict=True)
    tags: list[TagImportEntry]

    @field_validator("name")
    @classmethod
    def reject_blank_group_name(cls, value: str) -> str:
        """공백만 있는 그룹 이름을 DB 변경 전에 거부합니다."""

        if not value.strip():
            raise ValueError("그룹 이름은 비어 있을 수 없습니다.")
        return value


class TagImportDocument(BaseModel):
    """export와 LLM이 작성한 동일 형식의 태그 JSON을 검증합니다."""

    model_config = ConfigDict(extra="forbid")
    format: Literal["comfy-home-server.tags"]
    schema_version: int = Field(ge=1, le=1, strict=True)
    exported_at: datetime | None = None
    groups: list[TagImportGroup]


class TagImportInput(BaseModel):
    """파일 형식을 바꾸지 않고 API 요청에서만 Import 정책을 받습니다."""

    model_config = ConfigDict(extra="forbid")
    mode: Literal["append", "replace"]
    data: TagImportDocument
