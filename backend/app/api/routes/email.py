from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.email import SendEmailsRequest
from app.services.email_service import send_fixed_recipient_email, send_grouped_emails
from app.services.tender_service import build_email_routing_preview, list_tenders_for_email

router = APIRouter(prefix="")


@router.post("/send-emails")
def send_emails(payload: SendEmailsRequest, db: Session = Depends(get_db)):
    if payload.delivery_mode == "fixed":
        tenders = list_tenders_for_email(db, payload.reference_numbers)
        return send_fixed_recipient_email(
            db=db,
            tenders=tenders,
            subject_prefix=payload.subject_prefix,
            recipient=payload.recipient,
        )

    return send_grouped_emails(
        db=db,
        subject_prefix=payload.subject_prefix,
        reference_numbers=payload.reference_numbers,
        include_fixed_recipient=(payload.delivery_mode == "mapped_with_copy"),
        fixed_recipient=payload.recipient,
    )


@router.get("/email-preview")
def email_preview(reference_numbers: list[str] | None = None, db: Session = Depends(get_db)):
    return build_email_routing_preview(db, reference_numbers)
