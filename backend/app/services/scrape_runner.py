from __future__ import annotations

import asyncio

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.automation_settings import AutomationSettings
from app.models.keyword import Keyword
from app.schemas.tender import ScrapeRequest
from app.services.scrape_service import run_scrape_request


class _SyncBackgroundTasks(BackgroundTasks):
    def __init__(self) -> None:
        super().__init__()

    async def run_all(self) -> None:
        for task in self.tasks:
            result = task.func(*task.args, **task.kwargs)
            if asyncio.iscoroutine(result):
                await result


def get_or_create_automation_settings(db: Session) -> AutomationSettings:
    row = db.get(AutomationSettings, 1)
    if row is None:
        row = AutomationSettings(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    changed = False
    if getattr(row, 'schedule_mode', None) not in {'interval', 'daily_time'}:
        row.schedule_mode = 'interval'
        changed = True
    if row.interval_hours not in {1, 2, 4, 6, 8, 12, 24}:
        row.interval_hours = 1
        changed = True
    if row.max_pages is None:
        row.max_pages = 5
        changed = True
    if row.page_size is None:
        row.page_size = 6
        changed = True
    if changed:
        db.commit()
        db.refresh(row)
    return row


def has_saved_keywords(db: Session) -> bool:
    return db.scalar(select(Keyword.id).limit(1)) is not None


async def run_scrape_flow(*, db: Session, keyword: str, max_pages: int | None, page_size: int | None) -> dict:
    background_tasks = _SyncBackgroundTasks()
    response = await run_scrape_request(
        payload=ScrapeRequest(keyword=keyword, max_pages=max_pages, page_size=page_size),
        db=db,
        background_tasks=background_tasks,
    )
    await background_tasks.run_all()
    data = response.model_dump()
    data['auto_email_sent'] = data.pop('auto_email_queued', False)
    return data
