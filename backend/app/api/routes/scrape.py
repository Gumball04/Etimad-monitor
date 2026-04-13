from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.tender import ScrapeRequest, ScrapeResponse
from app.services.automation_service import save_manual_scrape_config
from app.services.scrape_service import run_scrape_request
from app.services.scraper import EtimadProtectionError

router = APIRouter(prefix="")


@router.post("/scrape", response_model=ScrapeResponse)
async def scrape_tenders(
    payload: ScrapeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ScrapeResponse:
    save_manual_scrape_config(
        db,
        keyword=payload.keyword,
        max_pages=payload.max_pages,
        page_size=payload.page_size,
    )
    try:
        return await run_scrape_request(
            payload=payload,
            db=db,
            background_tasks=background_tasks,
        )
    except EtimadProtectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
