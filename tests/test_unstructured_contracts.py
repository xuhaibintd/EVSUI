from __future__ import annotations

import unittest

from app.integrations.unstructured.contracts import validate_workflow_nodes


class UnstructuredWorkflowContractTests(unittest.TestCase):
    def test_explicit_vlm_rejects_redundant_enrichment(self) -> None:
        nodes = [
            {
                "name": "Partitioner",
                "type": "partition",
                "subtype": "vlm",
                "settings": {"strategy": "vlm"},
            },
            {
                "name": "Image Description",
                "type": "prompter",
                "subtype": "openai_image_description",
                "settings": {},
            },
        ]

        with self.assertRaisesRegex(ValueError, "already includes"):
            validate_workflow_nodes(nodes)

    def test_auto_vlm_allows_separate_enrichment_nodes(self) -> None:
        nodes = [
            {
                "name": "Partitioner",
                "type": "partition",
                "subtype": "vlm",
                "settings": {"strategy": "auto"},
            },
            {
                "name": "Image Description",
                "type": "prompter",
                "subtype": "openai_image_description",
                "settings": {},
            },
        ]

        validate_workflow_nodes(nodes)


if __name__ == "__main__":
    unittest.main()
