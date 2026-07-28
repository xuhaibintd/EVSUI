from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.services.bookrag_retrieval_policy import load_bookrag_retrieval_policy


class BookRAGRetrievalPolicyTests(unittest.TestCase):
    def test_default_policy_is_bounded_and_configuration_driven(self) -> None:
        policy = load_bookrag_retrieval_policy()

        self.assertLessEqual(policy.candidate_budget.per_track, 20)
        self.assertGreaterEqual(policy.candidate_budget.maximum_final, 1)
        self.assertIn("confirmed", policy.governance.allowed_metadata_statuses)
        self.assertTrue(policy.background.eligible_series)

    def test_custom_document_series_requires_no_python_change(self) -> None:
        payload = {
            "policy_version": 2,
            "background": {
                "eligible_series": ["weekly-research"],
                "eligible_roles": ["deep-analysis"]
            },
            "governance": {"allowed_metadata_statuses": ["confirmed"]}
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            policy = load_bookrag_retrieval_policy(path)

        self.assertEqual(policy.policy_version, 2)
        self.assertEqual(policy.background.eligible_series, ("weekly-research",))
        self.assertEqual(policy.background.eligible_roles, ("deep-analysis",))


if __name__ == "__main__":
    unittest.main()
