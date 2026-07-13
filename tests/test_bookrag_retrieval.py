from __future__ import annotations

import re
import unittest

from app.services.bookrag_retrieval import (
    _extract_similarity_matches,
    build_bookrag_evidence_packages,
)
from app.services.bookrag_schema import build_bookrag_relationship_contract, build_bookrag_table_targets


class _SimilarityResult:
    def __init__(self, rows):
        self._json_obj = rows


class _Cursor:
    def __init__(self, columns, rows):
        self.description = [(column,) for column in columns]
        self._rows = [tuple(row.get(column) for column in columns) for row in rows]

    def fetchall(self):
        return self._rows


class BookRAGRetrievalRelationshipTests(unittest.TestCase):
    def test_relationship_contract_uses_document_scoped_keys(self) -> None:
        contract = build_bookrag_relationship_contract("demo")
        self.assertEqual(
            contract["tables"]["nodes"]["primary_key"],
            ["doc_id", "node_id"],
        )
        self.assertEqual(contract["tables"]["nodes"]["role"], "core")
        self.assertEqual(contract["tables"]["entities"]["role"], "graph")
        relationships = {item["name"]: item for item in contract["relationships"]}
        self.assertEqual(
            relationships["block_document"]["from_columns"],
            ["doc_id"],
        )
        self.assertEqual(
            relationships["node_source_block"]["from_columns"],
            ["doc_id", "source_element_id"],
        )
        self.assertEqual(
            relationships["node_source_block"]["to_columns"],
            ["doc_id", "element_id"],
        )
        self.assertEqual(
            relationships["entity_link_entity"]["from_columns"],
            ["doc_id", "entity_id"],
        )
        self.assertEqual(relationships["entity_link_entity"]["strength"], "required")
        self.assertEqual(relationships["relation_section"]["strength"], "optional")
        self.assertIn("entity_link_document", relationships)
        self.assertIn("relation_document", relationships)
        self.assertNotIn("raw", contract["tables"])
        self.assertNotIn("chunks", contract["tables"])
    def test_similarity_result_preserves_composite_vector_key(self) -> None:
        result = _SimilarityResult(
            [
                {
                    "Score": 0.91,
                    "DatabaseName": "demo_schema",
                    "TableName": "demo_bnode",
                    "doc_id": "doc-a",
                    "node_id": "node-a",
                    "content": "Evidence A",
                    "IndexLabel": "idx",
                }
            ]
        )

        matches, schema_name = _extract_similarity_matches(result)

        self.assertEqual(schema_name, "demo_schema")
        self.assertEqual(matches[0]["doc_id"], "doc-a")
        self.assertEqual(matches[0]["node_id"], "node-a")
        self.assertEqual(matches[0]["content"], "Evidence A")

    def test_query_chain_scopes_every_relationship_by_document(self) -> None:
        vector_store_name = "demo"
        targets = build_bookrag_table_targets(vector_store_name)
        tables = {
            targets["nodes"]: [
                {
                    "doc_id": "doc-a",
                    "node_id": "root",
                    "source_element_id": None,
                    "parent_node_id": None,
                    "node_type": "document",
                    "level": 0,
                    "ordinal": 0,
                    "title": "A",
                    "content": None,
                    "page_start": 1,
                    "page_end": 1,
                    "path": "A",
                    "is_leaf": 0,
                },
                {
                    "doc_id": "doc-b",
                    "node_id": "root",
                    "source_element_id": None,
                    "parent_node_id": None,
                    "node_type": "document",
                    "level": 0,
                    "ordinal": 0,
                    "title": "B",
                    "content": None,
                    "page_start": 1,
                    "page_end": 1,
                    "path": "B",
                    "is_leaf": 0,
                },
                {
                    "doc_id": "doc-a",
                    "node_id": "shared-node",
                    "source_element_id": "shared-element",
                    "parent_node_id": "root",
                    "node_type": "text",
                    "level": 1,
                    "ordinal": 1,
                    "title": None,
                    "content": "Evidence A",
                    "page_start": 1,
                    "page_end": 1,
                    "path": "A",
                    "is_leaf": 1,
                },
                {
                    "doc_id": "doc-b",
                    "node_id": "shared-node",
                    "source_element_id": "shared-element",
                    "parent_node_id": "root",
                    "node_type": "text",
                    "level": 1,
                    "ordinal": 1,
                    "title": None,
                    "content": "Evidence B",
                    "page_start": 1,
                    "page_end": 1,
                    "path": "B",
                    "is_leaf": 1,
                },
            ],
            targets["blocks"]: [
                {
                    "doc_id": "doc-a",
                    "element_id": "shared-element",
                    "type": "NarrativeText",
                    "page_number": 1,
                    "ordinal": 1,
                    "text": "Block A",
                    "text_as_html": None,
                    "image_caption": None,
                    "image_context": None,
                },
                {
                    "doc_id": "doc-b",
                    "element_id": "shared-element",
                    "type": "NarrativeText",
                    "page_number": 1,
                    "ordinal": 1,
                    "text": "Block B",
                    "text_as_html": None,
                    "image_caption": None,
                    "image_context": None,
                },
            ],
            targets["documents"]: [
                {"doc_id": "doc-a", "filename": "a.pdf"},
                {"doc_id": "doc-b", "filename": "b.pdf"},
            ],
            targets["entity_links"]: [
                {
                    "doc_id": "doc-a",
                    "link_id": "shared-link",
                    "entity_id": "shared-entity",
                    "node_id": "shared-node",
                    "section_node_id": None,
                    "source_field": "test",
                    "mention_text": "Entity A",
                    "page_start": 1,
                    "page_end": 1,
                    "ordinal": 1,
                    "section_path": "A",
                },
                {
                    "doc_id": "doc-b",
                    "link_id": "shared-link",
                    "entity_id": "shared-entity",
                    "node_id": "shared-node",
                    "section_node_id": None,
                    "source_field": "test",
                    "mention_text": "Entity B",
                    "page_start": 1,
                    "page_end": 1,
                    "ordinal": 1,
                    "section_path": "B",
                },
            ],
            targets["entity_relations"]: [
                {
                    "doc_id": "doc-a",
                    "relation_id": "shared-relation",
                    "source_element_id": "shared-element",
                    "source_node_id": "shared-node",
                    "section_node_id": None,
                    "from_entity_id": "shared-entity",
                    "from_entity_text": "Entity A",
                    "relationship": "mentions",
                    "to_entity_id": "shared-entity",
                    "to_entity_text": "Entity A",
                    "page_start": 1,
                    "page_end": 1,
                    "ordinal": 1,
                    "section_path": "A",
                },
                {
                    "doc_id": "doc-b",
                    "relation_id": "shared-relation",
                    "source_element_id": "shared-element",
                    "source_node_id": "shared-node",
                    "section_node_id": None,
                    "from_entity_id": "shared-entity",
                    "from_entity_text": "Entity B",
                    "relationship": "mentions",
                    "to_entity_id": "shared-entity",
                    "to_entity_text": "Entity B",
                    "page_start": 1,
                    "page_end": 1,
                    "ordinal": 1,
                    "section_path": "B",
                },
            ],
            targets["entities"]: [
                {
                    "doc_id": "doc-a",
                    "entity_id": "shared-entity",
                    "canonical_name": "entity-a",
                    "display_name": "Entity A",
                    "entity_type": "TEST",
                    "mention_count": 1,
                    "node_count": 1,
                },
                {
                    "doc_id": "doc-b",
                    "entity_id": "shared-entity",
                    "canonical_name": "entity-b",
                    "display_name": "Entity B",
                    "entity_type": "TEST",
                    "mention_count": 1,
                    "node_count": 1,
                },
            ],
        }
        executed_sql: list[str] = []

        def execute_sql(statement: str):
            executed_sql.append(statement)
            table_name = next(name for name in tables if f'"{name}"' in statement)
            select_text = statement.split(" FROM ", 1)[0].removeprefix("SELECT ")
            columns = re.findall(r'"([^"]+)"', select_text)
            # Deliberately return every row. Correct tuple-key maps must still
            # prevent one document from overwriting the other.
            return _Cursor(columns, tables.get(table_name, []))

        similarity_result = _SimilarityResult(
            [
                {
                    "Score": 0.99,
                    "DatabaseName": "demo_schema",
                    "doc_id": "doc-a",
                    "node_id": "shared-node",
                    "content": "Evidence A",
                },
                {
                    "Score": 0.98,
                    "DatabaseName": "demo_schema",
                    "doc_id": "doc-b",
                    "node_id": "shared-node",
                    "content": "Evidence B",
                },
            ]
        )

        packages, _ = build_bookrag_evidence_packages(
            vector_store_name=vector_store_name,
            similarity_result=similarity_result,
            execute_sql_fn=execute_sql,
        )

        self.assertEqual(len(packages), 2)
        package_by_doc = {package["match"]["doc_id"]: package for package in packages}
        self.assertEqual(package_by_doc["doc-a"]["block"]["text"], "Block A")
        self.assertEqual(package_by_doc["doc-b"]["block"]["text"], "Block B")
        self.assertEqual(package_by_doc["doc-a"]["entities"][0]["display_name"], "Entity A")
        self.assertEqual(package_by_doc["doc-b"]["entities"][0]["display_name"], "Entity B")
        self.assertEqual(package_by_doc["doc-a"]["mapping"][0]["mention_text"], "Entity A")
        self.assertEqual(package_by_doc["doc-b"]["mapping"][0]["mention_text"], "Entity B")
        self.assertEqual(package_by_doc["doc-a"]["relations"][0]["from_entity_text"], "Entity A")
        self.assertEqual(package_by_doc["doc-b"]["relations"][0]["from_entity_text"], "Entity B")

        block_sql = next(sql for sql in executed_sql if targets["blocks"] in sql)
        self.assertIn('"doc_id" = ' + "'doc-a'" + ' AND "element_id" = ' + "'shared-element'", block_sql)
        self.assertIn('"doc_id" = ' + "'doc-b'" + ' AND "element_id" = ' + "'shared-element'", block_sql)

        link_sql = next(sql for sql in executed_sql if targets["entity_links"] in sql)
        self.assertIn('"doc_id" = ' + "'doc-a'" + ' AND "node_id" = ' + "'shared-node'", link_sql)
        self.assertIn('"doc_id" = ' + "'doc-b'" + ' AND "node_id" = ' + "'shared-node'", link_sql)

        entity_sql = next(sql for sql in executed_sql if targets["entities"] in sql)
        self.assertIn('"doc_id" = ' + "'doc-a'" + ' AND "entity_id" = ' + "'shared-entity'", entity_sql)
        self.assertIn('"doc_id" = ' + "'doc-b'" + ' AND "entity_id" = ' + "'shared-entity'", entity_sql)


if __name__ == "__main__":
    unittest.main()
