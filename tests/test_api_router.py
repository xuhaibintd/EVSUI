from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.routers.api import (
    BookRAGEvidenceResponse,
    _build_bookrag_llm_input,
    _build_bookrag_live_answer_or_raise,
    _has_valid_external_api_token,
    _retrieve_bookrag_evidence_or_raise,
    api_bookrag_answer_get,
    api_bookrag_retrieve_get,
    api_bookrag_schema,
)


class BookRAGApiAnswerShapeTests(unittest.TestCase):
    def test_llm_input_contains_evidence_items(self) -> None:
        evidence = {
            "packages": [
                {
                    "rank": 1,
                    "score": 0.99,
                    "match": {
                        "node_id": "node-1",
                        "title": "総括",
                        "content": "増収増益だが成長は鈍化。",
                        "path": "決算短信 > 総括",
                        "page_start": 2,
                        "page_end": 2,
                        "source_element_id": "block-1",
                    },
                    "section": {
                        "title": "総括",
                        "path": "決算短信 > 総括",
                        "page_start": 2,
                        "page_end": 2,
                    },
                    "block": {
                        "text": "増収増益だが成長は鈍化。",
                        "text_as_html": None,
                        "image_caption": None,
                        "image_context": None,
                    },
                    "document": {"filename": "2026夏号.pdf"},
                    "document_relations": [
                        {
                            "direction": "outgoing",
                            "relation_type": "next_issue_of",
                            "related_filename": "2026春号.pdf",
                        }
                    ],
                }
            ]
        }

        payload = _build_bookrag_llm_input(
            question="決算の要点は？",
            evidence=evidence,
            top_k=5,
            include_entities=True,
            include_mapping=True,
        )

        self.assertEqual(payload["question"], "決算の要点は？")
        self.assertEqual(len(payload["instructions"]), 8)
        self.assertEqual(len(payload["evidence"]), 1)
        self.assertEqual(payload["evidence"][0]["title"], "総括")
        self.assertEqual(payload["evidence"][0]["pages"], [2, 2])
        self.assertEqual(payload["document"]["filename"], "2026夏号.pdf")
        self.assertEqual(
            payload["evidence"][0]["document_relations"][0]["related_filename"],
            "2026春号.pdf",
        )

    def test_governance_fields_survive_response_validation(self) -> None:
        payload = BookRAGEvidenceResponse.model_validate(
            {
                "vector_store_name": "demo",
                "package_count": 1,
                "similarity_row_count": 1,
                "similarity_preview": "",
                "evidence_text": "evidence",
                "retrieval_scope": {"mode": "adaptive_current_only"},
                "query_plan": {"facets": [{"query": "金利"}]},
                "coverage": {"sufficient": True},
                "packages": [
                    {
                        "rank": 1,
                        "retrieval_track": "latest_related",
                        "matched_facets": ["clause_1"],
                        "match": {"doc_id": "doc-1", "node_id": "node-1"},
                        "document": {
                            "doc_id": "doc-1",
                            "filename": "latest.pdf",
                            "publication_date": "2026-06-09",
                            "metadata_status": "confirmed",
                        },
                    }
                ],
            }
        ).model_dump()

        self.assertEqual(payload["retrieval_scope"]["mode"], "adaptive_current_only")
        self.assertEqual(payload["packages"][0]["retrieval_track"], "latest_related")
        self.assertEqual(
            payload["packages"][0]["document"]["publication_date"],
            "2026-06-09",
        )


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
    async def test_schema_endpoint_exposes_document_relation_contract(self) -> None:
        request = _build_request(headers={"x-api-key": "secret-token"})
        with patch.dict(os.environ, {"EVSUI_API_TOKEN": "secret-token"}, clear=False):
            payload = await api_bookrag_schema(
                request,
                vector_store_name="demo_vs",
                schema_name="demo_schema",
            )
        self.assertIn("document_relations", payload["contract"]["tables"])
        names = {row["name"] for row in payload["contract"]["relationships"]}
        self.assertIn("document_relation_source", names)
        self.assertIn("document_relation_target", names)

    def test_external_api_token_accepts_bearer_and_x_api_key(self) -> None:
        with patch.dict(os.environ, {"EVSUI_API_TOKEN": "secret-token"}, clear=False):
            bearer_request = _build_request(headers={"authorization": "Bearer secret-token"})
            api_key_request = _build_request(headers={"x-api-key": "secret-token"})
            invalid_request = _build_request(headers={"x-api-key": "wrong-token"})

            self.assertTrue(_has_valid_external_api_token(bearer_request))
            self.assertTrue(_has_valid_external_api_token(api_key_request))
            self.assertFalse(_has_valid_external_api_token(invalid_request))

    def test_application_settings_can_disable_external_api_even_when_env_has_a_token(self) -> None:
        request = _build_request(headers={"x-api-key": "secret-token"})
        request.app.state.settings = SimpleNamespace(
            external_api_enabled=False,
            external_api_token="secret-token",
        )

        with patch.dict(os.environ, {"EVSUI_API_TOKEN": "secret-token"}, clear=False):
            self.assertFalse(_has_valid_external_api_token(request))

    async def test_retrieve_get_runs_real_lookup_when_query_params_are_present(self) -> None:
        request = _build_request(headers={"x-api-key": "secret-token", "x-request-id": "req-123"})
        evidence = {"vector_store_name": "demo_vs", "packages": [{"rank": 1}], "package_count": 1}

        with patch.dict(os.environ, {"EVSUI_API_TOKEN": "secret-token"}, clear=False):
            with patch("app.routers.api._activate_session_state", return_value={}), patch(
                "app.routers.api._retrieve_bookrag_evidence_or_raise",
                return_value=("what is new", "demo_vs", evidence, object()),
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
        self.assertEqual(payload["meta"]["request_id"], "req-123")
        self.assertEqual(payload["meta"]["auth_mode"], "api_key")
        self.assertEqual(payload["evidence"]["package_count"], 1)
        self.assertEqual(payload["evidence"]["packages_total"], 1)
        self.assertEqual(payload["evidence"]["top_k_applied"], 5)
        self.assertEqual(payload["evidence"]["retrieval_source"], "bnode.content")
        self.assertEqual(payload["assistant_message"], "reply")

    async def test_retrieve_get_without_params_rejects_missing_auth(self) -> None:
        request = _build_request()

        with self.assertRaises(HTTPException) as ctx:
            await api_bookrag_retrieve_get(request)

        self.assertEqual(ctx.exception.status_code, 401)

    async def test_answer_get_rejects_missing_auth(self) -> None:
        request = _build_request()

        with self.assertRaises(HTTPException) as ctx:
            await api_bookrag_answer_get(request, question="q", vector_store_name="vs")

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual((ctx.exception.headers or {}).get("WWW-Authenticate"), "Bearer")

    async def test_answer_get_never_falls_back_to_demo_data(self) -> None:
        request = _build_request(headers={"x-api-key": "secret-token"})

        with patch.dict(os.environ, {"EVSUI_API_TOKEN": "secret-token"}, clear=False):
            with self.assertRaises(HTTPException) as ctx:
                await api_bookrag_answer_get(request)

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "question and vector_store_name are required")

    async def test_answer_get_uses_live_model_when_query_params_are_present(self) -> None:
        request = _build_request(headers={"x-api-key": "secret-token", "x-request-id": "req-456"})
        evidence = {"vector_store_name": "demo_vs", "packages": [{"rank": 1}], "package_count": 1}
        live_answer = {"mode": "live", "model": "vectorstore.prepare_response", "grounded": True, "text": "live reply", "citations": []}

        with patch.dict(os.environ, {"EVSUI_API_TOKEN": "secret-token"}, clear=False):
            with patch("app.routers.api._retrieve_bookrag_evidence_or_raise", return_value=("what is new", "demo_vs", evidence, object())), patch(
                "app.routers.api._build_bookrag_live_answer_or_raise",
                return_value=live_answer,
            ):
                payload = await api_bookrag_answer_get(
                    request,
                    question="what is new",
                    vector_store_name="demo_vs",
                    schema_name="demo_schema",
                )

        self.assertEqual(payload["meta"]["request_id"], "req-456")
        self.assertEqual(payload["meta"]["auth_mode"], "api_key")
        self.assertEqual(payload["answer"]["mode"], "live")
        self.assertEqual(payload["answer"]["text"], "live reply")
        self.assertEqual(payload["assistant_message"], "live reply")


class BookRAGApiLiveAnswerTests(unittest.TestCase):
    def test_build_live_answer_calls_prepare_response(self) -> None:
        llm_input = {
            "question": "決算の要点は？",
            "instructions": ["与えられた evidence のみを根拠に回答すること。"],
            "evidence": [
                {
                    "rank": 1,
                    "title": "総括",
                    "pages": [2, 2],
                    "node_id": "node-1",
                    "source_element_id": "block-1",
                    "content": "増収増益だが成長は鈍化。",
                    "path": "決算短信 > 総括",
                }
            ],
        }

        class _VectorStore:
            def __init__(self, name):
                self.name = name

            def prepare_response(self, similarity_results=None, question=None, prompt=None):
                self.last_similarity_results = similarity_results
                self.last_question = question
                self.last_prompt = prompt
                return {"text": "real grounded answer"}

        with patch("app.routers.api.VectorStore", _VectorStore):
            answer = _build_bookrag_live_answer_or_raise(
                question="決算の要点は？",
                vector_store_name="demo_vs",
                llm_input=llm_input,
                similarity_result=object(),
            )

        self.assertEqual(answer["mode"], "live")
        self.assertEqual(answer["model"], "vectorstore.prepare_response")
        self.assertEqual(answer["text"], "real grounded answer")
        self.assertEqual(answer["citations"][0]["node_id"], "node-1")

    def test_retrieve_delegates_to_adaptive_retrieval(self) -> None:
        class _VectorStore:
            def __init__(self, _name):
                pass

        evidence = {
            "retrieval_scope": {
                "view_name": "MUBKWM_bk_retrieval_v",
                "allowed_doc_ids": ["latest-doc"],
            },
            "packages": [
                {"rank": 1, "match": {"doc_id": "latest-doc", "node_id": "node-latest"}},
            ],
        }
        with patch("app.routers.api.VectorStore", _VectorStore), patch(
            "app.routers.api.execute_sql", object()
        ), patch(
            "app.routers.api.retrieve_adaptive_bookrag_evidence",
            return_value=(evidence, "candidate-result"),
        ) as adaptive_mock:
            _, _, result, similarity_result = _retrieve_bookrag_evidence_or_raise(
                question="最新の債券見通しは？",
                vector_store_name="MUBKWM",
                schema_name="usecases_japan",
                top_k=5,
            )

        self.assertEqual(similarity_result, "candidate-result")
        self.assertEqual(result, evidence)
        adaptive_mock.assert_called_once()
        self.assertEqual(
            adaptive_mock.call_args.kwargs["question"],
            "最新の債券見通しは？",
        )

    def test_answer_retrieval_locks_similarity_to_final_evidence(self) -> None:
        class _VectorStore:
            def __init__(self, _name):
                pass

        packages = [
            {
                "rank": 1,
                "retrieval_track": "latest_related",
                "match": {"doc_id": "spot-doc", "node_id": "spot-node"},
            },
            {
                "rank": 2,
                "retrieval_track": "periodic_background",
                "match": {"doc_id": "monthly-doc", "node_id": "monthly-node"},
            },
        ]
        evidence = {
            "retrieval_scope": {
                "allowed_doc_ids": ["spot-doc", "monthly-doc"],
            },
            "packages": packages,
        }
        with patch("app.routers.api.VectorStore", _VectorStore), patch(
            "app.routers.api.execute_sql", object()
        ), patch(
            "app.routers.api.retrieve_adaptive_bookrag_evidence",
            return_value=(evidence, "candidate-result"),
        ), patch(
            "app.routers.api.lock_similarity_result_to_evidence",
            return_value="locked-result",
        ) as lock_mock:
            _, _, result, similarity_result = _retrieve_bookrag_evidence_or_raise(
                question="債券の資産別見通しを要約してください",
                vector_store_name="MUBKWM",
                schema_name="usecases_japan",
                lock_final=True,
            )

        self.assertEqual(similarity_result, "locked-result")
        self.assertEqual(result["packages"], packages)
        self.assertEqual(lock_mock.call_args.kwargs["packages"], packages)
        self.assertEqual(
            [package["retrieval_track"] for package in result["packages"]],
            ["latest_related", "periodic_background"],
        )

    def test_retrieve_rejects_an_empty_governed_scope(self) -> None:
        class _VectorStore:
            def __init__(self, _name):
                pass

        with patch("app.routers.api.VectorStore", _VectorStore), patch(
            "app.routers.api.execute_sql", object()
        ), patch(
            "app.routers.api.retrieve_adaptive_bookrag_evidence",
            return_value=(
                {"retrieval_scope": {"allowed_doc_ids": []}, "packages": []},
                None,
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                _retrieve_bookrag_evidence_or_raise(
                    question="20260609の債券見通しは？",
                    vector_store_name="MUBKWM",
                    schema_name="usecases_japan",
                    top_k=5,
                )

        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
