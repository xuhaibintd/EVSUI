from __future__ import annotations

from pathlib import Path
from threading import Event
import tempfile
import unittest
from unittest import mock

from app.services.bookrag_schema import BOOKRAG_RAW_COLUMNS
from app.services.bookrag_storage import _as_text, _insert_rows, _raw_row_to_element_dict, build_bookrag_raw_rows, persist_bookrag_dataset


class BookragRawStorageTests(unittest.TestCase):
    def test_as_text_strips_invalid_unicode_for_teradata(self) -> None:
        raw = "A\x00B\ud800C\ufdd0D\uffffE"
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

    def test_insert_rows_emits_csv_stage_file(self) -> None:
        rows = [{"doc_id": "doc1", "filename": "demo.pdf"}]
        columns = [("doc_id", "VARCHAR(64)"), ("filename", "VARCHAR(255)")]
        executed: list[str] = []
        stats: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_dir = Path(tmpdir)

            def _execute(sql: str) -> None:
                executed.append(sql)

            inserted = _insert_rows(
                schema_name=None,
                table_name="demo_bdoc",
                rows=rows,
                columns=columns,
                execute_sql_fn=_execute,
                csv_stage_dir=csv_dir,
                stats=stats,
            )
            csv_path = csv_dir / "demo_bdoc.csv"
            self.assertTrue(csv_path.exists())
            content = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("doc_id,filename", content)
            self.assertIn("doc1,demo.pdf", content)
        self.assertEqual(inserted, 1)
        self.assertTrue(executed)
        self.assertIn("csv_files", stats)
        self.assertTrue(any(str(item).endswith("demo_bdoc.csv") for item in stats["csv_files"]))

    def test_insert_rows_runs_csv_write_in_parallel_with_execute(self) -> None:
        rows = [{"doc_id": "doc1", "filename": "demo.pdf"}]
        columns = [("doc_id", "VARCHAR(64)"), ("filename", "VARCHAR(255)")]
        csv_started = Event()
        allow_csv_finish = Event()
        stats: dict[str, object] = {}

        def _fake_write_rows_csv(csv_stage_dir, table_name, write_rows, write_columns):
            csv_started.set()
            self.assertTrue(allow_csv_finish.wait(timeout=1.0))
            csv_path = Path(csv_stage_dir) / f"{table_name}.csv"
            csv_path.write_text("doc_id,filename\ndoc1,demo.pdf\n", encoding="utf-8-sig")
            return str(csv_path)

        executed: list[str] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_dir = Path(tmpdir)
            with mock.patch("app.services.bookrag_storage._write_rows_csv", side_effect=_fake_write_rows_csv):
                def _execute(sql: str) -> None:
                    self.assertTrue(csv_started.wait(timeout=1.0))
                    executed.append(sql)
                    allow_csv_finish.set()

                inserted = _insert_rows(
                    schema_name=None,
                    table_name="demo_bdoc",
                    rows=rows,
                    columns=columns,
                    execute_sql_fn=_execute,
                    csv_stage_dir=csv_dir,
                    stats=stats,
                )

        self.assertEqual(inserted, 1)
        self.assertEqual(len(executed), 1)
        self.assertEqual(stats.get("csv_parallel_calls"), 1)

    def test_persist_dataset_defers_csv_wait_until_all_tables_finish(self) -> None:
        table_targets = {
            "documents": "demo_bdoc",
            "nodes": "demo_bnode",
            "entities": "demo_bent",
            "entity_links": "demo_belnk",
            "entity_relations": "demo_brel",
            "blocks": "demo_bblk",
        }
        document_rows = [{"doc_id": "doc1", "filename": "demo.pdf"}]
        node_rows = [
            {
                "node_id": "node-1",
                "doc_id": "doc1",
                "parent_node_id": None,
                "source_block_id": "blk-1",
                "node_type": "document",
                "level": 0,
                "ordinal": 1,
                "page_start": 1,
                "page_end": 1,
                "title": "demo",
                "content": "demo",
                "path": "/demo",
                "is_leaf": 1,
            }
        ]
        first_csv_started = Event()
        allow_first_csv_finish = Event()
        csv_calls: list[str] = []
        executed: list[str] = []
        stats: dict[str, object] = {}

        def _fake_write_rows_csv(csv_stage_dir, table_name, write_rows, write_columns):
            csv_calls.append(table_name)
            if table_name == "demo_bdoc":
                first_csv_started.set()
                self.assertTrue(allow_first_csv_finish.wait(timeout=1.0))
            csv_path = Path(csv_stage_dir) / f"{table_name}.csv"
            csv_path.write_text("ok\n", encoding="utf-8-sig")
            return str(csv_path)

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_dir = Path(tmpdir)
            with mock.patch("app.services.bookrag_storage._write_rows_csv", side_effect=_fake_write_rows_csv):
                def _execute(sql: str) -> None:
                    self.assertTrue(first_csv_started.wait(timeout=1.0))
                    executed.append(sql)
                    if len(executed) >= 2:
                        allow_first_csv_finish.set()

                inserted = persist_bookrag_dataset(
                    schema_name=None,
                    table_targets=table_targets,
                    document_rows=document_rows,
                    blocks=[],
                    nodes=node_rows,
                    entities=[],
                    entity_links=[],
                    entity_relations=[],
                    execute_sql_fn=_execute,
                    csv_stage_dir=csv_dir,
                    stats=stats,
                )

        self.assertEqual(inserted, 2)
        self.assertGreaterEqual(len(executed), 2)
        self.assertEqual(stats.get("csv_parallel_calls"), 2)
        self.assertIn("demo_bdoc", csv_calls)
        self.assertIn("demo_bnode", csv_calls)


if __name__ == "__main__":
    unittest.main()
