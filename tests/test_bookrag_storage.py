from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from app.services.bookrag_schema import (
    BOOKRAG_ENTITY_LINK_COLUMNS,
    BOOKRAG_ENTITY_RELATION_COLUMNS,
    BOOKRAG_NODE_COLUMNS,
    BOOKRAG_RAW_COLUMNS,
    _build_table_ddl,
)
from app.services.bookrag_storage import _as_text, _csv_safe_value, _insert_rows, _load_csv_to_teradata, _raw_row_to_element_dict, build_bookrag_raw_rows, persist_bookrag_dataset


class BookragRawStorageTests(unittest.TestCase):
    def test_as_text_strips_invalid_unicode_for_teradata(self) -> None:
        raw = "A\x00B\ud800C\ufdd0D\uffffE🆓"
        self.assertEqual(_as_text(raw), "ABCDE")

    def test_raw_schema_includes_image_columns(self) -> None:
        column_names = [name for name, _ in BOOKRAG_RAW_COLUMNS]
        self.assertIn("image_caption", column_names)
        self.assertIn("image_context", column_names)

    def test_build_and_restore_raw_rows_preserves_image_metadata(self) -> None:
        elements = [
            {
                "type": "Image",
                "element_id": "img-1",
                "text": "Figure 1",
                "metadata": {
                    "page_number": 2,
                    "bookrag_image_caption": "Figure 1: Revenue trend",
                    "bookrag_image_context": "Bar chart comparing 2024 and 2025 quarterly revenue.",
                },
            }
        ]

        rows = build_bookrag_raw_rows(doc_id="doc123", elements=elements)

        self.assertEqual(rows[0]["image_caption"], "Figure 1: Revenue trend")
        self.assertEqual(rows[0]["image_context"], "Bar chart comparing 2024 and 2025 quarterly revenue.")

        restored = _raw_row_to_element_dict(rows[0])
        metadata = restored.get("metadata") or {}
        self.assertEqual(metadata.get("bookrag_image_caption"), "Figure 1: Revenue trend")
        self.assertEqual(metadata.get("bookrag_image_context"), "Bar chart comparing 2024 and 2025 quarterly revenue.")

    def test_csv_safe_value_replaces_flags_and_removes_other_supplementary_characters(self) -> None:
        normalized, flag_characters, unsupported_characters = _csv_safe_value("US \U0001F1FA\U0001F1F8 EU \U0001F1EA\U0001F1FA smile \U0001F600")

        self.assertEqual(normalized, "US [US] EU [EU] smile ")
        self.assertEqual(flag_characters, 4)
        self.assertEqual(unsupported_characters, 1)

    def test_node_ddl_uses_document_and_node_composite_primary_key(self) -> None:
        ddl = _build_table_ddl('"demo"."bnode"', BOOKRAG_NODE_COLUMNS)

        self.assertIn('PRIMARY KEY ("doc_id", "node_id")', ddl)

    def test_graph_ddl_requires_strong_relationship_columns(self) -> None:
        link_ddl = _build_table_ddl('"demo"."belnk"', BOOKRAG_ENTITY_LINK_COLUMNS)
        relation_ddl = _build_table_ddl('"demo"."brel"', BOOKRAG_ENTITY_RELATION_COLUMNS)

        self.assertIn('"entity_id" VARCHAR(64) NOT NULL', link_ddl)
        self.assertIn('"node_id" VARCHAR(64) NOT NULL', link_ddl)
        self.assertIn('"source_element_id" VARCHAR(64) NOT NULL', relation_ddl)
        self.assertIn('"source_node_id" VARCHAR(64) NOT NULL', relation_ddl)
        self.assertIn('"from_entity_id" VARCHAR(64) NOT NULL', relation_ddl)
        self.assertIn('"to_entity_id" VARCHAR(64) NOT NULL', relation_ddl)

    def test_insert_rows_writes_clean_csv_then_uses_native_loader(self) -> None:
        rows = [{"doc_id": "doc1", "filename": "US \U0001F1FA\U0001F1F8 \U0001F600.pdf"}]
        columns = [("doc_id", "VARCHAR(64)"), ("filename", "VARCHAR(255)")]
        stats: dict[str, object] = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_dir = Path(tmpdir)
            with mock.patch(
                "app.services.bookrag_storage._load_csv_to_teradata",
                return_value=1,
            ) as load_mock:
                inserted = _insert_rows(
                    schema_name="demo_schema",
                    table_name="demo_bdoc",
                    rows=rows,
                    columns=columns,
                    execute_sql_fn=mock.Mock(),
                    csv_stage_dir=csv_dir,
                    stats=stats,
                )

            csv_path = csv_dir / "demo_bdoc.csv"
            content = csv_path.read_text(encoding="utf-8-sig")

        self.assertEqual(inserted, 1)
        self.assertIn("US [US] .pdf", content)
        self.assertNotIn("\U0001F1FA\U0001F1F8", content)
        self.assertNotIn("\U0001F600", content)
        self.assertEqual(stats["csv_flag_characters_replaced"], 2)
        self.assertEqual(stats["csv_unsupported_characters_removed"], 1)
        load_mock.assert_called_once_with(
            "demo_schema",
            "demo_bdoc",
            str(csv_path),
            1,
            stats=stats,
        )

    def test_native_csv_loader_uses_batch_for_small_csv(self) -> None:
        stats: dict[str, object] = {}
        cursor = mock.Mock()
        connection = mock.Mock()
        connection.connection.driver_connection.cursor.return_value = cursor
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "rows.csv"
            csv_path.write_text("doc_id\ndoc1\n", encoding="utf-8-sig")
            with mock.patch.dict("os.environ", {"BOOKRAG_CSV_FASTLOAD_MIN_ROWS": "100000"}), mock.patch(
                "teradataml.get_connection",
                return_value=connection,
            ):
                inserted = _load_csv_to_teradata(
                    "demo_schema",
                    "demo_bdoc",
                    str(csv_path),
                    1,
                    stats=stats,
                )

        self.assertEqual(inserted, 1)
        statement = cursor.execute.call_args.args[0]
        self.assertIn("{fn teradata_read_csv(", statement)
        self.assertIn('INSERT INTO "demo_schema"."demo_bdoc" VALUES (?)', statement)
        cursor.close.assert_called_once()
        self.assertEqual(stats["native_csv_batch_calls"], 1)

    def test_native_csv_loader_uses_fastloadcsv_for_large_csv(self) -> None:
        stats: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "rows.csv"
            csv_path.write_text("doc_id\ndoc1\ndoc2\n", encoding="utf-8-sig")
            with mock.patch.dict("os.environ", {"BOOKRAG_CSV_FASTLOAD_MIN_ROWS": "2"}), mock.patch(
                "teradataml.read_csv",
                return_value=object(),
            ) as read_csv_mock:
                inserted = _load_csv_to_teradata(
                    "demo_schema",
                    "demo_bdoc",
                    str(csv_path),
                    2,
                    stats=stats,
                )

        self.assertEqual(inserted, 2)
        self.assertTrue(read_csv_mock.call_args.kwargs["use_fastload"])
        self.assertTrue(read_csv_mock.call_args.kwargs["catch_errors_warnings"])
        self.assertEqual(stats["native_csv_fastload_calls"], 1)

    def test_native_csv_failure_is_not_hidden_by_non_native_fallback(self) -> None:
        rows = [{"doc_id": "doc1", "filename": "one.pdf"}]
        columns = [("doc_id", "VARCHAR(64)"), ("filename", "VARCHAR(255)")]
        execute_mock = mock.Mock()
        stats: dict[str, object] = {}

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch(
            "app.services.bookrag_storage._load_csv_to_teradata",
            side_effect=RuntimeError("native CSV failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "native CSV failed"):
                _insert_rows(
                    schema_name="demo_schema",
                    table_name="demo_bdoc",
                    rows=rows,
                    columns=columns,
                    execute_sql_fn=execute_mock,
                    csv_stage_dir=Path(tmpdir),
                    stats=stats,
                )

        execute_mock.assert_not_called()
        self.assertIn("native CSV failed", str(stats["native_csv_last_error"]))

    def test_persist_dataset_creates_one_csv_per_table_for_the_file(self) -> None:
        table_targets = {
            "documents": "demo_bdoc",
            "nodes": "demo_bnode",
            "entities": "demo_bent",
            "entity_links": "demo_belnk",
            "entity_relations": "demo_brel",
            "blocks": "demo_bblk",
        }
        document_rows = [{"doc_id": "doc1", "filename": "demo.pdf"}]
        node_rows = [{
            "node_id": "node-1",
            "doc_id": "doc1",
            "source_element_id": "blk-1",
            "parent_node_id": None,
            "node_type": "document",
            "level": 0,
            "ordinal": 1,
            "title": "demo",
            "content": "demo",
            "page_start": 1,
            "page_end": 1,
            "path": "/demo",
            "is_leaf": 1,
        }]
        stats: dict[str, object] = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_dir = Path(tmpdir)
            with mock.patch(
                "app.services.bookrag_storage._load_csv_to_teradata",
                side_effect=lambda schema, table, path, row_count, stats=None: row_count,
            ) as load_mock:
                inserted = persist_bookrag_dataset(
                    schema_name=None,
                    table_targets=table_targets,
                    document_rows=document_rows,
                    blocks=[],
                    nodes=node_rows,
                    entities=[],
                    entity_links=[],
                    entity_relations=[],
                    execute_sql_fn=mock.Mock(),
                    csv_stage_dir=csv_dir,
                    stats=stats,
                )
            csv_names = sorted(path.name for path in csv_dir.glob("*.csv"))

        self.assertEqual(inserted, 2)
        self.assertEqual(csv_names, ["demo_bdoc.csv", "demo_bnode.csv"])
        self.assertEqual(load_mock.call_count, 2)




if __name__ == "__main__":
    unittest.main()
