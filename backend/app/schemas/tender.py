from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TenderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tender_title: str | None = None
    tender_number: str | None = None
    reference_number: str
    purpose: str | None = None
    document_fee: str | None = None
    status: str | None = None
    contract_duration: str | None = None
    insurance_required: str | None = None
    tender_type: str | None = None
    government_entity: str | None = None
    remaining_time: str | None = None
    submission_method: str | None = None
    initial_guarantee: str | None = None
    classification_field: str | None = None
    activity: str | None = None
    tender_url: str | None = None
    created_at: datetime
    updated_at: datetime


class ScrapeRequest(BaseModel):
    keyword: str = ""
    max_pages: int | None = Field(default=None, ge=1, le=50)
    page_size: int | None = Field(default=None, ge=1, le=100)

    @field_validator("keyword", mode="before")
    @classmethod
    def normalize_keyword(cls, value: str | None) -> str:
        if value is None:
            return ""
        return value.strip()


class ScrapeKeywordFailure(BaseModel):
    keyword: str
    error: str


class ScrapeResponse(BaseModel):
    keyword: str
    fetched_pages: int
    total_found: int
    total_saved: int
    inserted: int
    updated: int
    new_items_count: int
    auto_email_queued: bool
    auto_email_recipient: str | None = None
    auto_email_message: str | None = None
    items: list[dict[str, Any]]
    execution_mode: str = "manual"
    executed_keywords: list[str] = Field(default_factory=list)
    failed_keywords: list[ScrapeKeywordFailure] = Field(default_factory=list)
