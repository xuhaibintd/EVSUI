from __future__ import annotations

import unittest

from app.routers.api import (
    _build_bookrag_dummy_answer,
    _build_bookrag_dummy_data,
    _build_bookrag_llm_input,
)


class BookRAGApiDummyDataTests(unittest.TestCase):
    def test_dummy_data_default_date_is_stable(self) -> None:
        payload = _build_bookrag_dummy_data(
            question="q",
            vector_store_name="vs",
            schema_name=None,
        )

        self.assertEqual(payload["dummy_date"], "2099-12-31")

    def test_dummy_data_shape_is_stable(self) -> None:
        payload = _build_bookrag_dummy_data(
            question="What is the connectivity status?",
            vector_store_name="demo_vs",
            schema_name="demo_schema",
        )

        self.assertEqual(payload["status"], "dummy")
        self.assertEqual(payload["api"], "bookrag.retrieve")
        self.assertEqual(payload["version"], "dummy-v1")
        self.assertEqual(payload["dummy_date"], "2099-12-31")
        self.assertEqual(payload["question_echo"], "What is the connectivity status?")
        self.assertEqual(payload["vector_store_name_echo"], "demo_vs")
        self.assertEqual(payload["schema_name_echo"], "demo_schema")
        self.assertEqual(payload["sample_entities"][0]["entity_type"], "ORGANIZATION")
        self.assertEqual(payload["sample_mapping"][0]["node_id"], "node-demo-001")
        self.assertEqual(payload["sample_match"]["source_block_id"], "block-demo-001")


class BookRAGApiAnswerShapeTests(unittest.TestCase):
    def test_llm_input_contains_evidence_items(self) -> None:
        evidence = {
            "packages": [
                {
                    "rank": 1,
                    "score": 0.99,
                    "match": {
                        "node_id": "node-1",
                        "title": "?1???????????",
                        "content": "??????????",
                        "path": "???? > ????",
                        "page_start": 2,
                        "page_end": 2,
                        "source_block_id": "block-1",
                    },
                    "section": {
                        "title": "????",
                        "path": "???? > ????",
                        "page_start": 2,
                        "page_end": 2,
                    },
                    "block": {
                        "text": "??????????",
                        "text_as_html": None,
                        "image_caption": None,
                        "image_context": None,
                    },
                }
            ]
        }

        payload = _build_bookrag_llm_input(
            question="?3??????????????",
            evidence=evidence,
            top_k=5,
            include_entities=True,
            include_mapping=True,
        )

        self.assertEqual(payload["question"], "?3??????????????")
        self.assertEqual(len(payload["instructions"]), 4)
        self.assertEqual(len(payload["evidence"]), 1)
        self.assertEqual(payload["evidence"][0]["title"], "?1???????????")
        self.assertEqual(payload["evidence"][0]["pages"], [2, 2])

    def test_dummy_answer_contains_citations(self) -> None:
        llm_input = {
            "question": "?3??????????????",
            "instructions": [],
            "evidence": [
                {
                    "rank": 1,
                    "title": "?1???????????",
                    "section_title": "????",
                    "path": "???? > ????",
                    "pages": [2, 2],
                    "node_id": "node-1",
                    "source_block_id": "block-1",
                }
            ],
        }

        answer = _build_bookrag_dummy_answer(
            question="?3??????????????",
            llm_input=llm_input,
        )

        self.assertEqual(answer["mode"], "dummy")
        self.assertTrue(answer["grounded"])
        self.assertEqual(answer["citations"][0]["node_id"], "node-1")
        self.assertIn("?????", answer["text"])


if __name__ == "__main__":
    unittest.main()
