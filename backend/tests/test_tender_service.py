import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.tender import Tender
from app.services.tender_service import upsert_tenders


class TenderServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_upsert_reuses_url_placeholder_when_reference_number_arrives(self):
        placeholder = {
            "reference_number": "https://tenders.etimad.sa/Tender/DetailsForVisitor?id=1",
            "tender_url": "https://tenders.etimad.sa/Tender/DetailsForVisitor?id=1",
            "tender_title": "Tender A",
            "status": "Open",
            "remaining_time": "2 days",
        }
        resolved = {
            "reference_number": "RFQ-123",
            "tender_url": "https://tenders.etimad.sa/Tender/DetailsForVisitor?id=1",
            "tender_title": "Tender A",
            "status": "Open",
            "remaining_time": "2 days",
        }

        first = upsert_tenders(self.db, [placeholder])
        second = upsert_tenders(self.db, [resolved])

        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(self.db.execute(text("select count(*) from tenders")).scalar(), 1)
        self.assertEqual(
            self.db.execute(text("select reference_number from tenders")).scalar(),
            "RFQ-123",
        )

    def test_upsert_clears_non_numeric_remaining_time_and_duplicate_duration(self):
        item = {
            "reference_number": "RFQ-200",
            "tender_url": "https://tenders.etimad.sa/Tender/DetailsForVisitor?id=200",
            "tender_title": "Tender B",
            "status": "Open",
            "remaining_time": "قريبا",
            "purpose": "وصف المنافسة",
            "contract_duration": "وصف المنافسة",
        }

        result = upsert_tenders(self.db, [item])
        saved = self.db.query(Tender).filter(Tender.reference_number == "RFQ-200").one()

        self.assertEqual(result["inserted"], 1)
        self.assertIsNone(saved.remaining_time)
        self.assertIsNone(saved.contract_duration)

    def test_upsert_dedupes_duplicate_items_with_same_reference_in_one_batch(self):
        items = [
            {
                "reference_number": "RFQ-300",
                "tender_url": "https://tenders.etimad.sa/Tender/DetailsForVisitor?id=300",
                "tender_title": "Tender C",
                "status": "Open",
                "remaining_time": "3 days",
            },
            {
                "reference_number": "RFQ-300",
                "tender_url": "https://tenders.etimad.sa/Tender/DetailsForVisitor?id=300",
                "tender_title": "Tender C",
                "government_entity": "Entity A",
                "status": "Open",
                "remaining_time": "3 days",
            },
        ]

        result = upsert_tenders(self.db, items)
        saved = self.db.query(Tender).filter(Tender.reference_number == "RFQ-300").one()

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(self.db.execute(text("select count(*) from tenders")).scalar(), 1)
        self.assertEqual(saved.government_entity, "Entity A")

    def test_upsert_uses_tender_url_when_reference_is_missing_for_batch_deduplication(self):
        items = [
            {
                "reference_number": None,
                "tender_url": "https://tenders.etimad.sa/Tender/DetailsForVisitor?id=301",
                "tender_title": "Tender D",
                "status": "Open",
                "remaining_time": "4 days",
            },
            {
                "reference_number": None,
                "tender_url": "https://tenders.etimad.sa/Tender/DetailsForVisitor?id=301",
                "tender_title": "Tender D",
                "purpose": "Merged purpose",
                "status": "Open",
                "remaining_time": "4 days",
            },
        ]

        result = upsert_tenders(self.db, items)
        saved = self.db.query(Tender).one()

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(saved.reference_number, "https://tenders.etimad.sa/Tender/DetailsForVisitor?id=301")
        self.assertEqual(saved.purpose, "Merged purpose")


if __name__ == "__main__":
    unittest.main()
