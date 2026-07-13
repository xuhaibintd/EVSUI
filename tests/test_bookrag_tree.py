from __future__ import annotations

import unittest

from app.services.bookrag_tree import _block_kind, build_bookrag_nodes, elements_to_bookrag_blocks


class BookragTreeTests(unittest.TestCase):
    def test_node_ids_are_namespaced_by_document(self) -> None:
        blocks = [
            {
                "element_id": "shared-vlm-element-id",
                "ordinal": 1,
                "block_type": "text",
                "text": "Same structural position in two documents.",
                "page_number": 1,
            }
        ]

        nodes_a = build_bookrag_nodes(
            {"doc_id": "doc-a", "filename": "a.pdf"}, blocks
        )
        nodes_b = build_bookrag_nodes(
            {"doc_id": "doc-b", "filename": "b.pdf"}, blocks
        )

        self.assertEqual(nodes_a[1]["source_element_id"], "shared-vlm-element-id")
        self.assertEqual(nodes_b[1]["source_element_id"], "shared-vlm-element-id")
        self.assertNotEqual(nodes_a[1]["node_id"], nodes_b[1]["node_id"])
        self.assertTrue(
            {node["node_id"] for node in nodes_a}.isdisjoint(
                node["node_id"] for node in nodes_b
            )
        )

    def test_heading_html_levels_drive_section_nesting_without_title_text_hardcoding(self) -> None:
        raw_elements = [
            {
                "type": "Title",
                "element_id": "title-1",
                "text": "Top Section",
                "metadata": {
                    "page_number": 1,
                    "category_depth": 1,
                    "text_as_html": "<h2>Top Section</h2>",
                },
            },
            {
                "type": "Title",
                "element_id": "title-2",
                "text": "Nested Section",
                "metadata": {
                    "page_number": 1,
                    "category_depth": 1,
                    "text_as_html": "<h3>Nested Section</h3>",
                },
            },
            {
                "type": "Title",
                "element_id": "title-3",
                "text": "6. Deposits and Loans",
                "metadata": {
                    "page_number": 2,
                    "category_depth": 1,
                },
            },
            {
                "type": "NarrativeText",
                "element_id": "text-1",
                "text": "Body text.",
                "metadata": {
                    "page_number": 1,
                    "category_depth": 2,
                    "text_as_html": "<p>Body text.</p>",
                },
            },
            {
                "type": "Header",
                "element_id": "header-1",
                "text": "Running header",
                "metadata": {
                    "page_number": 1,
                    "category_depth": 1,
                    "text_as_html": "<header>Running header</header>",
                },
            },
            {
                "type": "Table",
                "element_id": "table-1",
                "text": "Name Value Revenue 100",
                "metadata": {
                    "page_number": 1,
                    "category_depth": 2,
                    "text_as_html": "<table><tr><td>Revenue</td><td>100</td></tr></table>",
                },
            },
        ]
        document_row = {
            "doc_id": "doc-1",
            "filename": "demo.pdf",
            "page_count": 2,
        }

        blocks = elements_to_bookrag_blocks(
            doc_id="doc-1",
            src=None,
            content_type="application/pdf",
            raw_elements=raw_elements,
        )

        self.assertEqual([_block_kind(block) for block in blocks], ["section", "section", "section", "text", "table"])
        self.assertEqual(blocks[0]["heading_level"], 2)
        self.assertEqual(blocks[1]["heading_level"], 3)
        self.assertIsNone(blocks[2]["heading_level"])
        self.assertNotIn("header-1", [block["element_id"] for block in blocks])

        nodes = build_bookrag_nodes(document_row, blocks)

        self.assertEqual(nodes[1]["node_type"], "section")
        self.assertEqual(nodes[1]["title"], "Top Section")
        self.assertEqual(nodes[1]["level"], 2)
        self.assertEqual(nodes[1]["parent_node_id"], nodes[0]["node_id"])

        self.assertEqual(nodes[2]["node_type"], "section")
        self.assertEqual(nodes[2]["title"], "Nested Section")
        self.assertEqual(nodes[2]["level"], 3)
        self.assertEqual(nodes[2]["parent_node_id"], nodes[1]["node_id"])

        self.assertEqual(nodes[3]["node_type"], "section")
        self.assertEqual(nodes[3]["title"], "6. Deposits and Loans")
        self.assertEqual(nodes[3]["parent_node_id"], nodes[0]["node_id"])

        self.assertEqual(nodes[4]["node_type"], "text")
        self.assertEqual(nodes[5]["node_type"], "table")

    def test_numeric_sections_pop_bracket_groups_without_title_hardcoding(self) -> None:
        raw_elements = [
            {
                "type": "Title",
                "element_id": "major-1",
                "text": "5. Yield Analysis",
                "metadata": {
                    "page_number": 1,
                    "text_as_html": "<h2>5. Yield Analysis</h2>",
                },
            },
            {
                "type": "Title",
                "element_id": "group-1",
                "text": "?Trust Bank Standalone?",
                "metadata": {
                    "page_number": 1,
                    "text_as_html": "<h3>?Trust Bank Standalone?</h3>",
                },
            },
            {
                "type": "Title",
                "element_id": "major-2",
                "text": "6. Deposits and Loans",
                "metadata": {
                    "page_number": 2,
                    "text_as_html": "<h2>6. Deposits and Loans</h2>",
                },
            },
            {
                "type": "Title",
                "element_id": "group-2",
                "text": "?Bank Standalone?",
                "metadata": {
                    "page_number": 2,
                    "text_as_html": "<h3>?Bank Standalone?</h3>",
                },
            },
        ]

        blocks = elements_to_bookrag_blocks(
            doc_id="doc-1",
            src=None,
            content_type="application/pdf",
            raw_elements=raw_elements,
        )
        nodes = build_bookrag_nodes({"doc_id": "doc-1", "filename": "demo.pdf", "page_count": 2}, blocks)

        major_1 = nodes[1]
        group_1 = nodes[2]
        major_2 = nodes[3]
        group_2 = nodes[4]

        self.assertEqual(group_1["parent_node_id"], major_1["node_id"])
        self.assertEqual(major_2["parent_node_id"], nodes[0]["node_id"])
        self.assertEqual(group_2["parent_node_id"], major_2["node_id"])

    def test_enum_and_generic_titles_anchor_to_open_major_section(self) -> None:
        raw_elements = [
            {
                "type": "Title",
                "element_id": "major",
                "text": "2. Financial Statements",
                "metadata": {
                    "page_number": 1,
                    "text_as_html": "<h2>2. Financial Statements</h2>",
                },
            },
            {
                "type": "Title",
                "element_id": "enum-1",
                "text": "(1) Balance Sheet",
                "metadata": {
                    "page_number": 1,
                    "text_as_html": "<h3>(1) Balance Sheet</h3>",
                },
            },
            {
                "type": "Title",
                "element_id": "child-1",
                "text": "Quarterly Consolidated Balance Sheet",
                "metadata": {
                    "page_number": 1,
                    "text_as_html": "<h3>Quarterly Consolidated Balance Sheet</h3>",
                },
            },
            {
                "type": "Title",
                "element_id": "enum-2",
                "text": "(2) Income Statement and Comprehensive Income Statement",
                "metadata": {
                    "page_number": 2,
                    "text_as_html": "<h2>(2) Income Statement and Comprehensive Income Statement</h2>",
                },
            },
            {
                "type": "Title",
                "element_id": "child-2",
                "text": "Quarterly Consolidated Comprehensive Income Statement",
                "metadata": {
                    "page_number": 2,
                    "text_as_html": "<h2>Quarterly Consolidated Comprehensive Income Statement</h2>",
                },
            },
        ]

        blocks = elements_to_bookrag_blocks(
            doc_id="doc-1",
            src=None,
            content_type="application/pdf",
            raw_elements=raw_elements,
        )
        nodes = build_bookrag_nodes({"doc_id": "doc-1", "filename": "demo.pdf", "page_count": 2}, blocks)

        major = nodes[1]
        enum_1 = nodes[2]
        child_1 = nodes[3]
        enum_2 = nodes[4]
        child_2 = nodes[5]

        self.assertEqual(enum_1["parent_node_id"], major["node_id"])
        self.assertEqual(child_1["parent_node_id"], enum_1["node_id"])
        self.assertEqual(enum_2["parent_node_id"], major["node_id"])
        self.assertEqual(child_2["parent_node_id"], enum_2["node_id"])

    def test_fullwidth_numeric_and_generic_depth_reset_section_stack(self) -> None:
        raw_elements = [
            {
                "type": "Title",
                "element_id": "major-1",
                "text": "\uff11\uff0e\u9023\u7d50\u696d\u7e3e",
                "metadata": {"page_number": 1, "category_depth": 1},
            },
            {
                "type": "Title",
                "element_id": "enum-1",
                "text": "\uff081\uff09\u9023\u7d50\u7d4c\u55b6\u6210\u7e3e",
                "metadata": {"page_number": 1, "category_depth": 1},
            },
            {
                "type": "Title",
                "element_id": "major-2",
                "text": "\uff12\uff0e\u914d\u5f53\u306e\u72b6\u6cc1",
                "metadata": {"page_number": 1, "category_depth": 1},
            },
            {
                "type": "Title",
                "element_id": "generic-1",
                "text": "\u203b \u6ce8\u8a18\u4e8b\u9805",
                "metadata": {"page_number": 2, "category_depth": 1},
            },
        ]

        blocks = elements_to_bookrag_blocks(
            doc_id="doc-1",
            src=None,
            content_type="application/pdf",
            raw_elements=raw_elements,
        )
        nodes = build_bookrag_nodes({"doc_id": "doc-1", "filename": "demo.pdf", "page_count": 2}, blocks)

        major_1 = nodes[1]
        enum_1 = nodes[2]
        major_2 = nodes[3]
        generic_1 = nodes[4]

        self.assertEqual(enum_1["parent_node_id"], major_1["node_id"])
        self.assertEqual(major_2["parent_node_id"], nodes[0]["node_id"])
        self.assertEqual(generic_1["parent_node_id"], nodes[0]["node_id"])

    def test_segmented_leaf_titles_keep_unique_suffix_when_truncated(self) -> None:
        long_title = "X" * 1100
        blocks = [
            {
                "doc_id": "doc-1",
                "element_id": "table-1",
                "parent_id": None,
                "category_depth": 1,
                "heading_level": None,
                "page_number": 1,
                "ordinal": 1,
                "text": long_title,
                "type": "Table",
                "text_as_html": "<table><tr><td>" + ("value " * 400) + "</td></tr></table>",
                "image_caption": None,
                "image_context": None,
            }
        ]

        nodes = build_bookrag_nodes({"doc_id": "doc-1", "filename": "demo.pdf", "page_count": 1}, blocks)
        table_nodes = [node for node in nodes if node["node_type"] == "table"]

        self.assertGreater(len(table_nodes), 1)
        self.assertTrue(all(len(node["title"]) <= 1000 for node in table_nodes))
        self.assertNotEqual(table_nodes[0]["title"], table_nodes[1]["title"])
        self.assertTrue(table_nodes[0]["title"].endswith("[1/{}]".format(len(table_nodes))))
        self.assertTrue(table_nodes[1]["title"].endswith("[2/{}]".format(len(table_nodes))))


if __name__ == "__main__":
    unittest.main()
