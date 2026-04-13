from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AutomationSettings(Base):
    __tablename__ = 'automation_settings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default='false')
    schedule_mode: Mapped[str] = mapped_column(String(20), nullable=False, default='interval', server_default='interval')
    interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default='1')
    daily_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    keyword: Mapped[str | None] = mapped_column(String(255), nullable=True)
    max_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default='5')
    page_size: Mapped[int] = mapped_column(Integer, nullable=False, default=6, server_default='6')
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
