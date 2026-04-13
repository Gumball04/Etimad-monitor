import re
from urllib.parse import urlencode

ETIMAD_BASE = "https://tenders.etimad.sa"
SEARCH_PATH = "/Tender/AllTendersForVisitor"


DETAIL_LABELS = {
    "اسم المنافسة": "tender_title",
    "رقم المنافسة": "tender_number",
    "الرقم المرجعي": "reference_number",
    "الغرض من المنافسة": "purpose",
    "قيمة وثائق المنافسة": "document_fee",
    "حالة المنافسة": "status",
    "مدة العقد": "contract_duration",
    "هل التأمين من متطلبات المنافسة": "insurance_required",
    "نوع المنافسة": "tender_type",
    "الجهة الحكوميه": "government_entity",
    "الوقت المتبقي": "remaining_time",
    "طريقة تقديم العروض": "submission_method",
    "مطلوب ضمان الإبتدائي": "initial_guarantee",
    "مطلوب ضمان الابتدائي": "initial_guarantee",
    "مجال التصنيف": "classification_field",
    "نشاط المنافسة": "activity",
}


def normalize_space(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def contains_digit(value: str | None) -> bool:
    text = normalize_space(value)
    if not text:
        return False
    return any(char.isdigit() for char in text)


def normalize_for_comparison(value: str | None) -> str:
    text = normalize_space(value)
    if not text:
        return ""
    return text.casefold()


def build_search_url(keyword: str, page_number: int = 1, page_size: int = 6) -> str:
    params = {
        "MultipleSearch": keyword,
        "TenderCategory": "",
        "ReferenceNumber": "",
        "TenderNumber": "",
        "agency": "",
        "ConditionaBookletRange": "",
        "PublishDateId": 5,
        "LastOfferPresentationDate": "",
        "TenderAreasIdString": "",
        "TenderTypeId": "",
        "TenderActivityId": "",
        "TenderSubActivityId": "",
        "AgencyCode": "",
        "FromLastOfferPresentationDateString": "",
        "ToLastOfferPresentationDateString": "",
        "SortDirection": "DESC",
        "Sort": "SubmitionDate",
        "PageSize": page_size,
        "IsSearch": "true",
        "PageNumber": page_number,
    }
    return f"{ETIMAD_BASE}{SEARCH_PATH}?{urlencode(params, doseq=True)}"


def extract_fields_from_text_block(text: str) -> dict:
    cleaned = normalize_space(text) or ""
    result: dict[str, str | None] = {}
    labels = list(DETAIL_LABELS.keys())
    for idx, label in enumerate(labels):
        next_labels = labels[:idx] + labels[idx + 1 :]
        pattern = rf"{re.escape(label)}\s*[:：.]?\s*(.*?)(?=(?:{'|'.join(map(re.escape, next_labels))})\s*[:：.]?|$)"
        match = re.search(pattern, cleaned, re.DOTALL)
        if match:
            result[DETAIL_LABELS[label]] = normalize_space(match.group(1))
    return result
