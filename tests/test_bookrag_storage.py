from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.services.bookrag_schema import BOOKRAG_RAW_COLUMNS
from app.services.bookrag_storage import _insert_rows, _raw_row_to_element_dict, build_bookrag_raw_rows


class BookragRawStorageTests(unittest.TestCase):
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


    def test_insert_rows_writes_csv_stage_file(self) -> None:
        rows = [{"doc_id": "doc1", "filename": "demo.pdf"}]
        columns = [("doc_id", "VARCHAR(64)"), ("filename", "VARCHAR(255)")]
        executed: list[str] = []
        stats: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_dir = Path(tmpdir)
            inserted = _insert_rows(
                schema_name=None,
                table_name='demo_bdoc',
                rows=rows,
                columns=columns,
                execute_sql_fn=executed.append,
                csv_stage_dir=csv_dir,
                stats=stats,
            )
            csv_path = csv_dir / 'demo_bdoc.csv'
            self.assertTrue(csv_path.exists())
            content = csv_path.read_text(encoding='utf-8-sig')
            self.assertIn('doc_id,filename', content)
            self.assertIn('doc1,demo.pdf', content)
        self.assertEqual(inserted, 1)
        self.assertTrue(executed)
        self.assertIn('csv_files', stats)
        self.assertTrue(any(str(item).endswith('demo_bdoc.csv') for item in stats['csv_files']))


if __name__ == "__main__":
    unittest.main()
