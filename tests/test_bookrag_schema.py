from __future__ import annotations

import unittest
from unittest import mock

from app.services.bookrag_schema import BOOKRAG_DOCUMENT_COLUMNS, _ensure_table


class BookragTablePreparationTests(unittest.TestCase):
    @mock.patch("app.services.bookrag_schema._count_teradata_rows", return_value=0)
    @mock.patch("app.services.bookrag_schema._teradata_table_exists", return_value=True)
    def test_existing_empty_compatible_table_is_reused(
        self,
        _exists_mock: mock.Mock,
        _count_mock: mock.Mock,
    ) -> None:
        execute_mock = mock.Mock()

        warnings = _ensure_table("demo", "store_bdoc", BOOKRAG_DOCUMENT_COLUMNS, execute_mock)

        self.assertEqual(
            warnings,
            ['Reused empty BookRAG target table after schema validation: "demo"."store_bdoc".'],
        )
        validation_sql = execute_mock.call_args.args[0]
        self.assertIn('SELECT "doc_id", "vector_store_name"', validation_sql)
        self.assertIn('FROM "demo"."store_bdoc" WHERE 1 = 0', validation_sql)

    @mock.patch("app.services.bookrag_schema._count_teradata_rows", return_value=3)
    @mock.patch("app.services.bookrag_schema._teradata_table_exists", return_value=True)
    def test_existing_nonempty_table_is_rejected(
        self,
        _exists_mock: mock.Mock,
        _count_mock: mock.Mock,
    ) -> None:
        execute_mock = mock.Mock()

        with self.assertRaisesRegex(RuntimeError, r"contains 3 row\(s\)"):
            _ensure_table("demo", "store_bdoc", BOOKRAG_DOCUMENT_COLUMNS, execute_mock)

        execute_mock.assert_not_called()

    @mock.patch("app.services.bookrag_schema._count_teradata_rows", return_value=None)
    @mock.patch("app.services.bookrag_schema._teradata_table_exists", return_value=True)
    def test_existing_table_is_rejected_when_row_count_is_unknown(
        self,
        _exists_mock: mock.Mock,
        _count_mock: mock.Mock,
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "row count could not be verified"):
            _ensure_table("demo", "store_bdoc", BOOKRAG_DOCUMENT_COLUMNS, mock.Mock())

    @mock.patch("app.services.bookrag_schema._count_teradata_rows", return_value=0)
    @mock.patch("app.services.bookrag_schema._teradata_table_exists", return_value=True)
    def test_existing_empty_incompatible_table_is_rejected(
        self,
        _exists_mock: mock.Mock,
        _count_mock: mock.Mock,
    ) -> None:
        execute_mock = mock.Mock(side_effect=RuntimeError("column does not exist"))

        with self.assertRaisesRegex(RuntimeError, "columns are incompatible"):
            _ensure_table("demo", "store_bdoc", BOOKRAG_DOCUMENT_COLUMNS, execute_mock)

    @mock.patch("app.services.bookrag_schema._teradata_table_exists", return_value=False)
    def test_missing_table_is_created(self, _exists_mock: mock.Mock) -> None:
        execute_mock = mock.Mock()

        warnings = _ensure_table("demo", "store_bdoc", BOOKRAG_DOCUMENT_COLUMNS, execute_mock)

        self.assertEqual(warnings, [])
        self.assertIn('CREATE SET TABLE "demo"."store_bdoc"', execute_mock.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
