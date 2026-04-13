from io import BytesIO
from typing import Any
from datetime import datetime

import pandas as pd
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.contact import Contact
from app.models.entity_contact_map import EntityContactMap
from app.models.tender import Tender
from app.models.tender_email_delivery import TenderEmailDelivery
from app.utils.text import contains_digit, normalize_for_comparison, normalize_space


TENDER_COLUMNS_AR = {
    "tender_title": "اسم المنافسة",
    "tender_number": "رقم المنافسة",
    "reference_number": "الرقم المرجعي",
    "purpose": "الغرض من المنافسة",
    "document_fee": "قيمة وثائق المنافسة",
    "status": "حالة المنافسة",
    "contract_duration": "مدة العقد",
    "insurance_required": "هل التأمين من متطلبات المنافسة",
    "tender_type": "نوع المنافسة",
    "government_entity": "الجهة الحكومية",
    "remaining_time": "الوقت المتبقي",
    "submission_method": "طريقة تقديم العروض",
    "initial_guarantee": "مطلوب ضمان الإبتدائي",
    "classification_field": "مجال التصنيف",
    "activity": "نشاط المنافسة",
    "tender_url": "رابط المنافسة",
    "email_sent": "تم إرسال الإيميل",
    "email_sent_at": "وقت إرسال الإيميل",
}

TENDER_MUTABLE_FIELDS = [
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


def _value_from_row(row: Tender | dict[str, Any], field_name: str) -> Any:
    if isinstance(row, dict):
        return row.get(field_name)
    return getattr(row, field_name, None)


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return normalize_space(str(value))


def _sanitize_remaining_time(value: Any) -> str | None:
    text = _normalize_optional_text(value)
    if not text or not contains_digit(text):
        return None
    return text


def _sanitize_contract_duration(value: Any, purpose: Any) -> str | None:
    text = _normalize_optional_text(value)
    if not text:
        return None

    purpose_text = _normalize_optional_text(purpose)
    if purpose_text and normalize_for_comparison(text) == normalize_for_comparison(purpose_text):
        return None

    if len(text) > 120 and not contains_digit(text):
        return None

    return text


def _sanitize_tender_payload(tender_data: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(tender_data)
    sanitized["remaining_time"] = _sanitize_remaining_time(sanitized.get("remaining_time"))
    sanitized["contract_duration"] = _sanitize_contract_duration(
        sanitized.get("contract_duration"),
        sanitized.get("purpose"),
    )
    return sanitized


def get_tender_identity(row: Tender | dict[str, Any]) -> str | None:
    for field_name in ("reference_number", "tender_url", "detail_url"):
        value = _normalize_optional_text(_value_from_row(row, field_name))
        if value:
            return value
    return None


def _merge_tender_payloads(primary: dict[str, Any], duplicate: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)

    for key, value in duplicate.items():
        if value in (None, "", [], {}):
            continue

        current = merged.get(key)
        if current in (None, "", [], {}):
            merged[key] = value
            continue

        if key == "reference_number" and _looks_like_tender_url(str(current)) and not _looks_like_tender_url(str(value)):
            merged[key] = value
            continue

        if key in {"tender_title", "government_entity", "purpose", "classification_field", "activity"}:
            if len(str(value)) > len(str(current)):
                merged[key] = value

    return _sanitize_tender_payload(merged)


def dedupe_tender_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}

    for item in items:
        cleaned_item = _sanitize_tender_payload(item)
        identity = get_tender_identity(cleaned_item)
        if not identity:
            continue

        existing = deduped.get(identity)
        if existing is None:
            deduped[identity] = cleaned_item
        else:
            deduped[identity] = _merge_tender_payloads(existing, cleaned_item)

    return list(deduped.values())


def dedupe_tender_records(tenders: list[Tender]) -> list[Tender]:
    deduped: dict[str, Tender] = {}

    for tender in tenders:
        identity = get_tender_identity(tender)
        if not identity:
            continue
        deduped.setdefault(identity, tender)

    return list(deduped.values())


def _excel_safe_value(value):
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.replace(tzinfo=None)
        return value
    return value


def _normalize_ar_status(value: str | None) -> str:
    if not value:
        return ""
    return (
        str(value).strip()
        .replace("إ", "ا")
        .replace("أ", "ا")
        .replace("آ", "ا")
        .replace("ٱ", "ا")
        .replace("ى", "ي")
        .replace("ة", "ه")
        .replace("ـ", "")
        .replace(" ", "")
    )


def is_ended_tender_value(value: str | None) -> bool:
    normalized = _normalize_ar_status(value)
    if not normalized:
        return False

    markers = {
        "انتهى", "انتهي", "انتهت", "منتهي", "منتهى", "منتهيه",
        "مغلق", "مغلقه", "مغلقة", "مقفل", "مقفله", "مقفلة",
        "اغلق", "اغلقت", "تماعتمادالترسيه", "تمترسيه",
    }
    normalized_markers = {_normalize_ar_status(m) for m in markers}
    return normalized in normalized_markers or any(m in normalized for m in normalized_markers)


def is_ended_tender_record(row: Tender | dict[str, Any]) -> bool:
    remaining_time = row.get("remaining_time") if isinstance(row, dict) else getattr(row, "remaining_time", None)
    status = row.get("status") if isinstance(row, dict) else getattr(row, "status", None)
    return is_ended_tender_value(remaining_time) or is_ended_tender_value(status)


def _looks_like_tender_url(value: str | None) -> bool:
    if not value:
        return False
    return value.startswith("http://") or value.startswith("https://")


def _merge_tender_record(primary: Tender, duplicate: Tender) -> None:
    for field in TENDER_MUTABLE_FIELDS:
        current = getattr(primary, field)
        other = getattr(duplicate, field)
        if current in (None, "", [], {}) and other not in (None, "", [], {}):
            setattr(primary, field, other)

    if _looks_like_tender_url(primary.reference_number) and not _looks_like_tender_url(duplicate.reference_number):
        primary.reference_number = duplicate.reference_number

    if not primary.email_sent and duplicate.email_sent:
        primary.email_sent = True
    if not primary.email_sent_at and duplicate.email_sent_at:
        primary.email_sent_at = duplicate.email_sent_at


def _find_matching_tenders(db: Session, reference_number: str | None, tender_url: str | None) -> list[Tender]:
    filters = []
    if reference_number:
        filters.append(Tender.reference_number == reference_number)
    if tender_url:
        filters.append(Tender.tender_url == tender_url)

    if not filters:
        return []

    return list(db.scalars(select(Tender).where(or_(*filters)).order_by(Tender.id.asc())).all())


def _pick_primary_tender(matches: list[Tender], reference_number: str | None) -> Tender:
    if reference_number:
        for match in matches:
            if match.reference_number == reference_number:
                return match

    for match in matches:
        if not _looks_like_tender_url(match.reference_number):
            return match

    return matches[0]


def _upsert_single_tender(db: Session, tender_data: dict[str, Any]) -> tuple[Tender | None, bool]:
    tender_data = _sanitize_tender_payload(tender_data)
    reference_number = tender_data.get("reference_number")
    tender_url = tender_data.get("tender_url")
    identity = reference_number or tender_url
    if not identity:
        return None, False

    matches = _find_matching_tenders(db, reference_number, tender_url)
    if matches:
        target = _pick_primary_tender(matches, reference_number)
        duplicates = [row for row in matches if row.id != target.id]
        for duplicate in duplicates:
            _merge_tender_record(target, duplicate)
            db.delete(duplicate)

        if reference_number and target.reference_number != reference_number:
            target.reference_number = reference_number
        elif not target.reference_number:
            target.reference_number = identity

        for key, value in tender_data.items():
            setattr(target, key, value)

        if not target.reference_number:
            target.reference_number = identity

        return target, False

    new_tender = Tender(**{**tender_data, "reference_number": identity})
    db.add(new_tender)
    db.flush()
    return new_tender, True


def upsert_tenders(db: Session, items: list[dict]) -> dict:
    inserted = 0
    updated = 0
    saved_items = []
    new_items = []

    for item in dedupe_tender_items(items):
        if is_ended_tender_record(item):
            continue

        ref = item.get("reference_number")
        tender_url = item.get("tender_url")
        if not ref and not tender_url:
            continue

        tender, is_new = _upsert_single_tender(db, item)
        if not tender:
            continue

        if is_new:
            inserted += 1
            saved_items.append(tender)
            new_items.append(tender)
        else:
            updated += 1
            saved_items.append(tender)

    db.commit()

    return {
        "total_saved": inserted + updated,
        "inserted": inserted,
        "updated": updated,
        "saved_items": saved_items,
        "new_items": new_items,
    }


def list_tenders(db: Session, limit: int = 100, government_entity: str | None = None) -> list[Tender]:
    stmt = select(Tender).order_by(Tender.updated_at.desc()).limit(limit)
    if government_entity:
        stmt = stmt.where(Tender.government_entity == government_entity)
    rows = [row for row in db.scalars(stmt).all() if not is_ended_tender_record(row)]
    return dedupe_tender_records(rows)


def export_tenders_excel(db: Session, reference_numbers: list[str] | None = None) -> bytes:
    rows = list_tenders_for_email(db, reference_numbers)
    data = []

    for row in rows:
        data.append(
            {
                "tender_title": _excel_safe_value(row.tender_title),
                "tender_number": _excel_safe_value(row.tender_number),
                "reference_number": _excel_safe_value(row.reference_number),
                "purpose": _excel_safe_value(row.purpose),
                "document_fee": _excel_safe_value(row.document_fee),
                "status": _excel_safe_value(row.status),
                "contract_duration": _excel_safe_value(row.contract_duration),
                "insurance_required": _excel_safe_value(row.insurance_required),
                "tender_type": _excel_safe_value(row.tender_type),
                "government_entity": _excel_safe_value(row.government_entity),
                "remaining_time": _excel_safe_value(row.remaining_time),
                "submission_method": _excel_safe_value(row.submission_method),
                "initial_guarantee": _excel_safe_value(row.initial_guarantee),
                "classification_field": _excel_safe_value(row.classification_field),
                "activity": _excel_safe_value(row.activity),
                "tender_url": _excel_safe_value(row.tender_url),
                "email_sent": _excel_safe_value(row.email_sent),
                "email_sent_at": _excel_safe_value(row.email_sent_at),
            }
        )

    df = pd.DataFrame(data)
    if not df.empty:
        df = df.rename(columns=TENDER_COLUMNS_AR)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="المنافسات")

    output.seek(0)
    return output.getvalue()


def list_tenders_for_email(db: Session, reference_numbers: list[str] | None = None) -> list[Tender]:
    stmt = select(Tender)
    if reference_numbers:
        stmt = stmt.where(Tender.reference_number.in_(reference_numbers))
    rows = [row for row in db.scalars(stmt).all() if not is_ended_tender_record(row)]
    return dedupe_tender_records(rows)


def build_email_routing_preview(db: Session, reference_numbers: list[str] | None = None) -> list[dict]:
    tenders = list_tenders_for_email(db, reference_numbers)

    mappings = list(
        db.scalars(
            select(EntityContactMap)
            .options(joinedload(EntityContactMap.entity), joinedload(EntityContactMap.contact))
        ).all()
    )

    entity_to_contacts: dict[str, list[Contact]] = {}
    for m in mappings:
        if not m.entity or not m.contact or not m.contact.is_active:
            continue
        entity_to_contacts.setdefault(m.entity.entity_name_ar, []).append(m.contact)

    tender_ids = [tender.id for tender in tenders if tender.id is not None]
    recipient_emails = sorted(
        {
            mapping.contact.email
            for mapping in mappings
            if mapping.contact and mapping.contact.is_active and mapping.contact.email
        }
    )
    delivery_rows = []
    if tender_ids and recipient_emails:
        delivery_rows = list(
            db.scalars(
                select(TenderEmailDelivery).where(
                    TenderEmailDelivery.tender_id.in_(tender_ids),
                    TenderEmailDelivery.recipient_email.in_(recipient_emails),
                )
            ).all()
        )
    delivery_map = {
        (delivery.tender_id, delivery.recipient_email): delivery
        for delivery in delivery_rows
    }

    grouped: dict[str, dict] = {}
    for tender in tenders:
        contacts = entity_to_contacts.get(tender.government_entity or "", [])
        for contact in contacts:
            delivery = delivery_map.get((tender.id, contact.email)) if tender.id is not None else None
            bucket = grouped.setdefault(
                contact.email,
                {
                    "contact_name": contact.full_name,
                    "email": contact.email,
                    "entities": set(),
                    "tenders": [],
                },
            )
            if tender.government_entity:
                bucket["entities"].add(tender.government_entity)

            bucket["tenders"].append(
                {
                    "reference_number": tender.reference_number,
                    "tender_title": tender.tender_title,
                    "government_entity": tender.government_entity,
                    "status": tender.status,
                    "tender_url": tender.tender_url,
                    "email_sent": bool(delivery and delivery.status == "sent"),
                    "email_sent_at": (
                        delivery.sent_at.replace(tzinfo=None)
                        if delivery and delivery.sent_at and delivery.sent_at.tzinfo is not None
                        else (delivery.sent_at if delivery else None)
                    ),
                    "delivery_status": delivery.status if delivery else "unsent",
                }
            )

    if settings.email_copy_fixed_recipient and settings.fixed_email_recipient:
        fixed_email = settings.fixed_email_recipient
        bucket = grouped.setdefault(
            fixed_email,
            {
                "contact_name": "Fixed recipient",
                "email": fixed_email,
                "entities": set(),
                "tenders": [],
            },
        )
        existing_keys = {
            (item["reference_number"], item.get("tender_url"))
            for item in bucket["tenders"]
        }
        for tender in tenders:
            key = (tender.reference_number, tender.tender_url)
            if key in existing_keys:
                continue
            existing_keys.add(key)
            if tender.government_entity:
                bucket["entities"].add(tender.government_entity)
            delivery = delivery_map.get((tender.id, fixed_email)) if tender.id is not None else None
            bucket["tenders"].append(
                {
                    "reference_number": tender.reference_number,
                    "tender_title": tender.tender_title,
                    "government_entity": tender.government_entity,
                    "status": tender.status,
                    "tender_url": tender.tender_url,
                    "email_sent": bool(delivery and delivery.status == "sent"),
                    "email_sent_at": (
                        delivery.sent_at.replace(tzinfo=None)
                        if delivery and delivery.sent_at and delivery.sent_at.tzinfo is not None
                        else (delivery.sent_at if delivery else None)
                    ),
                    "delivery_status": delivery.status if delivery else "unsent",
                }
            )

    result = []
    for item in grouped.values():
        item["entities"] = sorted(item["entities"])
        result.append(item)

    return result
