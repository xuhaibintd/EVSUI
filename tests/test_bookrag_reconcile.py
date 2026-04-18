from __future__ import annotations

import unittest

from app.services.bookrag_reconcile import reconcile_unstructured_elements


class BookragReconcileTests(unittest.TestCase):
    def test_table_caption_merge_preserves_entities_and_relationships(self) -> None:
        raw_elements = [
            {
                "type": "FigureCaption",
                "element_id": "cap-1",
                "text": "Table 1. Consolidated results",
                "metadata": {
                    "page_number": 1,
                    "entities": {
                        "items": [{"entity": "Demo Corp", "type": "ORGANIZATION"}],
                        "relationships": [
                            {"from": "Demo Corp", "relationship": "published_in", "to": "2026-04-18"}
                        ],
                    },
                },
            },
            {
                "type": "Table",
                "element_id": "tbl-1",
                "text": "Revenue 100",
                "metadata": {
                    "page_number": 1,
                    "entities": {
                        "items": [{"entity": "2026-04-18", "type": "DATE"}],
                        "relationships": [],
                    },
                },
            },
        ]

        reconciled = reconcile_unstructured_elements(raw_elements)

        self.assertEqual(len(reconciled), 1)
        table = reconciled[0]
        self.assertEqual(table["type"], "Table")
        self.assertEqual(table["metadata"]["bookrag_table_caption"], "Table 1. Consolidated results")
        self.assertEqual(
            {(item["entity"], item["type"]) for item in table["metadata"]["entities"]["items"]},
            {("Demo Corp", "ORGANIZATION"), ("2026-04-18", "DATE")},
        )
        self.assertEqual(
            table["metadata"]["entities"]["relationships"],
            [{"from": "Demo Corp", "relationship": "published_in", "to": "2026-04-18"}],
        )

    def test_table_note_merge_preserves_entities_and_relationships(self) -> None:
        raw_elements = [
            {
                "type": "Table",
                "element_id": "tbl-1",
                "text": "Revenue 100",
                "metadata": {
                    "page_number": 1,
                    "coordinates": {"points": [[0, 0], [0, 40], [100, 40], [100, 0]]},
                    "entities": {
                        "items": [{"entity": "Revenue", "type": "DOCUMENT"}],
                        "relationships": [],
                    },
                },
            },
            {
                "type": "NarrativeText",
                "element_id": "note-1",
                "text": "Insurance proceeds were recognized.",
                "metadata": {
                    "page_number": 1,
                    "coordinates": {"points": [[0, 50], [0, 70], [100, 70], [100, 50]]},
                    "entities": {
                        "items": [{"entity": "Insurance proceeds", "type": "MONEY"}],
                        "relationships": [
                            {"from": "Insurance proceeds", "relationship": "occurred_on", "to": "2026-04-18"}
                        ],
                    },
                },
            },
        ]

        reconciled = reconcile_unstructured_elements(raw_elements)

        self.assertEqual(len(reconciled), 1)
        table = reconciled[0]
        self.assertIn("Table note:", table["text"])
        self.assertEqual(table["metadata"]["bookrag_table_note"], "Insurance proceeds were recognized.")
        self.assertEqual(
            {(item["entity"], item["type"]) for item in table["metadata"]["entities"]["items"]},
            {("Revenue", "DOCUMENT"), ("Insurance proceeds", "MONEY")},
        )
        self.assertEqual(
            table["metadata"]["entities"]["relationships"],
            [{"from": "Insurance proceeds", "relationship": "occurred_on", "to": "2026-04-18"}],
        )

    def test_figure_merge_preserves_entities_and_relationships(self) -> None:
        raw_elements = [
            {
                "type": "Image",
                "element_id": "img-1",
                "text": "",
                "metadata": {
                    "page_number": 1,
                    "entities": {
                        "items": [{"entity": "Diagram A", "type": "DOCUMENT"}],
                        "relationships": [],
                    },
                },
            },
            {
                "type": "FigureCaption",
                "element_id": "cap-1",
                "text": "Figure 1. Diagram overview",
                "metadata": {
                    "page_number": 1,
                    "entities": {
                        "items": [{"entity": "Demo Corp", "type": "ORGANIZATION"}],
                        "relationships": [
                            {"from": "Demo Corp", "relationship": "contains", "to": "Diagram A"}
                        ],
                    },
                },
            },
        ]

        reconciled = reconcile_unstructured_elements(raw_elements)

        self.assertEqual(len(reconciled), 1)
        image = reconciled[0]
        self.assertEqual(image["type"], "Image")
        self.assertEqual(image["metadata"]["bookrag_image_caption"], "Figure 1. Diagram overview")
        self.assertEqual(
            {(item["entity"], item["type"]) for item in image["metadata"]["entities"]["items"]},
            {("Diagram A", "DOCUMENT"), ("Demo Corp", "ORGANIZATION")},
        )
        self.assertEqual(
            image["metadata"]["entities"]["relationships"],
            [{"from": "Demo Corp", "relationship": "contains", "to": "Diagram A"}],
        )


if __name__ == "__main__":
    unittest.main()
