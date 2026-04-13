from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


def normalize_keyword(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Keyword cannot be empty")
    return normalized


class KeywordCreate(BaseModel):
    keyword: str

    @field_validator("keyword")
    @classmethod
    def validate_keyword(cls, value: str) -> str:
        return normalize_keyword(value)


class KeywordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    keyword: str
    created_at: datetime


class KeywordDeleteResponse(BaseModel):
    deleted: bool = True
    id: int
