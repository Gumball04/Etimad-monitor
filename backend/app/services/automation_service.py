from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.automation_settings import AutomationSettings
from app.schemas.automation import ALLOWED_INTERVALS, ALLOWED_SCHEDULE_MODES
from app.services.scrape_runner import get_or_create_automation_settings, has_saved_keywords, run_scrape_flow
from app.services.scraper import EtimadProtectionError

logger = get_logger("automation-service")

_stop_event = threading.Event()
_thread: threading.Thread | None = None
_running_lock = threading.Lock()


class AutomationBusyError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _local_now() -> datetime:
    return datetime.now(settings.timezone)


def _normalize_last_run(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _mark_result(row: AutomationSettings, *, status: str, error: str | None, run_at: datetime) -> None:
    row.last_run_at = run_at
    row.last_status = status
    row.last_error = error


def _build_success_status(result: dict) -> str:
    return (
        f"success: found={result['total_found']}, saved={result['total_saved']}, "
        f"inserted={result['inserted']}, updated={result['updated']}"
    )


def save_manual_scrape_config(db: Session, *, keyword: str, max_pages: int | None, page_size: int | None) -> AutomationSettings:
    row = get_or_create_automation_settings(db)
    row.keyword = keyword.strip()
    if max_pages is not None:
        row.max_pages = max_pages
    if page_size is not None:
        row.page_size = page_size
    db.commit()
    db.refresh(row)
    return row


def update_automation_settings(
    db: Session,
    *,
    enabled: bool,
    schedule_mode: str,
    interval_hours: int,
    daily_hour: int | None = None,
    daily_minute: int | None = None,
    keyword: str | None = None,
    max_pages: int | None = None,
    page_size: int | None = None,
) -> AutomationSettings:
    if schedule_mode not in ALLOWED_SCHEDULE_MODES:
        raise ValueError(f"schedule_mode must be one of: {', '.join(ALLOWED_SCHEDULE_MODES)}")
    if interval_hours not in ALLOWED_INTERVALS:
        raise ValueError(f"interval_hours must be one of: {', '.join(map(str, ALLOWED_INTERVALS))}")
    if schedule_mode == "daily_time" and (daily_hour is None or daily_minute is None):
        raise ValueError("daily_hour and daily_minute are required when schedule_mode is daily_time")

    row = get_or_create_automation_settings(db)
    row.enabled = enabled
    row.schedule_mode = schedule_mode
    row.interval_hours = interval_hours
    row.daily_hour = daily_hour if schedule_mode == "daily_time" else None
    row.daily_minute = daily_minute if schedule_mode == "daily_time" else None
    if keyword is not None:
        row.keyword = keyword.strip() or None
    if max_pages is not None:
        row.max_pages = max_pages
    if page_size is not None:
        row.page_size = page_size
    db.commit()
    db.refresh(row)
    return row


def run_saved_scrape() -> dict:
    if not _running_lock.acquire(blocking=False):
        raise AutomationBusyError("A scrape job is already running.")

    db = SessionLocal()
    try:
        row = get_or_create_automation_settings(db)
        keyword = (row.keyword or "").strip()
        if not keyword and not has_saved_keywords(db):
            now = _local_now()
            _mark_result(row, status="skipped: no keyword configured", error=None, run_at=now)
            db.commit()
            return {
                "keyword": "",
                "fetched_pages": 0,
                "total_found": 0,
                "total_saved": 0,
                "inserted": 0,
                "updated": 0,
                "new_items_count": 0,
                "auto_email_sent": False,
                "auto_email_recipient": settings.fixed_email_recipient,
                "auto_email_message": "No saved keyword was found.",
                "last_run_at": row.last_run_at,
                "last_status": row.last_status,
                "last_error": row.last_error,
                "items": [],
                "execution_mode": "manual",
                "executed_keywords": [],
                "failed_keywords": [],
            }

        row.last_status = "running"
        row.last_error = None
        db.commit()

        result = asyncio.run(
            run_scrape_flow(
                db=db,
                keyword=keyword,
                max_pages=row.max_pages,
                page_size=row.page_size,
            )
        )

        finished_at = _local_now()
        _mark_result(row, status=_build_success_status(result), error=None, run_at=finished_at)
        db.commit()
        db.refresh(row)
        result.update(
            {
                "last_run_at": row.last_run_at,
                "last_status": row.last_status,
                "last_error": row.last_error,
            }
        )
        return result
    except EtimadProtectionError as exc:
        row = get_or_create_automation_settings(db)
        _mark_result(row, status="failed", error=str(exc), run_at=_local_now())
        db.commit()
        raise
    except Exception as exc:
        row = get_or_create_automation_settings(db)
        _mark_result(row, status="failed", error=str(exc), run_at=_local_now())
        db.commit()
        logger.exception("Automation run failed")
        raise
    finally:
        db.close()
        _running_lock.release()


def _is_due_interval(row: AutomationSettings, now_utc: datetime) -> bool:
    if row.interval_hours not in ALLOWED_INTERVALS:
        return False

    last_run = _normalize_last_run(row.last_run_at)
    if last_run is None:
        return True
    return (now_utc - last_run).total_seconds() >= row.interval_hours * 3600


def _is_due_daily_time(row: AutomationSettings, now_local: datetime) -> bool:
    if row.daily_hour is None or row.daily_minute is None:
        return False
    if (now_local.hour, now_local.minute) < (row.daily_hour, row.daily_minute):
        return False

    last_run = _normalize_last_run(row.last_run_at)
    if last_run is None:
        return True

    last_run_local = last_run.astimezone(settings.timezone)
    today_target = now_local.replace(hour=row.daily_hour, minute=row.daily_minute, second=0, microsecond=0)
    return last_run_local < today_target


def _is_due(row: AutomationSettings) -> bool:
    if not row.enabled:
        return False

    schedule_mode = getattr(row, "schedule_mode", "interval") or "interval"
    if schedule_mode == "daily_time":
        return _is_due_daily_time(row, _local_now())
    return _is_due_interval(row, _utcnow())


def _loop() -> None:
    logger.info("Automation loop started | timezone=%s", settings.app_timezone)
    while not _stop_event.is_set():
        db = SessionLocal()
        try:
            row = get_or_create_automation_settings(db)
            due = _is_due(row)
        except Exception:
            logger.exception("Automation scheduler check failed")
            due = False
        finally:
            db.close()

        if due:
            try:
                run_saved_scrape()
            except AutomationBusyError:
                logger.info("Automation run skipped because another scrape job is already running")
            except Exception:
                logger.exception("Automation run failed")

        _stop_event.wait(30)
    logger.info("Automation loop stopped")


def start_automation_loop() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="etimad-automation-loop")
    _thread.start()


def stop_automation_loop() -> None:
    global _thread
    _stop_event.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=2)
    _thread = None


from app.db.session import SessionLocal
