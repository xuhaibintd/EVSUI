from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.services import unstructured_json_inspector as inspector


class JsonInspectorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        patcher = mock.patch.object(inspector, "INSPECTOR_SOURCES", {"test": ("Fixture", self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def inspect(self, payload):
        (self.root / "fixture.json").write_text(json.dumps(payload), encoding="utf-8")
        context = inspector.build_unstructured_json_inspector_context("test:fixture.json")
        self.assertEqual(context["error"], "")
        return context["summary"]

    def test_supported_envelopes_and_hierarchical_metadata(self):
        elements = [{"type": "Title", "text": "title", "metadata": {"page_number": 1}},
                    {"type": "CompositeElement", "text": "body", "metadata": {
                        "page_number": "2", "parent_id": "parent", "category_depth": "1",
                        "text_as_html": "<b>body</b>", "entities": {"name": "fixture"}}},
                    {"type": "Table", "metadata": {"category_depth": "invalid", "page_number": "invalid"}},
                    {"type": "Image", "metadata": []}, "ignored-non-object"]
        for envelope in (elements, {"raw_elements": elements}, {"elements": elements},
                         {"output": elements}, {"data": elements}, {"custom": elements}):
            with self.subTest(envelope=type(envelope).__name__):
                summary = self.inspect(envelope)
                self.assertEqual(summary["element_count"], 4)
                self.assertEqual(summary["structure_verdict"], "Hierarchical")
                self.assertEqual(summary["page_range_label"], "1-2 (2 pages)")
                self.assertEqual(summary["parent_link_ratio_label"], "25%")
                for flag in ("has_parent_id", "has_category_depth", "has_text_as_html", "has_entities", "has_composite_elements"):
                    self.assertTrue(summary[flag])

    def test_flat_empty_and_scalar_payloads_and_long_preview(self):
        for payload, expected in (([{"type": "Title", "metadata": {"page_number": 1}}], "Typed flat elements"),
                                  ([{"text": "one\ntwo"}], "Flat elements"),
                                  ({"a": [], "b": []}, "No element list"), (None, "No element list")):
            with self.subTest(expected=expected):
                self.assertEqual(self.inspect(payload)["structure_verdict"], expected)
        summary = self.inspect([{"text": "文" * 13000}])
        sample = summary["sample_elements"][0]
        self.assertTrue(sample["text_preview"].endswith("..."))
        self.assertTrue(sample["json_preview"].endswith("\n..."))
        self.assertEqual(json.loads(sample["json_compact"])["text"], "文" * 13000)

    def test_invalid_missing_traversal_and_oversize_files_return_errors(self):
        (self.root / "invalid.json").write_text("{", encoding="utf-8")
        (self.root / "plain.txt").write_text("[]", encoding="utf-8")
        for selection in ("test:invalid.json", "test:missing.json", "test:plain.txt",
                          "test:../outside.json", "unknown:file.json", "", "test:"):
            with self.subTest(selection=selection):
                result = inspector.build_unstructured_json_inspector_context(selection)
                self.assertIsNone(result["summary"])
                self.assertEqual(bool(result["error"]), bool(selection))
        (self.root / "large.json").write_text("[{}]", encoding="utf-8")
        with mock.patch.object(inspector, "MAX_INSPECT_JSON_BYTES", 1):
            result = inspector.build_unstructured_json_inspector_context("test:large.json")
        self.assertIn("too large", result["error"])

    def test_file_listing_uses_known_roots_json_only_and_file_limit(self):
        (self.root / "nested").mkdir()
        for name in ("one.json", "nested/two.json", "ignored.txt"):
            (self.root / name).write_text("[]", encoding="utf-8")
        values = {item["value"] for item in inspector.list_unstructured_json_files()}
        self.assertEqual(values, {"test:one.json", "test:nested/two.json"})
        with mock.patch.object(inspector, "MAX_LISTED_FILES_PER_SOURCE", 1):
            self.assertEqual(len(inspector.list_unstructured_json_files()), 1)
