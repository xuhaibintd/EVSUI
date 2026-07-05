from __future__ import annotations

import unittest

from app.services.bookrag_graph import build_bookrag_entities


class BookragGraphTests(unittest.TestCase):
    def test_build_bookrag_entities_uses_raw_metadata_entities_and_relationships(self) -> None:
        document_row = {"doc_id": "doc-1"}
        raw_elements = [
            {
                "element_id": "blk-1",
                "text": "Demo Corp published the report on 2026-02-09.",
                "metadata": {
                    "page_number": 1,
                    "entities": {
                        "items": [
                            {"entity": "Demo Corp", "type": "ORGANIZATION"},
                            {"entity": "2026-02-09", "type": "DATE"},
                        ],
                        "relationships": [
                            {"from": "Demo Corp", "relationship": "published_in", "to": "2026-02-09"}
                        ],
                    },
                },
            }
        ]
        nodes = [
            {
                "node_id": "sec-1",
                "doc_id": "doc-1",
                "source_block_id": "blk-0",
                "parent_node_id": None,
                "node_type": "section",
                "page_start": 1,
                "page_end": 1,
                "path": "demo.pdf > Section",
            },
            {
                "node_id": "leaf-1",
                "doc_id": "doc-1",
                "source_block_id": "blk-1",
                "parent_node_id": "sec-1",
                "node_type": "text",
                "page_start": 1,
                "page_end": 1,
                "path": "demo.pdf > Section",
            },
        ]

        entities, entity_links, entity_relations = build_bookrag_entities(document_row, raw_elements, nodes)

        self.assertEqual(len(entities), 2)
        self.assertEqual({row["display_name"] for row in entities}, {"Demo Corp", "2026-02-09"})
        self.assertEqual({row["entity_type"] for row in entities}, {"ORGANIZATION", "DATE"})
        self.assertEqual({row["mention_count"] for row in entities}, {1})
        self.assertEqual({row["node_count"] for row in entities}, {1})

        self.assertEqual(len(entity_links), 2)
        self.assertEqual({row["node_id"] for row in entity_links}, {"leaf-1"})
        self.assertEqual({row["section_node_id"] for row in entity_links}, {"sec-1"})
        self.assertEqual({row["source_field"] for row in entity_links}, {"metadata.entities.items"})
        self.assertEqual({row["section_path"] for row in entity_links}, {"demo.pdf > Section"})
        self.assertEqual({row["mention_text"] for row in entity_links}, {"Demo Corp", "2026-02-09"})

        self.assertEqual(len(entity_relations), 1)
        self.assertEqual(entity_relations[0]["relationship"], "published_in")
        self.assertEqual(entity_relations[0]["from_entity_text"], "Demo Corp")
        self.assertEqual(entity_relations[0]["to_entity_text"], "2026-02-09")
        self.assertEqual(entity_relations[0]["source_element_id"], "blk-1")
        self.assertEqual(entity_relations[0]["source_node_id"], "leaf-1")
        self.assertEqual(entity_relations[0]["section_node_id"], "sec-1")
        self.assertTrue(entity_relations[0]["from_entity_id"])
        self.assertTrue(entity_relations[0]["to_entity_id"])

    def test_build_bookrag_entities_uses_entity_name_when_source_text_is_empty(self) -> None:
        document_row = {"doc_id": "doc-1"}
        raw_elements = [
            {
                "element_id": "blk-1",
                "text": "",
                "metadata": {
                    "page_number": 2,
                    "entities": {
                        "items": [
                            {"entity": "Demo Corp", "type": "ORGANIZATION"},
                        ],
                    },
                },
            }
        ]
        nodes = [
            {
                "node_id": "leaf-1",
                "doc_id": "doc-1",
                "source_block_id": "blk-1",
                "parent_node_id": None,
                "node_type": "text",
                "page_start": 2,
                "page_end": 2,
                "path": "demo.pdf",
            },
        ]

        entities, entity_links, entity_relations = build_bookrag_entities(document_row, raw_elements, nodes)

        self.assertEqual(len(entities), 1)
        self.assertEqual(len(entity_links), 1)
        self.assertEqual(len(entity_relations), 0)
        self.assertEqual(entity_links[0]["mention_text"], "Demo Corp")


    def test_build_bookrag_entities_skips_invalid_normalized_entity_names(self) -> None:
        document_row = {"doc_id": "doc-1"}
        raw_elements = [
            {
                "element_id": "blk-1",
                "text": "1. placeholder",
                "metadata": {
                    "page_number": 3,
                    "entities": {
                        "items": [
                            {"entity": "(1)", "type": "ORGANIZATION"},
                            {"entity": "Demo Corp", "type": "ORGANIZATION"},
                        ],
                    },
                },
            }
        ]
        nodes = [
            {
                "node_id": "leaf-1",
                "doc_id": "doc-1",
                "source_block_id": "blk-1",
                "parent_node_id": None,
                "node_type": "text",
                "page_start": 3,
                "page_end": 3,
                "path": "demo.pdf",
            },
        ]

        entities, entity_links, entity_relations = build_bookrag_entities(document_row, raw_elements, nodes)

        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["display_name"], "Demo Corp")
        self.assertEqual(len(entity_links), 1)
        self.assertEqual(entity_links[0]["mention_text"], "Demo Corp")
        self.assertEqual(len(entity_relations), 0)

    def test_build_bookrag_entities_preserves_corporate_abbreviation_prefixes(self) -> None:
        document_row = {"doc_id": "doc-1"}
        raw_elements = [
            {
                "element_id": "blk-1",
                "text": "(?)Demo Holdings",
                "metadata": {
                    "page_number": 1,
                    "entities": {
                        "items": [
                            {"entity": "(?)Demo Holdings", "type": "ORGANIZATION"},
                        ],
                    },
                },
            }
        ]
        nodes = [
            {
                "node_id": "leaf-1",
                "doc_id": "doc-1",
                "source_block_id": "blk-1",
                "parent_node_id": None,
                "node_type": "text",
                "page_start": 1,
                "page_end": 1,
                "path": "demo.pdf",
            },
        ]

        entities, entity_links, _ = build_bookrag_entities(document_row, raw_elements, nodes)

        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["display_name"], "(?)Demo Holdings")
        self.assertEqual(entity_links[0]["mention_text"], "(?)Demo Holdings")

    def test_build_bookrag_entities_resolves_dates_by_exact_match_before_normalized_match(self) -> None:
        document_row = {"doc_id": "doc-1"}
        raw_elements = [
            {
                "element_id": "blk-1",
                "text": "Fiscal periods.",
                "metadata": {
                    "page_number": 1,
                    "entities": {
                        "items": [
                            {"entity": "2025?3??", "type": "DATE"},
                            {"entity": "2026?3??", "type": "DATE"},
                            {"entity": "2025?4?1?", "type": "DATE"},
                        ],
                        "relationships": [
                            {"from": "2026?3??", "relationship": "occurred_on", "to": "2025?4?1?"},
                        ],
                    },
                },
            }
        ]
        nodes = [
            {
                "node_id": "leaf-1",
                "doc_id": "doc-1",
                "source_block_id": "blk-1",
                "parent_node_id": None,
                "node_type": "text",
                "page_start": 1,
                "page_end": 1,
                "path": "demo.pdf",
            },
        ]

        entities, _, relations = build_bookrag_entities(document_row, raw_elements, nodes)
        entity_by_name = {row["display_name"]: row["entity_id"] for row in entities}

        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["from_entity_id"], entity_by_name["2026?3??"])
        self.assertEqual(relations[0]["to_entity_id"], entity_by_name["2025?4?1?"])

    def test_build_bookrag_entities_creates_relation_endpoint_entities_when_missing_from_items(self) -> None:
        document_row = {"doc_id": "doc-1"}
        raw_elements = [
            {
                "element_id": "blk-1",
                "text": "Relationship only payload.",
                "metadata": {
                    "page_number": 1,
                    "entities": {
                        "items": [],
                        "relationships": [
                            {"from": "Method Change", "relationship": "occurred_on", "to": "2026?4?1?"},
                        ],
                    },
                },
            }
        ]
        nodes = [
            {
                "node_id": "leaf-1",
                "doc_id": "doc-1",
                "source_block_id": "blk-1",
                "parent_node_id": None,
                "node_type": "text",
                "page_start": 1,
                "page_end": 1,
                "path": "demo.pdf",
            },
        ]

        entities, _, relations = build_bookrag_entities(document_row, raw_elements, nodes)
        entity_names = {row["display_name"] for row in entities}

        self.assertIn("Method Change", entity_names)
        self.assertIn("2026?4?1?", entity_names)
        self.assertTrue(relations[0]["from_entity_id"])
        self.assertTrue(relations[0]["to_entity_id"])

if __name__ == "__main__":
    unittest.main()
