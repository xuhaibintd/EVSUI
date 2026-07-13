from __future__ import annotations

import unittest

from app.services.bookrag_integrity import validate_bookrag_dataset_relationships


def _core_rows():
    document = {"doc_id": "doc-1"}
    raw = [{"doc_id": "doc-1", "ordinal_raw": 1}]
    blocks = [{"doc_id": "doc-1", "element_id": "element-1"}]
    nodes = [
        {
            "doc_id": "doc-1",
            "node_id": "root",
            "node_type": "document",
            "parent_node_id": None,
            "source_element_id": None,
        },
        {
            "doc_id": "doc-1",
            "node_id": "node-1",
            "node_type": "text",
            "parent_node_id": "root",
            "source_element_id": "element-1",
        },
    ]
    return document, raw, blocks, nodes


class BookRAGIntegrityTests(unittest.TestCase):
    def test_valid_core_and_graph_relationships_pass(self) -> None:
        document, raw, blocks, nodes = _core_rows()
        entities = [{"doc_id": "doc-1", "entity_id": "entity-1"}]
        links = [
            {
                "doc_id": "doc-1",
                "link_id": "link-1",
                "node_id": "node-1",
                "entity_id": "entity-1",
                "section_node_id": None,
            }
        ]
        relations = [
            {
                "doc_id": "doc-1",
                "relation_id": "relation-1",
                "source_element_id": "element-1",
                "source_node_id": "node-1",
                "section_node_id": None,
                "from_entity_id": "entity-1",
                "to_entity_id": "entity-1",
            }
        ]

        validate_bookrag_dataset_relationships(
            document_row=document,
            raw_rows=raw,
            blocks=blocks,
            nodes=nodes,
            entities=entities,
            entity_links=links,
            entity_relations=relations,
            graph_enabled=True,
        )

    def test_duplicate_block_key_fails_before_persistence(self) -> None:
        document, raw, blocks, nodes = _core_rows()
        blocks.append(dict(blocks[0]))

        with self.assertRaisesRegex(RuntimeError, "duplicate primary key"):
            validate_bookrag_dataset_relationships(
                document_row=document,
                raw_rows=raw,
                blocks=blocks,
                nodes=nodes,
                entities=[],
                entity_links=[],
                entity_relations=[],
                graph_enabled=False,
            )

    def test_missing_graph_target_fails_before_persistence(self) -> None:
        document, raw, blocks, nodes = _core_rows()
        links = [
            {
                "doc_id": "doc-1",
                "link_id": "link-1",
                "node_id": "node-1",
                "entity_id": "missing-entity",
                "section_node_id": None,
            }
        ]

        with self.assertRaisesRegex(RuntimeError, "entity_link_entity"):
            validate_bookrag_dataset_relationships(
                document_row=document,
                raw_rows=raw,
                blocks=blocks,
                nodes=nodes,
                entities=[],
                entity_links=links,
                entity_relations=[],
                graph_enabled=True,
            )


if __name__ == "__main__":
    unittest.main()
