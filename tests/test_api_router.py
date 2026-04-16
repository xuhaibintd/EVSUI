from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.routers.api import (
    _build_bookrag_dummy_answer,
    _build_bookrag_dummy_data,
    _build_bookrag_llm_input,
    _has_valid_external_api_token,
    api_bookrag_answer_get,
    api_bookrag_retrieve_get,
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


def _build_request(*, headers: dict[str, str] | None = None, cookies: dict[str, str] | None = None):
    raw_headers = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode("latin-1"), value.encode("latin-1")))
    if cookies:
        cookie_value = "; ".join(f"{key}={value}" for key, value in cookies.items())
        raw_headers.append((b"cookie", cookie_value.encode("latin-1")))
    app = SimpleNamespace(state=SimpleNamespace(user_sessions={}, chat_history=[]))
    return Request({"type": "http", "headers": raw_headers, "app": app})


class BookRAGApiAccessTests(unittest.IsolatedAsyncioTestCase):
    def test_external_api_token_accepts_bearer_and_x_api_key(self) -> None:
        with patch.dict(os.environ, {"EVSUI_API_TOKEN": "secret-token"}, clear=False):
            bearer_request = _build_request(headers={"authorization": "Bearer secret-token"})
            api_key_request = _build_request(headers={"x-api-key": "secret-token"})
            invalid_request = _build_request(headers={"x-api-key": "wrong-token"})

            self.assertTrue(_has_valid_external_api_token(bearer_request))
            self.assertTrue(_has_valid_external_api_token(api_key_request))
            self.assertFalse(_has_valid_external_api_token(invalid_request))

    async def test_retrieve_get_runs_real_lookup_when_query_params_are_present(self) -> None:
        request = _build_request(headers={"x-api-key": "secret-token"})
        evidence = {"packages": [{"rank": 1}], "package_count": 1}

        with patch.dict(os.environ, {"EVSUI_API_TOKEN": "secret-token"}, clear=False):
            with patch("app.routers.api._activate_session_state", return_value={}), patch(
                "app.routers.api._retrieve_bookrag_evidence_or_raise",
                return_value=("what is new", "demo_vs", evidence),
            ), patch("app.routers.api._build_bookrag_chat_reply", return_value="reply"):
                payload = await api_bookrag_retrieve_get(
                    request,
                    question="what is new",
                    vector_store_name="demo_vs",
                    schema_name="demo_schema",
                )

        self.assertEqual(payload["question"], "what is new")
        self.assertEqual(payload["vector_store_name"], "demo_vs")
        self.assertEqual(payload["schema_name"], "demo_schema")
        self.assertEqual(payload["evidence"], evidence)
        self.assertEqual(payload["assistant_message"], "reply")

    async def test_retrieve_get_without_params_still_returns_dummy_payload(self) -> None:
        request = _build_request()
        payload = await api_bookrag_retrieve_get(request)

        self.assertEqual(payload["vector_store_name"], "dummy_vs")
        self.assertEqual(payload["evidence"]["package_count"], 0)
        self.assertEqual(payload["dummy_data"]["status"], "dummy")

    async def test_answer_get_rejects_missing_auth(self) -> None:
        request = _build_request()

        with self.assertRaises(HTTPException) as ctx:
            await api_bookrag_answer_get(request, question="q", vector_store_name="vs")

        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
