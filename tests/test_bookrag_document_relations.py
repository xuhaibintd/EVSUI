from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.services.bookrag_document_relations import (
    suggest_document_relations,
    validate_document_relation,
    validate_document_relations,
)
from app.services.bookrag_retrieval import render_bookrag_evidence_packages
from app.services.bookrag_schema import (
    BOOKRAG_DOCUMENT_RELATION_COLUMNS,
    _build_table_ddl,
    build_bookrag_relationship_contract,
)
from app.utils.uploads import save_document_uploads


class _Upload:
    def __init__(self, filename: str, payload: bytes):
        self.filename = filename
        self._payload = payload

    async def read(self) -> bytes:
        return self._payload


class BookRAGDocumentRelationTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_assigns_stable_document_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            upload_dir = project / "uploads"
            upload_dir.mkdir()
            rows, notices = await save_document_uploads(
                [_Upload("①GMAP_2026年春号（銀行）.pdf", b"pdf")],
                upload_dir,
                project,
                lambda: "2026-07-14 00:00:00",
            )
        self.assertEqual(notices, [])
        self.assertEqual(len(rows[0]["doc_id"]), 32)
        self.assertEqual(rows[0]["filename"], rows[0]["name"])

    def test_filename_rules_suggest_summary_and_real_issue_order(self) -> None:
        documents = [
            {"doc_id": "newyear", "filename": "①GMAP_2025年新春号（銀行）.pdf"},
            {"doc_id": "autumn", "filename": "①GMAP_2025年秋号（銀行）.pdf"},
            {"doc_id": "summer", "filename": "①GMAP_2026年夏号（銀行）.pdf"},
            {"doc_id": "spring", "filename": "①GMAP_2026年春号（銀行）.pdf"},
            {"doc_id": "summary", "filename": "②【A3両面印刷】GMAPサマリー_2026年春号（銀行）.pdf"},
        ]
        rows = suggest_document_relations(documents)
        keys = {
            (row["from_doc_id"], row["relation_type"], row["to_doc_id"])
            for row in rows
        }
        self.assertIn(("summary", "summary_of", "spring"), keys)
        self.assertIn(("spring", "next_issue_of", "autumn"), keys)
        self.assertIn(("summer", "next_issue_of", "spring"), keys)
        self.assertTrue(all(row["confirmed"] is False for row in rows))
        self.assertTrue(all(row["is_active"] == 0 for row in rows))
        self.assertTrue(all(row["from_filename"] and row["to_filename"] for row in rows))
        self.assertTrue(all(row["relation_description"] for row in rows))

    def test_validation_uses_doc_id_as_key_and_canonical_filename_as_snapshot(self) -> None:
        documents = [
            {"doc_id": "a", "filename": "A.pdf"},
            {"doc_id": "b", "filename": "B.pdf"},
        ]
        row = validate_document_relation(
            {
                "from_doc_id": "a",
                "from_filename": "wrong.pdf",
                "relation_type": "related_to",
                "to_doc_id": "b",
                "to_filename": "also-wrong.pdf",
                "confirmed": True,
            },
            documents,
        )
        self.assertEqual(row["from_filename"], "A.pdf")
        self.assertEqual(row["to_filename"], "B.pdf")
        with self.assertRaisesRegex(ValueError, "cannot relate to itself"):
            validate_document_relation(
                {
                    "from_doc_id": "a",
                    "relation_type": "related_to",
                    "to_doc_id": "a",
                    "confirmed": True,
                },
                documents,
            )

    def test_duplicate_logical_relationship_is_rejected(self) -> None:
        documents = [
            {"doc_id": "a", "filename": "A.pdf"},
            {"doc_id": "b", "filename": "B.pdf"},
        ]
        relation = {
            "from_doc_id": "a",
            "relation_type": "references",
            "to_doc_id": "b",
            "confirmed": True,
        }
        with self.assertRaisesRegex(ValueError, "Duplicate document relationship"):
            validate_document_relations([relation, relation], documents)

    def test_schema_and_mcp_contract_expose_bdrel_as_core(self) -> None:
        ddl = _build_table_ddl('"db"."vs_bk_bdrel"', BOOKRAG_DOCUMENT_RELATION_COLUMNS)
        self.assertIn('PRIMARY KEY ("from_doc_id", "relation_type", "to_doc_id")', ddl)
        contract = build_bookrag_relationship_contract("demo")
        self.assertEqual(contract["tables"]["document_relations"]["role"], "core")
        names = {row["name"] for row in contract["relationships"]}
        self.assertIn("document_relation_source", names)
        self.assertIn("document_relation_target", names)

    def test_retrieval_render_includes_human_readable_document_relation(self) -> None:
        text = render_bookrag_evidence_packages(
            [
                {
                    "rank": 1,
                    "match": {"node_id": "n1", "content": "content"},
                    "document": {"filename": "2026夏号.pdf"},
                    "document_relations": [
                        {
                            "direction": "outgoing",
                            "relation_type": "next_issue_of",
                            "related_filename": "2026春号.pdf",
                            "relation_description": "Previous issue",
                        }
                    ],
                }
            ]
        )
        self.assertIn("Document: 2026夏号.pdf", text)
        self.assertIn("next_issue_of -> 2026春号.pdf", text)
        self.assertIn("Previous issue", text)


if __name__ == "__main__":
    unittest.main()
