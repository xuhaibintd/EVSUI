from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services.bookrag_adaptive_retrieval import (
    build_exact_node_filter,
    discover_facets_from_candidates,
    partition_document_scope,
    rerank_packages,
    retrieve_adaptive_bookrag_evidence,
)
from app.services.bookrag_query_planner import plan_bookrag_query
from app.services.bookrag_retrieval_policy import load_bookrag_retrieval_policy


def _package(
    doc_id: str,
    node_id: str,
    *,
    publication_date: str,
    content: str,
    series: str = "spot",
    role: str = "update",
) -> dict:
    return {
        "rank": 1,
        "match": {
            "doc_id": doc_id,
            "node_id": node_id,
            "content": content,
        },
        "document": {
            "doc_id": doc_id,
            "filename": f"{doc_id}.pdf",
            "publication_date": publication_date,
            "document_series": series,
            "document_role": role,
            "metadata_status": "confirmed",
        },
    }


class BookRAGAdaptivePrimitiveTests(unittest.TestCase):
    def test_periodic_partition_keeps_latest_per_configured_series_current(self) -> None:
        policy = load_bookrag_retrieval_policy()
        documents = [
            {"doc_id": "spot", "document_series": "spot", "publication_date": "2026-06-09"},
            {"doc_id": "monthly-new", "document_series": "monthly", "publication_date": "2026-05-27"},
            {"doc_id": "monthly-old", "document_series": "monthly", "publication_date": "2026-04-23"},
            {"doc_id": "main-new", "document_series": "main", "publication_date": "2026-05-25"},
            {"doc_id": "main-old", "document_series": "main", "publication_date": "2026-02-25"},
        ]

        current, background = partition_document_scope(documents, policy)

        self.assertEqual(
            {row["doc_id"] for row in current},
            {"spot", "monthly-new", "main-new"},
        )
        self.assertEqual(
            {row["doc_id"] for row in background},
            {"monthly-old", "main-old"},
        )

    def test_freshness_changes_order_when_semantic_rank_is_equal(self) -> None:
        policy = load_bookrag_retrieval_policy()
        older = _package("old", "n-old", publication_date="2026-01-01", content="金利")
        newer = _package("new", "n-new", publication_date="2026-06-01", content="金利")
        older["_semantic_rank"] = 1
        newer["_semantic_rank"] = 1

        ranked = rerank_packages([older, newer], policy, apply_freshness=True)

        self.assertEqual(ranked[0]["match"]["doc_id"], "new")
        self.assertGreater(ranked[0]["adaptive_score"], ranked[1]["adaptive_score"])

    def test_exact_node_filter_uses_the_canonical_evidence_keys(self) -> None:
        packages = [
            _package("doc-1", "node-1", publication_date="2026-06-01", content="a"),
            _package("doc-2", "node-2", publication_date="2026-06-02", content="b"),
        ]

        filter_sql = build_exact_node_filter(packages)

        self.assertIn("(doc_id='doc-1' AND node_id='node-1')", filter_sql)
        self.assertIn("(doc_id='doc-2' AND node_id='node-2')", filter_sql)

    def test_document_native_section_titles_can_expand_an_open_query(self) -> None:
        policy = load_bookrag_retrieval_policy()
        plan = plan_bookrag_query(
            "株式の資産別見通しをそれぞれ要約してください。",
            facet_discovery_markers=policy.planning.facet_discovery_markers,
        )
        packages = [
            {
                "match": {
                    "doc_id": "doc-1",
                    "node_id": "node-1",
                    "title": "日本株式",
                    "path": "資産別見通し > 日本株式",
                }
            },
            {
                "match": {
                    "doc_id": "doc-1",
                    "node_id": "node-2",
                    "title": "米国株式",
                    "path": "資産別見通し > 米国株式",
                }
            },
        ]

        discovered = discover_facets_from_candidates(plan, packages, maximum=8)

        queries = [facet.query for facet in discovered]
        self.assertTrue(any("日本株式" in query for query in queries))
        self.assertTrue(any("米国株式" in query for query in queries))


class BookRAGAdaptiveRetrievalFlowTests(unittest.TestCase):
    def test_single_result_can_fall_back_to_background_when_current_has_no_match(self) -> None:
        policy = load_bookrag_retrieval_policy()
        scope = {
            "view_name": "demo_retrieval_v",
            "allowed_doc_ids": ["spot", "monthly-new", "monthly-old"],
            "primary_documents": [
                {
                    "doc_id": "spot",
                    "document_series": "spot",
                    "publication_date": "2026-06-09",
                },
                {
                    "doc_id": "monthly-new",
                    "document_series": "monthly",
                    "publication_date": "2026-05-23",
                },
                {
                    "doc_id": "monthly-old",
                    "document_series": "monthly",
                    "publication_date": "2026-04-23",
                },
            ],
        }
        background_evidence = {
            "packages": [
                _package(
                    "monthly-old",
                    "monthly-node",
                    publication_date="2026-04-23",
                    content="過去の定期レポートにある背景説明。",
                    series="monthly",
                    role="comprehensive",
                )
            ]
        }

        class _VectorStore:
            def similarity_search(self, **kwargs):
                return kwargs["filter"]

        with patch(
            "app.services.bookrag_adaptive_retrieval.fetch_governed_document_scope",
            return_value=scope,
        ), patch(
            "app.services.bookrag_adaptive_retrieval.retrieve_bookrag_evidence",
            side_effect=[{"packages": []}, background_evidence],
        ):
            evidence, _ = retrieve_adaptive_bookrag_evidence(
                vector_store=_VectorStore(),
                vector_store_name="demo",
                question="金利の背景を説明してください。",
                schema_name="demo",
                execute_sql_fn=object(),
                top_k=1,
                policy=policy,
            )

        self.assertEqual(len(evidence["packages"]), 1)
        self.assertEqual(
            evidence["packages"][0]["retrieval_track"],
            "periodic_background",
        )

    def test_background_is_queried_only_when_current_evidence_is_insufficient(self) -> None:
        policy = load_bookrag_retrieval_policy()
        scope = {
            "view_name": "demo_retrieval_v",
            "allowed_doc_ids": ["spot", "monthly-new", "monthly-old"],
            "primary_documents": [
                {"doc_id": "spot", "document_series": "spot", "publication_date": "2026-06-09"},
                {"doc_id": "monthly-new", "document_series": "monthly", "publication_date": "2026-05-27"},
                {"doc_id": "monthly-old", "document_series": "monthly", "publication_date": "2026-04-23"},
            ],
        }
        current_evidence = {
            "packages": [
                _package(
                    "spot",
                    "spot-node",
                    publication_date="2026-06-09",
                    content="金利への影響。",
                )
            ]
        }
        background_evidence = {
            "packages": [
                _package(
                    "monthly-old",
                    "monthly-node",
                    publication_date="2026-04-23",
                    content="金利が資産価格へ波及する背景を詳細に説明する。" * 30,
                    series="monthly",
                    role="comprehensive",
                )
            ]
        }

        class _VectorStore:
            def __init__(self):
                self.calls = []

            def similarity_search(self, **kwargs):
                self.calls.append(kwargs)
                return f"result-{len(self.calls)}"

        vector_store = _VectorStore()
        with patch(
            "app.services.bookrag_adaptive_retrieval.fetch_governed_document_scope",
            return_value=scope,
        ), patch(
            "app.services.bookrag_adaptive_retrieval.retrieve_bookrag_evidence",
            side_effect=[current_evidence, background_evidence],
        ):
            evidence, _ = retrieve_adaptive_bookrag_evidence(
                vector_store=vector_store,
                vector_store_name="demo",
                question="金利の影響と背景を説明してください。",
                schema_name="demo",
                execute_sql_fn=object(),
                top_k=5,
                policy=policy,
            )

        self.assertEqual(len(vector_store.calls), 2)
        self.assertNotIn("monthly-old", vector_store.calls[0]["filter"])
        self.assertIn("monthly-old", vector_store.calls[1]["filter"])
        self.assertTrue(evidence["coverage"]["background_used"])
        self.assertEqual(
            {package["retrieval_track"] for package in evidence["packages"]},
            {"latest_related", "periodic_background"},
        )

    def test_sufficient_current_evidence_avoids_background_query(self) -> None:
        policy = load_bookrag_retrieval_policy()
        scope = {
            "view_name": "demo_retrieval_v",
            "allowed_doc_ids": ["spot-1", "spot-2", "monthly-old"],
            "primary_documents": [
                {"doc_id": "spot-1", "document_series": "spot", "publication_date": "2026-06-09"},
                {"doc_id": "spot-2", "document_series": "topics", "publication_date": "2026-06-08"},
                {"doc_id": "monthly-old", "document_series": "monthly", "publication_date": "2026-04-23"},
            ],
        }
        long_text = "金利見通しと市場への影響を、政策、需給、物価の関係から説明する。" * 30
        current_evidence = {
            "packages": [
                _package("spot-1", "n1", publication_date="2026-06-09", content=long_text),
                _package("spot-2", "n2", publication_date="2026-06-08", content=long_text, series="topics"),
            ]
        }

        class _VectorStore:
            def __init__(self):
                self.calls = []

            def similarity_search(self, **kwargs):
                self.calls.append(kwargs)
                return "current-result"

        vector_store = _VectorStore()
        with patch(
            "app.services.bookrag_adaptive_retrieval.fetch_governed_document_scope",
            return_value=scope,
        ), patch(
            "app.services.bookrag_adaptive_retrieval.retrieve_bookrag_evidence",
            return_value=current_evidence,
        ):
            evidence, _ = retrieve_adaptive_bookrag_evidence(
                vector_store=vector_store,
                vector_store_name="demo",
                question="金利の影響と背景を説明してください。",
                schema_name="demo",
                execute_sql_fn=object(),
                top_k=5,
                policy=policy,
            )

        self.assertEqual(len(vector_store.calls), 1)
        self.assertFalse(evidence["coverage"]["background_used"])
        self.assertTrue(evidence["coverage"]["sufficient"])


if __name__ == "__main__":
    unittest.main()
