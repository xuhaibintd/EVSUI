from __future__ import annotations

import unittest
from unittest import mock

from app.services.bookrag_schema import (
    BOOKRAG_DOCUMENT_COLUMNS,
    _ensure_table,
    migrate_bookrag_document_metadata_columns,
    ensure_bookrag_retrieval_view,
    prepare_bookrag_retrieval_view,
)


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

    @mock.patch("app.services.bookrag_schema._teradata_table_exists", return_value=True)
    def test_metadata_migration_adds_only_missing_columns(self, _exists_mock: mock.Mock) -> None:
        def execute(sql: str):
            if sql.startswith('SELECT TOP 1 "publication_date"'):
                raise RuntimeError("[3810] Column does not exist")
            return None

        execute_mock = mock.Mock(side_effect=execute)
        added = migrate_bookrag_document_metadata_columns(
            schema_name="demo",
            table_name="EXAMPLE_STORE_bk_bdoc",
            execute_sql_fn=execute_mock,
        )

        self.assertEqual(added, ("publication_date",))
        add_sql = [
            call.args[0]
            for call in execute_mock.call_args_list
            if call.args[0].startswith("ALTER TABLE")
        ]
        self.assertEqual(
            add_sql,
            ['ALTER TABLE "demo"."EXAMPLE_STORE_bk_bdoc" ADD "publication_date" DATE'],
        )

    def test_retrieval_view_ranks_effective_documents_by_publication_date(self) -> None:
        execute_mock = mock.Mock()

        view_name = prepare_bookrag_retrieval_view(
            vector_store_name="EXAMPLE_STORE",
            schema_name="example_database",
            execute_sql_fn=execute_mock,
        )

        self.assertEqual(view_name, "EXAMPLE_STORE_bk_retrieval_v")
        sql = execute_mock.call_args.args[0]
        self.assertIn('ORDER BY d."publication_date" DESC', sql)
        self.assertIn('r."relation_type" = \'updates\'', sql)
        self.assertIn('r."to_doc_id" = d."doc_id"', sql)
        self.assertIn('"example_database"."EXAMPLE_STORE_bk_bnode"', sql)

    def test_existing_retrieval_view_is_not_replaced_on_regular_access(self) -> None:
        execute_mock = mock.Mock()

        view_name = ensure_bookrag_retrieval_view(
            vector_store_name="EXAMPLE_STORE",
            schema_name="example_database",
            execute_sql_fn=execute_mock,
        )

        self.assertEqual(view_name, "EXAMPLE_STORE_bk_retrieval_v")
        self.assertEqual(execute_mock.call_count, 1)
        self.assertIn('SELECT TOP 1 "doc_id", "publication_date"', execute_mock.call_args.args[0])

    def test_missing_retrieval_view_is_created(self) -> None:
        execute_mock = mock.Mock(side_effect=[RuntimeError("[3807] Object does not exist"), None])

        view_name = ensure_bookrag_retrieval_view(
            vector_store_name="EXAMPLE_STORE",
            schema_name="example_database",
            execute_sql_fn=execute_mock,
        )

        self.assertEqual(view_name, "EXAMPLE_STORE_bk_retrieval_v")
        self.assertIn("REPLACE VIEW", execute_mock.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
