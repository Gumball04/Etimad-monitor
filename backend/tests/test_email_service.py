import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.session import Base
from app.models.contact import Contact
from app.models.entity import Entity
from app.models.entity_contact_map import EntityContactMap
from app.models.tender import Tender
from app.models.tender_email_delivery import TenderEmailDelivery
from app.services.email_service import _build_message, send_grouped_emails, send_new_tenders_email


class _SuccessfulSMTP:
    sent_messages = []

    def __init__(self, *args, **kwargs):
        pass

    def ehlo(self):
        return 250, b"ok"

    def starttls(self):
        return 220, b"ready"

    def login(self, *args, **kwargs):
        return 235, b"ok"

    def send_message(self, message):
        self.__class__.sent_messages.append(message)

    def quit(self):
        return 221, b"bye"


class _FailingSMTP(_SuccessfulSMTP):
    def send_message(self, message):
        raise RuntimeError("smtp boom")


class _TimeoutSMTP(_SuccessfulSMTP):
    def __init__(self, *args, **kwargs):
        raise TimeoutError("timed out")


class EmailServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db = self.Session()
        _SuccessfulSMTP.sent_messages = []

        self.original_copy_setting = settings.email_copy_fixed_recipient
        self.original_fixed_recipient = settings.fixed_email_recipient
        self.original_smtp_use_ssl = settings.smtp_use_ssl
        self.original_smtp_ssl_fallback = settings.smtp_ssl_fallback

        settings.email_copy_fixed_recipient = False
        settings.fixed_email_recipient = "gambol.3mr@gmail.com"
        settings.smtp_use_ssl = False
        settings.smtp_ssl_fallback = True

    def tearDown(self):
        settings.email_copy_fixed_recipient = self.original_copy_setting
        settings.fixed_email_recipient = self.original_fixed_recipient
        settings.smtp_use_ssl = self.original_smtp_use_ssl
        settings.smtp_ssl_fallback = self.original_smtp_ssl_fallback
        self.db.close()
        self.engine.dispose()

    def _create_tender(self, **overrides):
        tender = Tender(
            reference_number=overrides.get("reference_number", "RFQ-1"),
            tender_url=overrides.get("tender_url", "https://example.com/tender/1"),
            tender_title=overrides.get("tender_title", "Tender"),
            tender_number=overrides.get("tender_number"),
            purpose=overrides.get("purpose"),
            document_fee=overrides.get("document_fee"),
            status=overrides.get("status", "Open"),
            contract_duration=overrides.get("contract_duration"),
            insurance_required=overrides.get("insurance_required"),
            tender_type=overrides.get("tender_type"),
            remaining_time=overrides.get("remaining_time", "2 days"),
            government_entity=overrides.get("government_entity"),
            submission_method=overrides.get("submission_method"),
            initial_guarantee=overrides.get("initial_guarantee"),
            classification_field=overrides.get("classification_field"),
            activity=overrides.get("activity"),
        )
        self.db.add(tender)
        self.db.commit()
        return self.db.scalar(select(Tender).where(Tender.id == tender.id))

    def test_send_new_tenders_email_tracks_delivery_per_recipient(self):
        tender = self._create_tender()

        with patch("app.services.email_service.smtplib.SMTP", _SuccessfulSMTP):
            first = send_new_tenders_email(self.db, [tender], recipient="alice@example.com", subject_prefix="Batch A")
            self.db.refresh(tender)
            second = send_new_tenders_email(self.db, [tender], recipient="bob@example.com", subject_prefix="Batch B")

        self.assertEqual(first["emails_sent"], 1)
        self.assertEqual(second["emails_sent"], 1)
        deliveries = self.db.scalars(select(TenderEmailDelivery).order_by(TenderEmailDelivery.recipient_email.asc())).all()
        self.assertEqual(
            [(row.recipient_email, row.status) for row in deliveries],
            [("alice@example.com", "sent"), ("bob@example.com", "sent")],
        )

    def test_send_new_tenders_email_leaves_pending_delivery_if_final_commit_fails(self):
        tender = self._create_tender()
        real_commit = self.db.commit
        call_count = {"count": 0}

        def flaky_commit():
            call_count["count"] += 1
            if call_count["count"] == 2:
                raise RuntimeError("db commit failed")
            return real_commit()

        self.db.commit = flaky_commit

        with patch("app.services.email_service.smtplib.SMTP", _SuccessfulSMTP):
            with self.assertRaises(RuntimeError):
                send_new_tenders_email(self.db, [tender], recipient="alice@example.com", subject_prefix="Batch A")

        self.db.rollback()
        verifier = self.Session()
        try:
            delivery = verifier.scalar(select(TenderEmailDelivery))
            self.assertIsNotNone(delivery)
            self.assertEqual(delivery.status, "pending")
            self.assertIsNone(delivery.sent_at)
        finally:
            verifier.close()

    def test_send_new_tenders_email_marks_failed_delivery_on_smtp_error(self):
        tender = self._create_tender()

        with patch("app.services.email_service.smtplib.SMTP", _FailingSMTP):
            with self.assertRaises(RuntimeError):
                send_new_tenders_email(self.db, [tender], recipient="alice@example.com", subject_prefix="Batch A")

        delivery = self.db.scalar(select(TenderEmailDelivery))
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.error_message, "smtp boom")

    def test_send_grouped_emails_uses_entity_contact_mapping(self):
        entity = Entity(entity_name_ar="Entity A")
        contact = Contact(full_name="Alice", email="alice@example.com", is_active=True)
        self.db.add_all([entity, contact])
        self.db.flush()
        self.db.add(EntityContactMap(entity_id=entity.id, contact_id=contact.id))
        self.db.add(
            Tender(
                reference_number="RFQ-1",
                tender_url="https://example.com/tender/1",
                tender_title="Tender",
                status="Open",
                remaining_time="2 days",
                government_entity="Entity A",
            )
        )
        self.db.commit()

        with patch("app.services.email_service.smtplib.SMTP", _SuccessfulSMTP):
            result = send_grouped_emails(self.db, "Batch A", include_fixed_recipient=False)

        self.assertEqual(result["recipient_count"], 1)
        self.assertEqual(result["deliveries"][0]["recipient"], "alice@example.com")
        self.assertEqual(result["deliveries"][0]["reference_numbers"], ["RFQ-1"])

    def test_send_new_tenders_email_falls_back_to_ssl_when_starttls_connection_fails(self):
        tender = self._create_tender()

        with patch("app.services.email_service.smtplib.SMTP", _TimeoutSMTP), patch(
            "app.services.email_service.smtplib.SMTP_SSL",
            _SuccessfulSMTP,
        ):
            result = send_new_tenders_email(self.db, [tender], recipient="alice@example.com", subject_prefix="Batch A")

        self.assertEqual(result["emails_sent"], 1)
        self.assertEqual(len(_SuccessfulSMTP.sent_messages), 1)

    def test_email_body_skips_invalid_remaining_time_and_duplicate_duration(self):
        tender = self._create_tender(
            purpose="Repeated description",
            contract_duration="Repeated description",
            remaining_time="منتهي",
        )

        message = _build_message([tender], "alice@example.com", "Batch A")
        plain_part = next(part for part in message.walk() if part.get_content_type() == "text/plain")
        body = plain_part.get_payload(decode=True).decode(plain_part.get_content_charset() or "utf-8", errors="replace")

        self.assertIn("الغرض من المنافسة: Repeated description", body)
        self.assertNotIn("مدة العقد: Repeated description", body)
        self.assertNotIn("الوقت المتبقي:", body)


if __name__ == "__main__":
    unittest.main()
