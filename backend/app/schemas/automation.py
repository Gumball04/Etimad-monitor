from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ALLOWED_INTERVALS = (1, 2, 4, 6, 8, 12, 24)
ALLOWED_SCHEDULE_MODES = ('interval', 'daily_time')


class AutomationSettingsIn(BaseModel):
    enabled: bool = False
    schedule_mode: str = Field(default='interval')
    interval_hours: int = Field(default=1)
    daily_hour: int | None = Field(default=None, ge=0, le=23)
    daily_minute: int | None = Field(default=None, ge=0, le=59)
    keyword: str | None = Field(default=None, max_length=255)
    max_pages: int | None = Field(default=None, ge=1, le=50)
    page_size: int | None = Field(default=None, ge=1, le=100)

    @field_validator("schedule_mode")
    @classmethod
    def validate_schedule_mode(cls, value: str) -> str:
        if value not in ALLOWED_SCHEDULE_MODES:
            raise ValueError(f"schedule_mode must be one of: {', '.join(ALLOWED_SCHEDULE_MODES)}")
        return value

    @field_validator("interval_hours")
    @classmethod
    def validate_interval(cls, value: int) -> int:
        if value not in ALLOWED_INTERVALS:
            raise ValueError(f"interval_hours must be one of: {', '.join(map(str, ALLOWED_INTERVALS))}")
        return value

    @field_validator("keyword", mode="before")
    @classmethod
    def normalize_keyword(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode='after')
    def validate_mode_specific_fields(self):
        if self.schedule_mode == 'daily_time' and (self.daily_hour is None or self.daily_minute is None):
            raise ValueError('daily_hour and daily_minute are required when schedule_mode is daily_time')
        return self


class AutomationSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    enabled: bool = False
    schedule_mode: str = 'interval'
    interval_hours: int = 1
    daily_hour: int | None = None
    daily_minute: int | None = None
    keyword: str | None = None
    max_pages: int | None = 5
    page_size: int | None = 6
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None
    updated_at: datetime | None = None
    timezone: str = 'Asia/Amman'
    email_ready: bool = False
    email_recipient: str | None = None


class AutomationRunResponse(BaseModel):
    keyword: str
    fetched_pages: int
    total_found: int
    total_saved: int
    inserted: int
    updated: int
    new_items_count: int
    auto_email_sent: bool
    auto_email_recipient: str | None = None
    auto_email_message: str | None = None
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None
    items: list[dict[str, Any]]
