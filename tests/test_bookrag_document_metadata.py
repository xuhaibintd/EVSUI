from __future__ import annotations

import unittest
from unittest import mock

from app.services.bookrag_document_metadata import (
    build_logical_document_key,
    derive_document_metadata,
    question_has_explicit_timeline,
    save_document_metadata,
)


class BookRAGDocumentMetadataDerivationTests(unittest.TestCase):
    def test_content_publication_date_precedes_filename_month(self) -> None:
        metadata = derive_document_metadata(
            filename="④GMAP月次アップデート_2026年6月（製本印刷用）.pdf",
            content_values=["発行日：2026年5月27日", "2026年6月の市場見通し"],
        )

        self.assertEqual(metadata["publication_date"], "2026-05-27")
        self.assertEqual(metadata["publication_date_source"], "content")
        self.assertEqual(metadata["publication_date_precision"], "day")
        self.assertEqual(metadata["document_series"], "monthly")
        self.assertEqual(metadata["document_role"], "comprehensive")
        self.assertEqual(metadata["metadata_status"], "confirmed")

    def test_six_digit_spot_filename_is_a_reviewable_fallback(self) -> None:
        metadata = derive_document_metadata(
            filename="⑤GMAP_Spot_260609「米超長期債の投資妙味は乏しいだろう」.pdf"
        )

        self.assertEqual(metadata["publication_date"], "2026-06-09")
        self.assertEqual(metadata["publication_date_source"], "filename")
        self.assertEqual(metadata["document_series"], "spot")
        self.assertEqual(metadata["document_role"], "update")
        self.assertEqual(metadata["metadata_status"], "review")

    def test_topics_performance_filename_classification(self) -> None:
        metadata = derive_document_metadata(
            filename="⑥GMAP不定期レポート_Topics_260608_パフォーマンス・レビュー.pdf"
        )

        self.assertEqual(metadata["publication_date"], "2026-06-08")
        self.assertEqual(metadata["document_series"], "topics")
        self.assertEqual(metadata["document_role"], "performance")

    def test_invalid_six_digit_date_is_not_accepted(self) -> None:
        metadata = derive_document_metadata(filename="GMAP_Spot_261332.pdf")

        self.assertIsNone(metadata["publication_date"])
        self.assertIsNone(metadata["publication_date_source"])
        self.assertEqual(metadata["metadata_status"], "missing")

    def test_revision_marker_and_filename_date_do_not_change_logical_key(self) -> None:
        original = build_logical_document_key("⑤GMAP_Spot_260608_米超長期債.pdf")
        revision = build_logical_document_key("⑤GMAP_Spot_260609_米超長期債_改訂版.pdf")

        self.assertEqual(original, revision)

    def test_explicit_timeline_detection_distinguishes_latest_only_question(self) -> None:
        self.assertFalse(question_has_explicit_timeline("債券の資産別見通しを要約してください"))
        self.assertFalse(question_has_explicit_timeline("最新の見通しを要約してください"))
        self.assertTrue(question_has_explicit_timeline("20260609と20260608を確認しましたか"))
        self.assertTrue(question_has_explicit_timeline("2026年6月時点の見通しは？"))


class BookRAGDocumentMetadataPersistenceTests(unittest.TestCase):
    @mock.patch(
        "app.services.bookrag_document_metadata.ensure_bookrag_retrieval_view",
        return_value="MUBKWM_bk_retrieval_v",
    )
    @mock.patch(
        "app.services.bookrag_document_metadata.fetch_document_metadata",
        return_value=[{"doc_id": "doc-1", "filename": "report.pdf"}],
    )
    def test_manual_save_sets_manual_source_and_ensures_view(
        self,
        _fetch_mock: mock.Mock,
        ensure_mock: mock.Mock,
    ) -> None:
        execute_mock = mock.Mock()

        saved = save_document_metadata(
            vector_store_name="MUBKWM",
            schema_name="usecases_japan",
            doc_id="doc-1",
            values={
                "publication_date": "2026-06-09",
                "document_series": "spot",
                "document_role": "update",
                "logical_document_key": "spot-report",
                "revision_no": "2",
                "metadata_status": "confirmed",
            },
            execute_sql_fn=execute_mock,
            username="admin",
        )

        self.assertEqual(saved["publication_date_source"], "manual")
        self.assertIn('"publication_date"=CAST(\'2026-06-09\' AS DATE)', execute_mock.call_args.args[0])
        self.assertIn('"metadata_updated_by"=CAST(\'admin\'', execute_mock.call_args.args[0])
        ensure_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
