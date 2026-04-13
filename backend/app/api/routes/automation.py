from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.schemas.automation import AutomationRunResponse, AutomationSettingsIn, AutomationSettingsOut
from app.services.automation_service import AutomationBusyError, run_saved_scrape, update_automation_settings
from app.services.scrape_runner import get_or_create_automation_settings
from app.services.scraper import EtimadProtectionError

router = APIRouter(prefix="/automation")


def _serialize(row) -> AutomationSettingsOut:
    payload = AutomationSettingsOut.model_validate(row).model_dump()
    payload.update(
        {
            "timezone": settings.app_timezone,
            "email_ready": settings.fixed_email_enabled,
            "email_recipient": settings.fixed_email_recipient,
        }
    )
    return AutomationSettingsOut(**payload)


@router.get("", response_model=AutomationSettingsOut)
def get_automation_settings(db: Session = Depends(get_db)) -> AutomationSettingsOut:
    return _serialize(get_or_create_automation_settings(db))


@router.put("", response_model=AutomationSettingsOut)
def save_automation_settings(payload: AutomationSettingsIn, db: Session = Depends(get_db)) -> AutomationSettingsOut:
    try:
        row = update_automation_settings(
            db,
            enabled=payload.enabled,
            schedule_mode=payload.schedule_mode,
            interval_hours=payload.interval_hours,
            daily_hour=payload.daily_hour,
            daily_minute=payload.daily_minute,
            keyword=payload.keyword,
            max_pages=payload.max_pages,
            page_size=payload.page_size,
        )
        return _serialize(row)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/run-now", response_model=AutomationRunResponse)
def run_now() -> AutomationRunResponse:
    try:
        return AutomationRunResponse(**run_saved_scrape())
    except AutomationBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except EtimadProtectionError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
