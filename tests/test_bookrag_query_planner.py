from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.services.bookrag_query_planner import (
    parse_temporal_scope,
    plan_bookrag_query,
)
from app.services.bookrag_retrieval_policy import load_bookrag_retrieval_policy


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "bookrag_evaluation_questions.json"


class BookRAGTemporalScopeTests(unittest.TestCase):
    def test_exact_dates_are_structured(self) -> None:
        scope = parse_temporal_scope("20260609と2026-06-08の見通し")

        self.assertEqual(scope.kind, "exact_dates")
        self.assertEqual(
            [value.isoformat() for value in scope.exact_dates],
            ["2026-06-08", "2026-06-09"],
        )

    def test_month_and_quarter_become_half_open_ranges(self) -> None:
        month = parse_temporal_scope("2026年6月時点の見通し")
        quarter = parse_temporal_scope("2026年第2四半期の見通し")

        self.assertEqual(month.start_date.isoformat(), "2026-06-01")
        self.assertEqual(month.end_date_exclusive.isoformat(), "2026-07-01")
        self.assertEqual(quarter.start_date.isoformat(), "2026-04-01")
        self.assertEqual(quarter.end_date_exclusive.isoformat(), "2026-07-01")

    def test_latest_quarter_is_relative_until_document_scope_resolution(self) -> None:
        scope = parse_temporal_scope("最新四半期の金利見通し")

        self.assertEqual(scope.kind, "latest_quarter")
        self.assertIsNone(scope.start_date)


class BookRAGOpenQueryPlannerTests(unittest.TestCase):
    def test_all_regression_questions_produce_valid_generic_plans(self) -> None:
        questions = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        policy = load_bookrag_retrieval_policy()

        self.assertEqual(len(questions), 22)
        for question in questions:
            with self.subTest(question=question):
                plan = plan_bookrag_query(
                    question,
                    explanation_markers=policy.background.explanation_markers,
                )
                self.assertEqual(plan.question, question)
                self.assertTrue(plan.facets)
                self.assertTrue(all(facet.query for facet in plan.facets))
                self.assertEqual(
                    plan.temporal_scope.kind,
                    "latest_available",
                )

    def test_comparison_terms_are_discovered_from_parenthetical_slashes(self) -> None:
        plan = plan_bookrag_query("金融政策（FRB/ECB/日銀）の見立てをまとめてください。")

        self.assertEqual(plan.comparison_terms, ("FRB", "ECB", "日銀"))
        self.assertGreaterEqual(len(plan.facets), 4)

    def test_output_sentence_hint_is_not_tied_to_a_specific_question(self) -> None:
        plan = plan_bookrag_query("各項目を2～3文で説明してください。")

        self.assertEqual(plan.output_hints["sentences_per_item"], [2, 3])


if __name__ == "__main__":
    unittest.main()
