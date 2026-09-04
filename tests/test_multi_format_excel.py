from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.services.multi_format_excel import (
    build_excel_headers,
    excel_column_name,
    partition_excel_chunks,
    read_excel_sheet_rows,
    split_text_with_overlap,
)


class MultiFormatExcelTests(unittest.TestCase):
    def test_reads_a_real_xlsx_workbook(self) -> None:
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook = Path(tmpdir) / "sample.xlsx"
            pd.DataFrame([["Name", "Amount"], ["Sales", 120]]).to_excel(
                workbook,
                index=False,
                header=False,
            )

            sheets = read_excel_sheet_rows(workbook)

        self.assertEqual(sheets, [("Sheet1", [(1, ["Name", "Amount"]), (2, ["Sales", "120"])])])

    def test_column_names_and_duplicate_headers_are_stable(self) -> None:
        self.assertEqual(excel_column_name(1), "A")
        self.assertEqual(excel_column_name(27), "AA")
        self.assertEqual(build_excel_headers(["Name", "Name", ""]), ["Name", "Name (2)", "Column C"])

    def test_split_text_preserves_overlap(self) -> None:
        parts = split_text_with_overlap("alpha beta gamma delta", max_chars=12, overlap_chars=3)

        self.assertGreater(len(parts), 1)
        self.assertTrue(all(part for part in parts))
        self.assertEqual(" ".join(parts).split()[0], "alpha")

    def test_partition_builds_structured_rows_through_the_supplied_mapper(self) -> None:
        source = Path("quarterly.xlsx")

        def mapper(element, *, src, content_type, row_sequence):
            self.assertEqual(element["id"], element["element_id"])
            return {
                "id": element["id"],
                "text": element["text"],
                "source": src.name,
                "content_type": content_type,
                "sequence": row_sequence,
            }

        rows = [(1, ["Account", "Amount"]), (2, ["Sales", "120"])]
        with patch("app.services.multi_format_excel.read_excel_sheet_rows", return_value=[("Q1", rows)]):
            table_rows, raw_elements, summary = partition_excel_chunks(
                source,
                chunk_size=32000,
                chunk_overlap=100,
                element_to_chunk_row=mapper,
            )

        self.assertEqual(len(table_rows), 1)
        self.assertEqual(len(raw_elements), 1)
        self.assertIn("Account: Sales", table_rows[0]["text"])
        self.assertEqual(summary["sheet_names"], ["Q1"])
        self.assertEqual(summary["logical_row_count"], 1)


if __name__ == "__main__":
    unittest.main()
