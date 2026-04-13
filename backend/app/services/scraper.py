import asyncio
import re
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from app.core.config import settings
from app.core.logging import get_logger
from app.utils.text import DETAIL_LABELS, ETIMAD_BASE, build_search_url, extract_fields_from_text_block, normalize_space

logger = get_logger("scraper")
_PLAYWRIGHT_PROFILE_LOCK = threading.Lock()

PROTECTION_MARKERS = (
    "What code is in the image?",
    "Please enable JavaScript",
    "verify you are human",
    "captcha",
)
ENDED_MARKERS = {
    "انتهى",
    "إنتهى",
    "انتهي",
    "انتهت",
    "منتهي",
    "منتهى",
    "منتهيه",
    "مغلق",
    "مغلقه",
    "مغلقة",
    "مقفل",
    "مقفله",
    "مقفلة",
    "اغلق",
    "اغلقت",
    "تماعتمادالترسيه",
    "تمترسيه",
}
PRIMARY_INFO_TAB_LABELS = ["المعلومات الأساسية", "المعلومات الاساسية"]
CLASSIFICATION_TAB_LABELS = [
    "مجال التصنيف وموقع التنفيذ",
    "مجال التصنيف وموقع التنفيذ والتقديم",
    "التصنيف وموقع التنفيذ",
]
GOVERNMENT_ENTITY_LABELS = ["الجهة الحكومية", "الجهه الحكومية", "الجهة الحكوميه", "الجهه الحكوميه"]
PURPOSE_LABELS = ["الغرض من المنافسة", "الغرض من المنافسـسة", "الغرض من المنافسه"]
CLASSIFICATION_LABELS = ["مجال التصنيف", "مجال التصنيف الرئيسي", "مجال التصنيف / القطاع"]
ACTIVITY_LABELS = ["نشاط المنافسة", "نشاط المناقصة", "نشاط التصنيف", "النشاط"]
SHOW_MORE_SELECTORS = [
    "text=عرض المزيد",
    'button:has-text("عرض المزيد")',
    'a:has-text("عرض المزيد")',
    'span:has-text("عرض المزيد")',
]
TAB_SELECTORS = [
    '[role="tab"]',
    ".nav-tabs a",
    ".nav a",
    'a[data-toggle="tab"]',
    ".nav-item a",
    'button[role="tab"]',
    "a",
    "button",
]
BAD_TEXT_PHRASES = [
    "عرض المزيد",
    "عرض الأقل",
    "الدعم والمساعدة",
    "تحتاج مساعدة؟",
    "اتصل 19990",
    "البوابة الارشادية",
    "اتصل بنا",
    "تابعنا على",
    "حمل تطبيق اعتماد",
    "الدعم بلغة الإشارة",
    "جميع الحقوق محفوظة",
    "المركز الوطني لنظم الموارد الحكومية",
    "المملكة العربية السعودية",
    "سياسة الاستخدام وإخلاء المسؤولية",
    "الإبلاغ عن حالات فساد",
    "سياسة الخصوصية",
    "تدعم منصة اعتماد المتصفحات التالية",
    "تحت إشراف",
    "مجال التصنيف غير مطلوب",
]
LABEL_STRIP_PATTERNS = [
    r"(الجهة الحكومية|الجهه الحكومية|الجهة الحكوميه|الجهه الحكوميه)\s*",
    r"(مجال التصنيف)\s*",
    r"(نشاط المنافسة|نشاط المناقصة|نشاط التصنيف)\s*",
]


class EtimadProtectionError(RuntimeError):
    pass


def _normalize_arabic_for_match(value: str | None) -> str:
    if not value:
        return ""
    text = normalize_space(value) or ""
    return (
        text.replace("إ", "ا")
        .replace("أ", "ا")
        .replace("آ", "ا")
        .replace("ٱ", "ا")
        .replace("ى", "ي")
        .replace("ة", "ه")
        .replace("ـ", "")
        .replace(" ", "")
    )


def _raise_for_protection_page(body_text: str | None) -> None:
    lowered = (normalize_space(body_text) or "").lower()
    if any(marker.lower() in lowered for marker in PROTECTION_MARKERS):
        raise EtimadProtectionError(
            "Etimad returned a protection or challenge page. Retry with a validated browser session."
        )


@dataclass
class ScrapeCard:
    tender_url: str
    summary_text: str | None = None
    tender_title: str | None = None
    tender_number: str | None = None
    reference_number: str | None = None
    government_entity: str | None = None
    remaining_time: str | None = None
    status: str | None = None
    classification_field: str | None = None
    activity: str | None = None


class EtimadScraper:
    def __init__(self, keyword: str, max_pages: int | None = None, page_size: int | None = None):
        self.keyword = keyword.strip()
        self.max_pages = max_pages or settings.playwright_max_pages
        self.page_size = page_size or settings.playwright_page_size
        self.timeout_ms = settings.playwright_timeout_ms

    async def scrape(self) -> tuple[list[dict[str, Any]], int]:
        return await asyncio.to_thread(self._scrape_sync)

    def _scrape_sync(self) -> tuple[list[dict[str, Any]], int]:
        with _PLAYWRIGHT_PROFILE_LOCK:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=settings.playwright_user_data_dir,
                    headless=settings.playwright_headless,
                    locale="ar-SA",
                    viewport={"width": 1440, "height": 1024},
                )
                try:
                    page = context.new_page()
                    return self._scrape_search_pages(context, page)
                finally:
                    context.close()

    def _scrape_search_pages(self, context: BrowserContext, page: Page) -> tuple[list[dict[str, Any]], int]:
        cards: list[ScrapeCard] = []
        seen_links: set[str] = set()
        pages_fetched = 0

        for page_number in range(1, self.max_pages + 1):
            url = build_search_url(self.keyword, page_number=page_number, page_size=self.page_size)
            logger.info("Opening Etimad search page | page=%s | url=%s", page_number, url)

            if not self._goto_with_retry(page, url):
                logger.warning("Failed to open search page | page=%s", page_number)
                break

            self._wait_for_search_results_or_challenge(page)
            page_cards = self._extract_search_cards(page)
            logger.info("Extracted search cards | page=%s | count=%s", page_number, len(page_cards))
            if not page_cards:
                break

            new_cards = 0
            for card in page_cards:
                if card.tender_url not in seen_links:
                    seen_links.add(card.tender_url)
                    cards.append(card)
                    new_cards += 1

            pages_fetched += 1
            if new_cards == 0:
                break

        items = self._resolve_details(context, cards)
        deduped: dict[str, dict[str, Any]] = {}
        for item in items:
            if self._should_skip_tender(item):
                continue

            key = item.get("reference_number") or item.get("tender_url")
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = item
                continue

            merged = self._merge_items(existing, item)
            if not self._should_skip_tender(merged):
                deduped[key] = merged

        return list(deduped.values()), pages_fetched

    def _merge_items(self, old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
        merged = dict(old)
        for key, value in new.items():
            if value in (None, "", [], {}):
                continue
            if merged.get(key) in (None, "", [], {}):
                merged[key] = value
            elif key in {"government_entity", "classification_field", "activity", "purpose"}:
                if len(str(value)) > len(str(merged.get(key) or "")):
                    merged[key] = value
        return merged

    def _goto_with_retry(self, page: Page, url: str, retries: int = 3) -> bool:
        for attempt in range(1, retries + 1):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                return True
            except PlaywrightTimeoutError:
                logger.warning("Timeout while opening page | attempt=%s | url=%s", attempt, url)
            except Exception as exc:
                logger.warning("Error while opening page | attempt=%s | url=%s | error=%s", attempt, url, exc)
            time.sleep(attempt)
        return False

    def _wait_for_search_results_or_challenge(self, page: Page) -> None:
        try:
            page.wait_for_timeout(2500)
            _raise_for_protection_page(page.locator("body").inner_text(timeout=5000))
        except EtimadProtectionError:
            raise
        except Exception:
            pass

    def _extract_search_cards(self, page: Page) -> list[ScrapeCard]:
        detail_links = page.locator('a[href*="/Tender/DetailsForVisitor"]')
        count = detail_links.count()
        results: list[ScrapeCard] = []

        for index in range(count):
            link = detail_links.nth(index)
            href = link.get_attribute("href")
            if not href:
                continue

            full_url = urljoin(ETIMAD_BASE, href)
            container_text = None
            try:
                title_text = normalize_space(link.inner_text())
            except Exception:
                title_text = None

            summary = {"tender_title": title_text}
            for locator_expr in ["xpath=ancestor::article[1]", "xpath=ancestor::div[1]", "xpath=ancestor::li[1]"]:
                try:
                    text = link.locator(locator_expr).inner_text(timeout=1000)
                    if text and len(text.strip()) > 10:
                        container_text = normalize_space(text)
                        break
                except Exception:
                    continue

            if container_text:
                summary.update({key: value for key, value in extract_fields_from_text_block(container_text).items() if value})

            results.append(
                ScrapeCard(
                    tender_url=full_url,
                    summary_text=container_text,
                    tender_title=summary.get("tender_title"),
                    tender_number=summary.get("tender_number"),
                    reference_number=summary.get("reference_number"),
                    government_entity=summary.get("government_entity"),
                    remaining_time=summary.get("remaining_time"),
                    status=summary.get("status"),
                    classification_field=summary.get("classification_field"),
                    activity=summary.get("activity"),
                )
            )

        return results

    def _resolve_details(self, context: BrowserContext, cards: list[ScrapeCard]) -> list[dict[str, Any]]:
        return [self._extract_detail(context, card) for card in cards]

    def _extract_detail(self, context: BrowserContext, card: ScrapeCard) -> dict[str, Any]:
        page = context.new_page()
        try:
            if not self._goto_with_retry(page, card.tender_url):
                return self._card_to_item(card)

            page.wait_for_timeout(1800)
            _raise_for_protection_page(page.locator("body").inner_text(timeout=5000))
            self._click_show_more_buttons(page)

            data = self._card_to_item(card)
            data["tender_url"] = card.tender_url
            data.update({key: value for key, value in self._extract_by_labels(page).items() if value})

            self._open_tab_by_any_text(page, PRIMARY_INFO_TAB_LABELS)
            page.wait_for_timeout(1000)
            self._click_show_more_buttons(page)

            government_entity = self._extract_value_by_any_label(page, GOVERNMENT_ENTITY_LABELS)
            purpose = self._extract_value_by_any_label(page, PURPOSE_LABELS)

            self._open_tab_by_any_text(page, CLASSIFICATION_TAB_LABELS)
            page.wait_for_timeout(1200)
            self._click_show_more_buttons(page)

            classification_field = self._extract_value_by_any_label(page, CLASSIFICATION_LABELS)
            activity = self._extract_value_by_any_label(page, ACTIVITY_LABELS)

            body_text = normalize_space(page.locator("body").inner_text(timeout=9000)) or ""

            if not government_entity:
                government_entity = self._extract_field_from_text_by_any_label(body_text, GOVERNMENT_ENTITY_LABELS)
            if not purpose:
                purpose = self._extract_field_from_text_by_any_label(body_text, PURPOSE_LABELS)
            if not classification_field:
                classification_field = self._extract_field_from_text_by_any_label(body_text, CLASSIFICATION_LABELS)
            if not activity:
                activity = self._extract_field_from_text_by_any_label(body_text, ACTIVITY_LABELS)

            if not government_entity:
                government_entity = self._extract_between_labels(
                    body_text,
                    start_labels=GOVERNMENT_ENTITY_LABELS,
                    stop_labels=[
                        "الغرض من المنافسة",
                        "رقم المنافسة",
                        "الرقم المرجعي",
                        "قيمة وثائق المنافسة",
                        "حالة المنافسة",
                    ],
                )
            if not classification_field:
                classification_field = self._extract_between_labels(
                    body_text,
                    start_labels=["مجال التصنيف"],
                    stop_labels=["نشاط المنافسة", "نشاط المناقصة", "نشاط التصنيف", "مكان التنفيذ", "موقع التنفيذ"],
                )
            if not activity:
                activity = self._extract_between_labels(
                    body_text,
                    start_labels=["نشاط المنافسة", "نشاط المناقصة", "نشاط التصنيف"],
                    stop_labels=["مكان التنفيذ", "موقع التنفيذ", "منطقة", "التقديم", "مكان التقديم"],
                )

            if government_entity:
                data["government_entity"] = self._clean_extracted_value(government_entity)
            if purpose:
                data["purpose"] = self._clean_extracted_value(purpose)
            if classification_field:
                data["classification_field"] = self._clean_extracted_value(classification_field)
            if activity:
                data["activity"] = self._clean_extracted_value(activity)
            if not data.get("reference_number"):
                data["reference_number"] = card.reference_number or card.tender_url

            return data
        except EtimadProtectionError:
            raise
        except Exception as exc:
            logger.warning("Failed to extract tender details | url=%s | error=%s", card.tender_url, exc)
            return self._card_to_item(card)
        finally:
            page.close()

    def _extract_by_labels(self, page: Page) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for label, field_name in DETAIL_LABELS.items():
            value = self._read_value_near_label(page, label)
            if value:
                data[field_name] = self._clean_extracted_value(value)
        return data

    def _read_value_near_label(self, page: Page, label: str) -> str | None:
        candidates = [
            f"text={label}",
            f"xpath=//*[normalize-space()='{label}']",
            f"xpath=//label[normalize-space()='{label}']",
            f"xpath=//span[normalize-space()='{label}']",
            f"xpath=//div[normalize-space()='{label}']",
            f"xpath=//dt[normalize-space()='{label}']",
            f"xpath=//th[normalize-space()='{label}']",
        ]
        for selector in candidates:
            try:
                locator = page.locator(selector).first
                if locator.count() == 0:
                    continue
                for neighbor in [
                    "xpath=following-sibling::*[1]",
                    "xpath=parent::*/*[2]",
                    "xpath=ancestor::*[1]/following-sibling::*[1]",
                    "xpath=ancestor::*[1]/parent::*/*[2]",
                ]:
                    try:
                        text = normalize_space(locator.locator(neighbor).inner_text(timeout=800))
                        cleaned = self._clean_extracted_value(text)
                        if cleaned and cleaned != label:
                            return cleaned
                    except Exception:
                        continue

                wrapper_text = normalize_space(locator.locator("xpath=ancestor::*[1]").inner_text(timeout=800))
                if wrapper_text and wrapper_text != label:
                    extracted = extract_fields_from_text_block(wrapper_text)
                    field_name = DETAIL_LABELS.get(label)
                    if field_name:
                        cleaned = self._clean_extracted_value(extracted.get(field_name))
                        if cleaned:
                            return cleaned
            except Exception:
                continue
        return None

    def _click_show_more_buttons(self, page: Page) -> None:
        for _ in range(5):
            clicked_any = False
            for selector in SHOW_MORE_SELECTORS:
                try:
                    locator = page.locator(selector)
                    count = locator.count()
                    for index in range(count):
                        try:
                            button = locator.nth(index)
                            if button.is_visible():
                                button.click(timeout=1500)
                                page.wait_for_timeout(350)
                                clicked_any = True
                        except Exception:
                            pass
                except Exception:
                    pass
            if not clicked_any:
                break

    def _open_tab_by_any_text(self, page: Page, texts: list[str]) -> bool:
        for tab_text in texts:
            if self._open_tab_by_text(page, tab_text):
                return True
        return False

    def _open_tab_by_text(self, page: Page, tab_text: str) -> bool:
        wanted = normalize_space(tab_text)
        for selector in TAB_SELECTORS:
            try:
                locator = page.locator(selector)
                count = min(locator.count(), 80)
                for index in range(count):
                    try:
                        tab = locator.nth(index)
                        text = normalize_space(tab.inner_text())
                        if text and wanted in text and tab.is_visible():
                            tab.click(timeout=2000)
                            page.wait_for_timeout(1200)
                            return True
                    except Exception:
                        pass
            except Exception:
                pass
        return False

    def _extract_value_by_any_label(self, page: Page, labels: list[str]) -> str | None:
        for label in labels:
            value = self._extract_value_by_label(page, label)
            if value:
                cleaned = self._clean_extracted_value(value)
                if cleaned:
                    return cleaned
        return None

    def _extract_value_by_label(self, page: Page, label_text: str) -> str | None:
        js = """
        (labelText) => {
            const norm = (s) => (s || "")
                .replace(/\\u200f|\\u200e|\\xa0/g, " ")
                .replace(/\\s+/g, " ")
                .trim();

            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (style.display === "none" || style.visibility === "hidden") return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };

            const exact = (a, b) => norm(a) === norm(b);
            const banned = [
                "الدعم والمساعدة",
                "اتصل بنا",
                "تابعنا على",
                "حمل تطبيق اعتماد",
                "جميع الحقوق محفوظة",
                "سياسة الخصوصية",
                "سياسة الاستخدام",
                "تحت إشراف"
            ];

            const badText = (txt) => {
                const value = norm(txt);
                if (!value) return true;
                return banned.some((item) => value.includes(item));
            };

            const rows = Array.from(document.querySelectorAll("tr")).filter(isVisible);
            for (const row of rows) {
                const cells = Array.from(row.querySelectorAll("th, td")).filter(isVisible);
                const texts = cells.map((cell) => norm(cell.innerText));
                for (let i = 0; i < texts.length - 1; i++) {
                    if (exact(texts[i], labelText)) {
                        const value = norm(cells[i + 1].innerText);
                        if (value && !badText(value) && !exact(value, labelText)) {
                            return value;
                        }
                    }
                }
            }

            const blocks = Array.from(document.querySelectorAll("label, th, td, span, div, p, li, strong, b")).filter(isVisible);
            for (const el of blocks) {
                const text = norm(el.innerText);
                if (!exact(text, labelText)) continue;

                const parent = el.parentElement;
                if (parent && isVisible(parent)) {
                    const kids = Array.from(parent.children).filter(isVisible);
                    const kidTexts = kids.map((child) => norm(child.innerText));
                    for (let i = 0; i < kidTexts.length - 1; i++) {
                        if (exact(kidTexts[i], labelText)) {
                            const value = norm(kids[i + 1].innerText);
                            if (value && !badText(value) && !exact(value, labelText)) {
                                return value;
                            }
                        }
                    }
                }

                const next = el.nextElementSibling;
                if (next && isVisible(next)) {
                    const nextText = norm(next.innerText);
                    if (nextText && !badText(nextText) && !exact(nextText, labelText)) {
                        return nextText;
                    }
                }

                const grand = parent?.parentElement;
                if (grand && isVisible(grand)) {
                    const grandKids = Array.from(grand.children).filter(isVisible);
                    const grandTexts = grandKids.map((child) => norm(child.innerText));
                    for (let i = 0; i < grandTexts.length - 1; i++) {
                        if (exact(grandTexts[i], labelText)) {
                            const value = norm(grandKids[i + 1].innerText);
                            if (value && !badText(value) && !exact(value, labelText)) {
                                return value;
                            }
                        }
                    }
                }
            }

            return null;
        }
        """
        try:
            value = page.evaluate(js, label_text)
            return self._clean_extracted_value(value) if value else None
        except Exception:
            return None

    def _extract_field_from_text_by_any_label(self, text: str, labels: list[str]) -> str | None:
        for label in labels:
            value = self._extract_field_from_text(text, label)
            if value:
                cleaned = self._clean_extracted_value(value)
                if cleaned:
                    return cleaned
        return None

    def _extract_field_from_text(self, text: str, label: str) -> str | None:
        try:
            lines = [normalize_space(line) for line in text.splitlines() if normalize_space(line)]
            label_norm = normalize_space(label)
            for index, line in enumerate(lines):
                current = normalize_space(line)
                if current == label_norm and index + 1 < len(lines):
                    next_line = self._clean_extracted_value(lines[index + 1])
                    if next_line and normalize_space(next_line) != label_norm:
                        return next_line
                if current.startswith(label_norm + ":"):
                    same_line = self._clean_extracted_value(current.split(":", 1)[1])
                    if same_line:
                        return same_line
                if current.startswith(label_norm + " "):
                    same_line = self._clean_extracted_value(current[len(label_norm) :])
                    if same_line:
                        return same_line
        except Exception:
            pass
        return None

    def _extract_between_labels(self, text: str, start_labels: list[str], stop_labels: list[str]) -> str | None:
        compact = normalize_space(text)
        if not compact:
            return None
        stop_pattern = "|".join(re.escape(normalize_space(label)) for label in stop_labels if normalize_space(label))
        if not stop_pattern:
            return None

        for start_label in start_labels:
            start_label_norm = re.escape(normalize_space(start_label))
            pattern = rf"{start_label_norm}\s*(.*?)(?=\s*(?:{stop_pattern})\b)"
            match = re.search(pattern, compact, flags=re.IGNORECASE)
            if match:
                value = self._clean_extracted_value(match.group(1))
                if value and value != normalize_space(start_label):
                    return value
        return None

    def _clean_extracted_value(self, value: str | None) -> str | None:
        text = normalize_space(value)
        if not text:
            return None
        for phrase in BAD_TEXT_PHRASES:
            text = text.replace(phrase, " ")
        text = normalize_space(text)
        if not text:
            return None
        if "..." in text:
            parts = [normalize_space(part) for part in text.split("...") if normalize_space(part)]
            if parts:
                text = max(parts, key=len)
        for pattern in LABEL_STRIP_PATTERNS:
            text = re.sub(pattern, "", text).strip()
        text = normalize_space(text.replace("..", " "))
        return text or None

    def _card_to_item(self, card: ScrapeCard) -> dict[str, Any]:
        return {
            "tender_title": card.tender_title,
            "tender_number": card.tender_number,
            "reference_number": card.reference_number or card.tender_url,
            "purpose": None,
            "document_fee": None,
            "status": card.status,
            "contract_duration": None,
            "insurance_required": None,
            "tender_type": None,
            "government_entity": card.government_entity,
            "remaining_time": card.remaining_time,
            "submission_method": None,
            "initial_guarantee": None,
            "classification_field": card.classification_field,
            "activity": card.activity,
            "tender_url": card.tender_url,
        }

    def _is_ended_value(self, value: str | None) -> bool:
        normalized = _normalize_arabic_for_match(value)
        if not normalized:
            return False
        normalized_markers = {_normalize_arabic_for_match(marker) for marker in ENDED_MARKERS}
        return normalized in normalized_markers or any(marker in normalized for marker in normalized_markers)

    def _should_skip_tender(self, item: dict[str, Any]) -> bool:
        for value in (item.get("remaining_time"), item.get("status")):
            if self._is_ended_value(value):
                return True
        return False
