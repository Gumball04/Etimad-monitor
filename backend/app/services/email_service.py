from collections import defaultdict
from datetime import datetime, timezone
from email.message import EmailMessage
from html import escape
from io import BytesIO
import re
import smtplib
from uuid import uuid4

import pandas as pd
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.logging import get_logger
from app.models.entity_contact_map import EntityContactMap
from app.models.tender import Tender
from app.models.tender_email_delivery import TenderEmailDelivery
from app.services.tender_service import TENDER_COLUMNS_AR, dedupe_tender_records, is_ended_tender_record
from app.utils.text import contains_digit, normalize_for_comparison, normalize_space

logger = get_logger("email")

EXCEL_EXPORT_FIELDS = [
    "tender_title",
    "tender_number",
    "reference_number",
    "purpose",
    "document_fee",
    "status",
    "contract_duration",
    "insurance_required",
    "tender_type",
    "government_entity",
    "remaining_time",
    "submission_method",
    "initial_guarantee",
    "classification_field",
    "activity",
    "tender_url",
]


class EmailConfigurationError(RuntimeError):
    pass


def _safe(value) -> str:
    if value is None:
        return "غير متوفر"
    text = str(value).strip()
    return text if text else "غير متوفر"


def _safe_html(value) -> str:
    return escape(_safe(value))


def _clean_field_value(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _iter_email_detail_rows(tender: Tender) -> list[tuple[str, str]]:
    purpose = _clean_field_value(tender.purpose)
    purpose_key = normalize_for_comparison(purpose)

    rows: list[tuple[str, str]] = []
    candidates = [
        ("رقم المنافسة", tender.tender_number),
        ("الرقم المرجعي", tender.reference_number),
        ("الجهة الحكومية", tender.government_entity),
        ("الغرض من المنافسة", purpose),
        ("قيمة وثائق المنافسة", tender.document_fee),
        ("حالة المنافسة", tender.status),
        ("الوقت المتبقي", tender.remaining_time),
        ("مدة العقد", tender.contract_duration),
        ("هل التأمين من متطلبات المنافسة", tender.insurance_required),
        ("نوع المنافسة", tender.tender_type),
        ("طريقة تقديم العروض", tender.submission_method),
        ("مطلوب ضمان ابتدائي", tender.initial_guarantee),
        ("مجال التصنيف", tender.classification_field),
        ("نشاط المنافسة", tender.activity),
    ]

    for label, raw_value in candidates:
        value = _clean_field_value(raw_value)
        if not value:
            continue
        if label == "الوقت المتبقي" and not contains_digit(value):
            continue
        if label == "مدة العقد":
            if purpose_key and normalize_for_comparison(value) == purpose_key:
                continue
            if len(value) > 120 and not contains_digit(value):
                continue
        rows.append((label, value))

    if tender.tender_url:
        rows.append(("الرابط", str(tender.tender_url).strip()))

    return rows


def _build_tenders_excel_bytes(tenders: list[Tender]) -> bytes:
    tenders = dedupe_tender_records(tenders)
    rows = []
    for tender in tenders:
        rows.append(
            {
                "اسم المنافسة": tender.tender_title,
                "رقم المنافسة": tender.tender_number,
                "الرقم المرجعي": tender.reference_number,
                "الغرض من المنافسة": tender.purpose,
                "قيمة وثائق المنافسة": tender.document_fee,
                "حالة المنافسة": tender.status,
                "مدة العقد": tender.contract_duration,
                "هل التأمين من متطلبات المنافسة": tender.insurance_required,
                "نوع المنافسة": tender.tender_type,
                "الجهة الحكومية": tender.government_entity,
                "الوقت المتبقي": tender.remaining_time,
                "طريقة تقديم العروض": tender.submission_method,
                "مطلوب ضمان الابتدائي": tender.initial_guarantee,
                "مجال التصنيف": tender.classification_field,
                "نشاط المنافسة": tender.activity,
                "رابط المنافسة": tender.tender_url,
            }
        )

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="المنافسات")
    output.seek(0)
    return output.getvalue()


def _build_keyword_items_excel_bytes(items: list[dict]) -> bytes:
    rows = []
    for item in items:
        rows.append(
            {
                TENDER_COLUMNS_AR[field_name]: item.get(field_name)
                for field_name in EXCEL_EXPORT_FIELDS
            }
        )

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name="المنافسات")
    output.seek(0)
    return output.getvalue()


def _build_keyword_attachment_filename(keyword: str) -> str:
    safe_keyword = normalize_space(keyword) or "keyword"
    safe_keyword = re.sub(r"\s+", "_", safe_keyword)
    safe_keyword = re.sub(r'[\\/:*?"<>|]+', "", safe_keyword)
    safe_keyword = safe_keyword.strip("._")
    if not safe_keyword:
        safe_keyword = "keyword"
    return f"tenders_{safe_keyword}.xlsx"


def _build_tender_text_block(tender: Tender) -> str:
    lines = [f"اسم المنافسة: {_safe(tender.tender_title)}"]
    lines.extend(f"{label}: {_safe(value)}" for label, value in _iter_email_detail_rows(tender))
    return "\n".join(lines)


def _build_plain_text_email(tenders: list[Tender]) -> str:
    tenders = dedupe_tender_records(tenders)
    lines = [
        "مرحباً،",
        "",
        "تم اكتشاف منافسات جديدة على منصة اعتماد.",
        "أدناه تفاصيل المنافسات الجديدة، ومرفق أيضاً ملف Excel يحتوي على نفس البيانات.",
        "",
        f"عدد المنافسات: {len(tenders)}",
        "",
        "=" * 80,
    ]
    for index, tender in enumerate(tenders, start=1):
        lines.extend(
            [
                f"المنافسة رقم {index}",
                "-" * 80,
                _build_tender_text_block(tender),
                "=" * 80,
            ]
        )
    return "\n".join(lines)


def _build_tender_html_block(tender: Tender) -> str:
    url = str(tender.tender_url).strip() if tender.tender_url else ""
    link_html = (
        f'<a href="{escape(url)}" '
        'style="color:#2563eb;text-decoration:none;font-weight:bold;" '
        'target="_blank">فتح المنافسة</a>'
        if url
        else "غير متوفر"
    )
    rows = []
    for label, value in _iter_email_detail_rows(tender):
        rendered_value = link_html if label == "الرابط" and url else _safe_html(value)
        rows.append(
            f'<tr><td style="padding:6px 0;font-weight:bold;width:220px;color:#374151;">{escape(label)}:</td>'
            f'<td style="padding:6px 0;color:#111827;">{rendered_value}</td></tr>'
        )
    rows_html = "\n        ".join(rows)

    return f"""
    <div style="border:1px solid #e5e7eb;border-radius:14px;padding:18px;margin-bottom:18px;background:#ffffff;">
      <h2 style="margin:0 0 14px 0;font-size:20px;line-height:1.6;color:#111827;">
        {_safe_html(tender.tender_title)}
      </h2>
      <table style="width:100%;border-collapse:collapse;font-size:14px;line-height:1.9;">
        {rows_html}
      </table>
    </div>
    """.strip()


def _build_html_email(tenders: list[Tender], subject_prefix: str) -> str:
    tenders = dedupe_tender_records(tenders)
    cards = "\n".join(_build_tender_html_block(tender) for tender in tenders)
    return f"""
    <html lang="ar" dir="rtl">
      <head><meta charset="UTF-8" /></head>
      <body style="margin:0;padding:24px;background:#f3f4f6;font-family:Tahoma,Arial,sans-serif;color:#111827;">
        <div style="max-width:950px;margin:0 auto;">
          <div style="background:#0f172a;color:#ffffff;padding:22px;border-radius:16px;margin-bottom:20px;">
            <h1 style="margin:0 0 10px 0;font-size:24px;">{_safe_html(subject_prefix)}</h1>
            <p style="margin:0;font-size:15px;line-height:1.8;">تم اكتشاف منافسات جديدة على منصة اعتماد.</p>
            <p style="margin:8px 0 0 0;font-size:15px;line-height:1.8;">عدد المنافسات: <strong>{len(tenders)}</strong></p>
            <p style="margin:8px 0 0 0;font-size:14px;line-height:1.8;opacity:0.95;">مرفق مع هذا الإيميل ملف Excel يحتوي على جميع المنافسات.</p>
          </div>
          {cards}
        </div>
      </body>
    </html>
    """.strip()


def _validate_email_settings(recipient: str | None) -> str:
    recipient = (recipient or settings.fixed_email_recipient or "").strip()
    if not recipient:
        raise EmailConfigurationError("FIXED_EMAIL_RECIPIENT is not configured.")
    if not settings.smtp_host:
        raise EmailConfigurationError("SMTP_HOST is not configured.")
    if not settings.smtp_from:
        raise EmailConfigurationError("SMTP_FROM is not configured.")
    if not settings.smtp_username or not settings.smtp_password:
        raise EmailConfigurationError("SMTP credentials are not configured.")
    return recipient


def _list_delivery_rows(
    db: Session,
    tenders: list[Tender],
    recipient: str,
) -> dict[int, TenderEmailDelivery]:
    tender_ids = [tender.id for tender in tenders if tender.id is not None]
    if not tender_ids:
        return {}

    rows = db.scalars(
        select(TenderEmailDelivery).where(
            TenderEmailDelivery.tender_id.in_(tender_ids),
            TenderEmailDelivery.recipient_email == recipient,
        )
    ).all()
    return {row.tender_id: row for row in rows}


def _reserve_deliveries(
    db: Session,
    tenders: list[Tender],
    recipient: str,
    contact_id: int | None,
    batch_id: str,
    retry_on_conflict: bool = True,
) -> tuple[list[Tender], list[TenderEmailDelivery]]:
    existing = _list_delivery_rows(db, tenders, recipient)
    deliverable: list[Tender] = []
    deliveries: list[TenderEmailDelivery] = []

    for tender in tenders:
        if tender.id is None or is_ended_tender_record(tender):
            continue

        delivery = existing.get(tender.id)
        if delivery and delivery.status in {"pending", "sent"}:
            continue

        if delivery:
            delivery.status = "pending"
            delivery.batch_id = batch_id
            delivery.contact_id = contact_id
            delivery.sent_at = None
            delivery.error_message = None
        else:
            delivery = TenderEmailDelivery(
                tender_id=tender.id,
                contact_id=contact_id,
                recipient_email=recipient,
                batch_id=batch_id,
                status="pending",
            )
            db.add(delivery)

        deliverable.append(tender)
        deliveries.append(delivery)

    if not deliverable:
        return [], []

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if retry_on_conflict:
            return _reserve_deliveries(
                db=db,
                tenders=tenders,
                recipient=recipient,
                contact_id=contact_id,
                batch_id=batch_id,
                retry_on_conflict=False,
            )
        raise

    return deliverable, deliveries


def _mark_deliveries_sent(
    db: Session,
    tenders: list[Tender],
    deliveries: list[TenderEmailDelivery],
    sent_at: datetime,
) -> None:
    for delivery in deliveries:
        delivery.status = "sent"
        delivery.sent_at = sent_at
        delivery.error_message = None

    for tender in tenders:
        tender.email_sent = True
        tender.email_sent_at = sent_at

    db.commit()


def _mark_deliveries_failed(db: Session, deliveries: list[TenderEmailDelivery], error: Exception) -> None:
    message = str(error).strip() or error.__class__.__name__
    for delivery in deliveries:
        delivery.status = "failed"
        delivery.error_message = message[:1000]

    try:
        db.commit()
    except Exception:
        db.rollback()


def _send_message_with_server(server: smtplib.SMTP, msg: EmailMessage) -> None:
    if settings.smtp_username and settings.smtp_password:
        server.login(settings.smtp_username, settings.smtp_password)
    server.send_message(msg)


def _send_via_starttls(msg: EmailMessage) -> None:
    server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds)
    try:
        server.ehlo()
        if settings.smtp_use_tls:
            server.starttls()
            server.ehlo()
        _send_message_with_server(server, msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def _send_via_ssl(msg: EmailMessage) -> None:
    port = settings.smtp_port if settings.smtp_use_ssl else settings.smtp_ssl_port
    server = smtplib.SMTP_SSL(settings.smtp_host, port, timeout=settings.smtp_timeout_seconds)
    try:
        server.ehlo()
        _send_message_with_server(server, msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def _send_message(msg: EmailMessage) -> None:
    if settings.smtp_use_ssl:
        _send_via_ssl(msg)
        return

    try:
        _send_via_starttls(msg)
    except (TimeoutError, OSError, smtplib.SMTPServerDisconnected) as exc:
        if not settings.smtp_ssl_fallback:
            raise
        logger.warning(
            "Primary SMTP connection failed; retrying with SSL | host=%s | port=%s | error=%s",
            settings.smtp_host,
            settings.smtp_port,
            exc,
        )
        _send_via_ssl(msg)


def _build_message(tenders: list[Tender], recipient: str, subject_prefix: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject_prefix
    msg["From"] = settings.smtp_from
    msg["To"] = recipient
    msg.set_content(_build_plain_text_email(tenders))
    msg.add_alternative(_build_html_email(tenders, subject_prefix), subtype="html")
    msg.add_attachment(
        _build_tenders_excel_bytes(tenders),
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="etimad_new_tenders.xlsx",
    )
    return msg


def _build_keyword_exports_message(
    recipient: str,
    subject_prefix: str,
    keyword_exports: list[dict[str, object]],
) -> EmailMessage:
    attachment_lines = [
        f"- {attachment['filename']}"
        for attachment in keyword_exports
    ]
    attachment_lines_text = "\n".join(attachment_lines) if attachment_lines else "- لا توجد ملفات"
    attachment_lines_html = "".join(
        f"<li>{escape(str(attachment['filename']))}</li>"
        for attachment in keyword_exports
    )

    plain_text = "\n".join(
        [
            "مرحباً،",
            "",
            "تم تشغيل البحث على عدة كلمات مفتاحية في منصة اعتماد.",
            "ستجد في المرفقات ملف Excel مستقلاً لكل كلمة مفتاحية تم تنفيذها.",
            "",
            "الملفات المرفقة:",
            attachment_lines_text,
        ]
    )

    html_text = f"""
    <html lang="ar" dir="rtl">
      <head><meta charset="UTF-8" /></head>
      <body style="margin:0;padding:24px;background:#f3f4f6;font-family:Tahoma,Arial,sans-serif;color:#111827;">
        <div style="max-width:950px;margin:0 auto;">
          <div style="background:#0f172a;color:#ffffff;padding:22px;border-radius:16px;margin-bottom:20px;">
            <h1 style="margin:0 0 10px 0;font-size:24px;">{_safe_html(subject_prefix)}</h1>
            <p style="margin:0;font-size:15px;line-height:1.8;">تم تشغيل البحث على عدة كلمات مفتاحية في منصة اعتماد.</p>
            <p style="margin:8px 0 0 0;font-size:14px;line-height:1.8;opacity:0.95;">كل مرفق يمثل نتائج كلمة مفتاحية مستقلة.</p>
          </div>
          <div style="border:1px solid #e5e7eb;border-radius:14px;padding:18px;background:#ffffff;">
            <h2 style="margin:0 0 12px 0;font-size:18px;color:#111827;">الملفات المرفقة</h2>
            <ul style="margin:0;padding-right:20px;line-height:1.9;color:#374151;">
              {attachment_lines_html or "<li>لا توجد ملفات</li>"}
            </ul>
          </div>
        </div>
      </body>
    </html>
    """.strip()

    msg = EmailMessage()
    msg["Subject"] = subject_prefix
    msg["From"] = settings.smtp_from
    msg["To"] = recipient
    msg.set_content(plain_text)
    msg.add_alternative(html_text, subtype="html")

    for attachment in keyword_exports:
        msg.add_attachment(
            attachment["content"],
            maintype="application",
            subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=str(attachment["filename"]),
        )

    return msg


def _build_recipient_buckets(
    db: Session,
    tenders: list[Tender],
    include_fixed_recipient: bool,
    fixed_recipient: str | None,
) -> tuple[dict[str, dict], list[str]]:
    tenders = dedupe_tender_records(tenders)
    mappings = list(
        db.scalars(
            select(EntityContactMap).options(joinedload(EntityContactMap.entity), joinedload(EntityContactMap.contact))
        ).all()
    )

    entity_to_contacts: dict[str, dict[str, object]] = defaultdict(dict)
    for mapping in mappings:
        if not mapping.entity or not mapping.contact or not mapping.contact.is_active:
            continue
        entity_to_contacts[mapping.entity.entity_name_ar][mapping.contact.email] = mapping.contact

    buckets: dict[str, dict] = {}
    unrouted_reference_numbers: list[str] = []

    for tender in tenders:
        contacts = entity_to_contacts.get(tender.government_entity or "", {})
        if not contacts:
            unrouted_reference_numbers.append(tender.reference_number)

        for email, contact in contacts.items():
            bucket = buckets.setdefault(
                email,
                {
                    "contact": contact,
                    "tenders": [],
                },
            )
            bucket["tenders"].append(tender)

    if include_fixed_recipient and fixed_recipient:
        fixed_bucket = buckets.setdefault(
            fixed_recipient,
            {
                "contact": None,
                "tenders": [],
            },
        )
        seen_ids = {tender.id for tender in fixed_bucket["tenders"]}
        for tender in tenders:
            if tender.id not in seen_ids:
                fixed_bucket["tenders"].append(tender)

    return buckets, sorted(set(unrouted_reference_numbers))


def send_new_tenders_email(
    db: Session,
    tenders: list[Tender],
    recipient: str | None = None,
    subject_prefix: str = "تنبيه منافسات جديدة من اعتماد",
    contact_id: int | None = None,
) -> dict:
    tenders = dedupe_tender_records(tenders)
    recipient = _validate_email_settings(recipient)
    batch_id = uuid4().hex
    deliverable, deliveries = _reserve_deliveries(
        db=db,
        tenders=tenders,
        recipient=recipient,
        contact_id=contact_id,
        batch_id=batch_id,
    )
    if not deliverable:
        return {
            "emails_sent": 0,
            "recipient": recipient,
            "reference_numbers": [],
            "message": "No new unsent tenders to email.",
        }

    message = _build_message(deliverable, recipient, subject_prefix)

    try:
        _send_message(message)
    except Exception as exc:
        logger.error("Email delivery failed | recipient=%s | error=%s", recipient, exc)
        _mark_deliveries_failed(db, deliveries, exc)
        raise

    sent_at = datetime.now(timezone.utc)
    _mark_deliveries_sent(db, deliverable, deliveries, sent_at)
    logger.info("Email delivered | recipient=%s | count=%s", recipient, len(deliverable))

    return {
        "emails_sent": len(deliverable),
        "recipient": recipient,
        "reference_numbers": [tender.reference_number for tender in deliverable],
        "attachment_filename": "etimad_new_tenders.xlsx",
        "batch_id": batch_id,
    }


def send_fixed_recipient_email(
    db: Session,
    tenders: list[Tender],
    subject_prefix: str,
    recipient: str | None = None,
) -> dict:
    return send_new_tenders_email(
        db=db,
        tenders=tenders,
        recipient=recipient or settings.fixed_email_recipient,
        subject_prefix=subject_prefix,
    )


def send_fixed_recipient_keyword_exports_email(
    db: Session,
    tenders: list[Tender],
    keyword_exports: list[dict[str, object]],
    subject_prefix: str,
    recipient: str | None = None,
) -> dict:
    tenders = dedupe_tender_records(tenders)
    recipient = _validate_email_settings(recipient or settings.fixed_email_recipient)
    batch_id = uuid4().hex
    deliverable, deliveries = _reserve_deliveries(
        db=db,
        tenders=tenders,
        recipient=recipient,
        contact_id=None,
        batch_id=batch_id,
    )
    if not deliverable:
        return {
            "emails_sent": 0,
            "recipient": recipient,
            "reference_numbers": [],
            "message": "No new unsent tenders to email.",
        }

    attachments = []
    for keyword_export in keyword_exports:
        keyword = str(keyword_export.get("keyword") or "").strip()
        items = keyword_export.get("items") or []
        attachments.append(
            {
                "filename": _build_keyword_attachment_filename(keyword),
                "content": _build_keyword_items_excel_bytes(items),
            }
        )

    message = _build_keyword_exports_message(
        recipient=recipient,
        subject_prefix=subject_prefix,
        keyword_exports=attachments,
    )

    try:
        _send_message(message)
    except Exception as exc:
        logger.error("Keyword export email delivery failed | recipient=%s | error=%s", recipient, exc)
        _mark_deliveries_failed(db, deliveries, exc)
        raise

    sent_at = datetime.now(timezone.utc)
    _mark_deliveries_sent(db, deliverable, deliveries, sent_at)
    logger.info("Keyword export email delivered | recipient=%s | files=%s", recipient, len(attachments))

    return {
        "emails_sent": 1,
        "recipient": recipient,
        "reference_numbers": [tender.reference_number for tender in deliverable],
        "attachment_filenames": [attachment["filename"] for attachment in attachments],
        "batch_id": batch_id,
    }


def send_grouped_emails(
    db: Session,
    subject_prefix: str,
    reference_numbers: list[str] | None = None,
    include_fixed_recipient: bool | None = None,
    fixed_recipient: str | None = None,
) -> dict:
    stmt = select(Tender)
    if reference_numbers:
        stmt = stmt.where(Tender.reference_number.in_(reference_numbers))

    tenders = [row for row in db.scalars(stmt).all() if not is_ended_tender_record(row)]
    if not tenders:
        return {
            "emails_sent": 0,
            "recipient_count": 0,
            "tenders_sent": 0,
            "deliveries": [],
            "errors": [],
            "unrouted_reference_numbers": [],
            "message": "No eligible tenders found.",
        }

    if include_fixed_recipient is None:
        include_fixed_recipient = settings.email_copy_fixed_recipient

    fixed_recipient = (fixed_recipient or settings.fixed_email_recipient or "").strip() or None
    buckets, unrouted_reference_numbers = _build_recipient_buckets(
        db=db,
        tenders=tenders,
        include_fixed_recipient=include_fixed_recipient,
        fixed_recipient=fixed_recipient,
    )
    if not buckets:
        return {
            "emails_sent": 0,
            "recipient_count": 0,
            "tenders_sent": 0,
            "deliveries": [],
            "errors": [],
            "unrouted_reference_numbers": unrouted_reference_numbers,
            "message": "No active recipient mappings found.",
        }

    deliveries = []
    errors = []
    recipient_count = 0
    tenders_sent = 0

    for recipient, bucket in sorted(buckets.items()):
        contact = bucket["contact"]
        try:
            result = send_new_tenders_email(
                db=db,
                tenders=bucket["tenders"],
                recipient=recipient,
                subject_prefix=subject_prefix,
                contact_id=getattr(contact, "id", None),
            )
            if result["emails_sent"] > 0:
                recipient_count += 1
                tenders_sent += result["emails_sent"]
            deliveries.append(
                {
                    "recipient": recipient,
                    "contact_name": getattr(contact, "full_name", None) if contact else None,
                    "is_fixed_recipient": bool(fixed_recipient and recipient == fixed_recipient),
                    **result,
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "recipient": recipient,
                    "contact_name": getattr(contact, "full_name", None) if contact else None,
                    "is_fixed_recipient": bool(fixed_recipient and recipient == fixed_recipient),
                    "error": str(exc).strip() or exc.__class__.__name__,
                }
            )

    return {
        "emails_sent": recipient_count,
        "recipient_count": recipient_count,
        "tenders_sent": tenders_sent,
        "deliveries": deliveries,
        "errors": errors,
        "unrouted_reference_numbers": unrouted_reference_numbers,
    }
