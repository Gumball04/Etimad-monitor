import unittest
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks

from app.schemas.tender import ScrapeRequest
from app.services.scrape_service import SingleKeywordScrapeResult, run_scrape_request
from app.services.scraper import EtimadProtectionError


class _DBSession:
    def __init__(self):
        self.rollback_count = 0

    def rollback(self):
        self.rollback_count += 1


class _SavedTender:
    def __init__(self, tender_id: int):
        self.id = tender_id


class ScrapeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_mode_keeps_single_keyword_flow_and_finalizes_once(self):
        db = _DBSession()
        single_result = SingleKeywordScrapeResult(
            keyword="manual",
            fetched_pages=2,
            total_found=1,
            items=[{"reference_number": "RFQ-1", "tender_title": "Tender 1"}],
        )

        with patch("app.services.scrape_service.list_saved_keywords", return_value=[]), patch(
            "app.services.scrape_service.run_single_keyword_scrape",
            new=AsyncMock(return_value=single_result),
        ) as run_single, patch(
            "app.services.scrape_service.upsert_tenders",
            return_value={
                "total_saved": 1,
                "inserted": 1,
                "updated": 0,
                "new_items": [_SavedTender(101)],
            },
        ) as upsert, patch(
            "app.services.scrape_service._queue_auto_email",
            return_value=(True, "fixed@example.com"),
        ) as queue_email:
            response = await run_scrape_request(
                payload=ScrapeRequest(keyword=" manual "),
                db=db,
                background_tasks=BackgroundTasks(),
            )

        self.assertEqual(response.execution_mode, "manual")
        self.assertEqual(response.executed_keywords, ["manual"])
        self.assertEqual(response.failed_keywords, [])
        self.assertEqual(len(response.items), 1)
        self.assertEqual(response.items[0]["reference_number"], "RFQ-1")
        self.assertEqual(response.items[0]["tender_title"], "Tender 1")
        self.assertEqual(response.inserted, 1)
        self.assertEqual(response.updated, 0)
        self.assertTrue(response.auto_email_queued)
        self.assertEqual(run_single.await_count, 1)
        self.assertEqual(run_single.await_args.kwargs["keyword"], "manual")
        self.assertEqual(upsert.call_count, 1)
        self.assertEqual(len(upsert.call_args.args[1]), 1)
        self.assertEqual(upsert.call_args.args[1][0]["reference_number"], "RFQ-1")
        self.assertEqual(queue_email.call_count, 1)
        self.assertEqual(queue_email.call_args.kwargs["execution_mode"], "manual")
        self.assertIsNone(queue_email.call_args.kwargs["keyword_exports"])

    async def test_saved_keywords_are_deduped_before_single_final_save_and_email(self):
        db = _DBSession()
        run_results = [
            SingleKeywordScrapeResult(
                keyword="gas",
                fetched_pages=1,
                total_found=2,
                items=[
                    {"reference_number": "RFQ-1", "tender_title": "Tender 1", "government_entity": None},
                    {"reference_number": "RFQ-2", "tender_title": "Tender 2"},
                ],
            ),
            SingleKeywordScrapeResult(
                keyword="fiber",
                fetched_pages=2,
                total_found=1,
                items=[
                    {"reference_number": "RFQ-1", "tender_title": "Tender 1", "government_entity": "Entity A"},
                ],
            ),
        ]

        with patch("app.services.scrape_service.list_saved_keywords", return_value=["gas", "fiber"]), patch(
            "app.services.scrape_service.run_single_keyword_scrape",
            new=AsyncMock(side_effect=run_results),
        ) as run_single, patch(
            "app.services.scrape_service.upsert_tenders",
            return_value={
                "total_saved": 2,
                "inserted": 2,
                "updated": 0,
                "new_items": [_SavedTender(201), _SavedTender(202)],
            },
        ) as upsert, patch(
            "app.services.scrape_service._queue_auto_email",
            return_value=(True, "fixed@example.com"),
        ) as queue_email:
            response = await run_scrape_request(
                payload=ScrapeRequest(keyword="manual should be ignored"),
                db=db,
                background_tasks=BackgroundTasks(),
            )

        final_items = upsert.call_args.args[1]

        self.assertEqual(response.execution_mode, "saved-keywords")
        self.assertEqual(response.executed_keywords, ["gas", "fiber"])
        self.assertEqual(response.failed_keywords, [])
        self.assertEqual(response.fetched_pages, 3)
        self.assertEqual(response.total_found, 2)
        self.assertEqual(response.total_saved, 2)
        self.assertEqual(response.inserted, 2)
        self.assertEqual(response.updated, 0)
        self.assertEqual(len(response.items), 2)
        merged_first = next(item for item in final_items if item["reference_number"] == "RFQ-1")
        self.assertEqual(merged_first["government_entity"], "Entity A")
        self.assertEqual(run_single.await_count, 2)
        self.assertEqual(
            [call.kwargs["keyword"] for call in run_single.await_args_list],
            ["gas", "fiber"],
        )
        self.assertEqual(upsert.call_count, 1)
        self.assertEqual(len(final_items), 2)
        self.assertEqual(queue_email.call_count, 1)
        self.assertEqual(queue_email.call_args.kwargs["execution_mode"], "saved-keywords")
        self.assertEqual(len(queue_email.call_args.kwargs["keyword_exports"]), 2)
        self.assertEqual(
            [item["keyword"] for item in queue_email.call_args.kwargs["keyword_exports"]],
            ["gas", "fiber"],
        )

    async def test_saved_keyword_failures_are_collected_and_remaining_keywords_continue(self):
        db = _DBSession()
        run_results = [
            EtimadProtectionError("challenge page"),
            SingleKeywordScrapeResult(
                keyword="telecom",
                fetched_pages=1,
                total_found=1,
                items=[{"reference_number": "RFQ-9", "tender_title": "Tender 9"}],
            ),
        ]

        with patch("app.services.scrape_service.list_saved_keywords", return_value=["gas", "telecom"]), patch(
            "app.services.scrape_service.run_single_keyword_scrape",
            new=AsyncMock(side_effect=run_results),
        ), patch(
            "app.services.scrape_service.upsert_tenders",
            return_value={
                "total_saved": 1,
                "inserted": 1,
                "updated": 0,
                "new_items": [],
            },
        ) as upsert, patch(
            "app.services.scrape_service._queue_auto_email",
            return_value=(False, None),
        ):
            response = await run_scrape_request(
                payload=ScrapeRequest(keyword=""),
                db=db,
                background_tasks=BackgroundTasks(),
            )

        self.assertEqual(response.execution_mode, "saved-keywords")
        self.assertEqual(response.executed_keywords, ["telecom"])
        self.assertEqual(len(response.failed_keywords), 1)
        self.assertEqual(response.failed_keywords[0].keyword, "gas")
        self.assertEqual(response.failed_keywords[0].error, "challenge page")
        self.assertEqual(len(response.items), 1)
        self.assertEqual(upsert.call_count, 1)
        self.assertEqual(db.rollback_count, 1)


if __name__ == "__main__":
    unittest.main()
