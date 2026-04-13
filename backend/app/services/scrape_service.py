from dataclasses import dataclass
from typing import Any

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.models.keyword import Keyword
from app.schemas.tender import ScrapeKeywordFailure, ScrapeRequest, ScrapeResponse
from app.services.email_service import send_fixed_recipient_email, send_fixed_recipient_keyword_exports_email
from app.services.scraper import EtimadProtectionError, EtimadScraper
from app.services.tender_service import dedupe_tender_items, upsert_tenders

logger = get_logger("scrape-service")


@dataclass
class SingleKeywordScrapeResult:
    keyword: str
    fetched_pages: int
    total_found: int
    items: list[dict[str, Any]]


def _send_new_tenders_email_background(tender_ids: list[int], subject_prefix: str) -> None:
    unique_tender_ids = list(dict.fromkeys(tender_ids))
    if not unique_tender_ids:
        return

    db = SessionLocal()
    try:
        from app.models.tender import Tender

        tenders = db.query(Tender).filter(Tender.id.in_(unique_tender_ids)).all()
        if tenders:
            send_fixed_recipient_email(
                db=db,
                tenders=tenders,
                subject_prefix=subject_prefix,
            )
    except Exception as exc:
        logger.error("Automatic email delivery failed | tender_ids=%s | error=%s", unique_tender_ids, exc)
    finally:
        db.close()


def _send_keyword_exports_email_background(
    tender_ids: list[int],
    subject_prefix: str,
    keyword_exports: list[dict[str, object]],
) -> None:
    unique_tender_ids = list(dict.fromkeys(tender_ids))
    if not unique_tender_ids:
        return

    db = SessionLocal()
    try:
        from app.models.tender import Tender

        tenders = db.query(Tender).filter(Tender.id.in_(unique_tender_ids)).all()
        if tenders:
            send_fixed_recipient_keyword_exports_email(
                db=db,
                tenders=tenders,
                keyword_exports=keyword_exports,
                subject_prefix=subject_prefix,
            )
    except Exception as exc:
        logger.error("Keyword export email delivery failed | tender_ids=%s | error=%s", unique_tender_ids, exc)
    finally:
        db.close()


def list_saved_keywords(db: Session) -> list[str]:
    return list(
        db.scalars(select(Keyword.keyword).order_by(Keyword.created_at.asc(), Keyword.id.asc())).all()
    )


def _build_subject_prefix(execution_mode: str, executed_keywords: list[str], manual_keyword: str) -> str:
    if execution_mode == "manual":
        return f"منافسات جديدة - {manual_keyword}"
    if len(executed_keywords) == 1:
        return f"منافسات جديدة - {executed_keywords[0]}"
    return "منافسات جديدة - تشغيل متعدد الكلمات المفتاحية"


def _build_auto_email_message(
    *,
    auto_email_queued: bool,
    new_items_count: int,
    execution_mode: str,
) -> str | None:
    if auto_email_queued:
        if execution_mode == "saved-keywords":
            return "Automatic email was queued once with separate Excel files for each executed keyword."
        return None
    if new_items_count > 0:
        return "Automatic email was skipped because SMTP or FIXED_EMAIL_RECIPIENT is not fully configured."
    return "No new tenders were added, so no automatic email was queued."


def _queue_auto_email(
    *,
    new_item_ids: list[int],
    background_tasks: BackgroundTasks,
    subject_prefix: str,
    log_keyword: str,
    execution_mode: str,
    keyword_exports: list[dict[str, object]] | None = None,
) -> tuple[bool, str | None]:
    unique_ids = list(dict.fromkeys(new_item_ids))
    auto_email_recipient = settings.fixed_email_recipient if settings.fixed_email_enabled else None

    if unique_ids and settings.fixed_email_enabled:
        if execution_mode == "saved-keywords" and keyword_exports:
            background_tasks.add_task(
                _send_keyword_exports_email_background,
                unique_ids,
                subject_prefix,
                keyword_exports,
            )
        else:
            background_tasks.add_task(
                _send_new_tenders_email_background,
                unique_ids,
                subject_prefix,
            )
        return True, auto_email_recipient

    if unique_ids:
        logger.warning(
            "Automatic email skipped | keyword=%s | inserted=%s | fixed_recipient=%s | smtp_enabled=%s",
            log_keyword,
            len(unique_ids),
            settings.fixed_email_recipient,
            settings.smtp_enabled,
        )

    return False, auto_email_recipient


def _finalize_scrape_response(
    *,
    raw_items: list[dict[str, Any]],
    fetched_pages: int,
    executed_keywords: list[str],
    failed_keywords: list[ScrapeKeywordFailure],
    execution_mode: str,
    manual_keyword: str,
    keyword_exports: list[dict[str, object]] | None,
    db: Session,
    background_tasks: BackgroundTasks,
) -> ScrapeResponse:
    final_items = dedupe_tender_items(raw_items)
    result = upsert_tenders(db, final_items)
    new_items = result.get("new_items") or []
    new_item_ids = [item.id for item in new_items if getattr(item, "id", None)]
    subject_prefix = _build_subject_prefix(execution_mode, executed_keywords, manual_keyword)
    auto_email_queued, auto_email_recipient = _queue_auto_email(
        new_item_ids=new_item_ids,
        background_tasks=background_tasks,
        subject_prefix=subject_prefix,
        log_keyword=manual_keyword or ",".join(executed_keywords) or "saved-keywords",
        execution_mode=execution_mode,
        keyword_exports=keyword_exports,
    )

    logger.info(
        "Scrape run finalized | mode=%s | executed=%s | failed=%s | final_items=%s | inserted=%s | updated=%s",
        execution_mode,
        len(executed_keywords),
        len(failed_keywords),
        len(final_items),
        result["inserted"],
        result["updated"],
    )

    response_keyword = manual_keyword or (executed_keywords[0] if len(executed_keywords) == 1 else "")

    return ScrapeResponse(
        keyword=response_keyword,
        fetched_pages=fetched_pages,
        total_found=len(final_items),
        total_saved=result["total_saved"],
        inserted=result["inserted"],
        updated=result["updated"],
        new_items_count=len(new_items),
        auto_email_queued=auto_email_queued,
        auto_email_recipient=auto_email_recipient,
        auto_email_message=_build_auto_email_message(
            auto_email_queued=auto_email_queued,
            new_items_count=len(new_items),
            execution_mode=execution_mode,
        ),
        items=final_items,
        execution_mode=execution_mode,
        executed_keywords=executed_keywords,
        failed_keywords=failed_keywords,
    )


async def run_single_keyword_scrape(
    *,
    keyword: str,
    max_pages: int | None,
    page_size: int | None,
) -> SingleKeywordScrapeResult:
    normalized_keyword = keyword.strip()
    if not normalized_keyword:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Keyword is required when there are no saved keywords.",
        )

    scraper = EtimadScraper(
        keyword=normalized_keyword,
        max_pages=max_pages,
        page_size=page_size,
    )
    items, pages = await scraper.scrape()
    deduped_items = dedupe_tender_items(items)

    return SingleKeywordScrapeResult(
        keyword=normalized_keyword,
        fetched_pages=pages,
        total_found=len(deduped_items),
        items=deduped_items,
    )


async def run_scrape_request(
    *,
    payload: ScrapeRequest,
    db: Session,
    background_tasks: BackgroundTasks,
) -> ScrapeResponse:
    saved_keywords = list_saved_keywords(db)

    if not saved_keywords:
        result = await run_single_keyword_scrape(
            keyword=payload.keyword,
            max_pages=payload.max_pages,
            page_size=payload.page_size,
        )
        return _finalize_scrape_response(
            raw_items=result.items,
            fetched_pages=result.fetched_pages,
            executed_keywords=[result.keyword],
            failed_keywords=[],
            execution_mode="manual",
            manual_keyword=result.keyword,
            keyword_exports=None,
            db=db,
            background_tasks=background_tasks,
        )

    fetched_pages = 0
    executed_keywords: list[str] = []
    failed_keywords: list[ScrapeKeywordFailure] = []
    raw_items: list[dict[str, Any]] = []
    keyword_exports: list[dict[str, object]] = []

    for saved_keyword in saved_keywords:
        try:
            result = await run_single_keyword_scrape(
                keyword=saved_keyword,
                max_pages=payload.max_pages,
                page_size=payload.page_size,
            )
        except EtimadProtectionError as exc:
            db.rollback()
            logger.warning("Saved keyword scrape failed | keyword=%s | error=%s", saved_keyword, exc)
            failed_keywords.append(ScrapeKeywordFailure(keyword=saved_keyword, error=str(exc)))
            continue
        except HTTPException as exc:
            db.rollback()
            logger.warning(
                "Saved keyword scrape failed | keyword=%s | status=%s | detail=%s",
                saved_keyword,
                exc.status_code,
                exc.detail,
            )
            failed_keywords.append(ScrapeKeywordFailure(keyword=saved_keyword, error=str(exc.detail)))
            continue
        except Exception as exc:
            db.rollback()
            logger.exception("Saved keyword scrape failed unexpectedly | keyword=%s", saved_keyword)
            failed_keywords.append(ScrapeKeywordFailure(keyword=saved_keyword, error=str(exc)))
            continue

        executed_keywords.append(result.keyword)
        fetched_pages += result.fetched_pages
        raw_items.extend(result.items)
        keyword_exports.append({"keyword": result.keyword, "items": result.items})

    return _finalize_scrape_response(
        raw_items=raw_items,
        fetched_pages=fetched_pages,
        executed_keywords=executed_keywords,
        failed_keywords=failed_keywords,
        execution_mode="saved-keywords",
        manual_keyword=payload.keyword,
        keyword_exports=keyword_exports,
        db=db,
        background_tasks=background_tasks,
    )
