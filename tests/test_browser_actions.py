"""Opt-in real-browser action regression suite; see docs/testing.md."""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock
from pathlib import Path
from urllib.parse import urlsplit

from tests.e2e_support import BrowserApplication


@unittest.skipUnless(os.getenv("EVSUI_BROWSER_TESTS") == "1", "Set EVSUI_BROWSER_TESTS=1 for browser actions")
class BrowserActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        options = {"headless": True}
        channel = os.getenv("EVSUI_BROWSER_CHANNEL")
        if channel:
            options["channel"] = channel
        cls.browser = cls.playwright.chromium.launch(**options)
        cls.actions = []
        cls.output = Path(__file__).resolve().parents[1] / "test-results"
        cls.output.mkdir(exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        (cls.output / "browser-actions.json").write_text(json.dumps(cls.actions, indent=2), encoding="utf-8")
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        from playwright.sync_api import expect
        self.expect = expect
        self.fixture = BrowserApplication().__enter__()
        self.addCleanup(self.fixture.__exit__, None, None, None)
        self.context = self.browser.new_context(viewport={"width": 1600, "height": 1000}, accept_downloads=True)
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("response", self.record_response)

    def record_response(self, response):
        if response.url.startswith(self.fixture.base_url):
            path = urlsplit(response.url).path
            if not path.startswith("/static"):
                self.actions.append({"test": self._testMethodName, "method": response.request.method,
                                     "path": path, "status": response.status})

    def tearDown(self):
        self.assertEqual(self.errors, [], "Unhandled browser JavaScript errors")

    def login(self, user="e2e_admin"):
        self.page.goto(self.fixture.base_url + "/login")
        self.page.locator('[name="username"]').fill(user)
        self.page.locator('[name="password"]').fill("browser-password")
        self.page.get_by_role("button", name="Login", exact=True).click()
        self.expect(self.page.locator(".menu-layout")).to_be_visible()
        self.page.wait_for_function("() => Boolean(window.htmx && window.EVSUIApp)")

    def connect(self):
        self.page.get_by_role("button", name="Connect", exact=True).click()
        self.expect(self.page.locator("[data-step1-connected]")).to_have_attribute("data-step1-connected", "true")

    def governance(self):
        self.login()
        self.connect()
        self.page.get_by_role("button", name="BookRAG Governance", exact=True).click()

    def load_governance(self, panel_id):
        panel = self.page.locator(panel_id)
        with self.page.expect_response(lambda response: "/ui/admin/document-" in response.url):
            panel.get_by_role("button", name="Refresh Vector Stores", exact=True).click()
        self.expect(panel.locator('select[name="vector_store_name"] option[value="e2e_store"]')).to_have_count(1)
        panel.locator('select[name="vector_store_name"]').select_option("e2e_store")
        with self.page.expect_response(lambda response: "/ui/admin/document-" in response.url):
            panel.get_by_role("button", name="Load", exact=True).click()
        return panel

    def test_empty_governance_select_refreshes_both_lists_without_native_validation(self):
        self.governance()
        for panel_id in ("#document-metadata-admin", "#document-relation-admin"):
            with self.subTest(panel=panel_id):
                panel = self.page.locator(panel_id)
                self.assertEqual(panel.locator('select[name="vector_store_name"]').input_value(), "")
                before = self.fixture.calls.count("list")
                with self.page.expect_response(lambda response: "refresh=true" in response.url):
                    panel.get_by_role("button", name="Refresh Vector Stores").click()
                self.expect(panel.locator('option[value="e2e_store"]')).to_have_count(1)
                self.assertGreater(self.fixture.calls.count("list"), before)
                # Loading is still required to have a selection; only list refresh bypasses it.
                self.assertEqual(panel.locator('select[name="vector_store_name"]').input_value(), "")
        self.page.locator("#bookrag-admin-panel").screenshot(path=str(self.output / "governance-refresh.png"))

    def test_login_failure_logout_and_connection_navigation_lifecycle(self):
        self.page.goto(self.fixture.base_url + "/login")
        self.page.locator('[name="username"]').fill("e2e_admin")
        self.page.locator('[name="password"]').fill("wrong-password")
        self.page.get_by_role("button", name="Login", exact=True).click()
        self.expect(self.page.locator(".login-btn")).to_be_visible()
        self.login()
        self.expect(self.page.get_by_role("button", name="Vector Store Creation", exact=True)).to_be_disabled()
        self.connect()
        for name in ("Vector Store Creation", "Vector Store Retrieval", "BookRAG Governance", "Connect & Manage"):
            self.page.get_by_role("button", name=name, exact=True).click()
        self.page.get_by_role("button", name="Disconnect", exact=True).click()
        self.expect(self.page.locator("[data-step1-connected]")).to_have_attribute("data-step1-connected", "false")
        self.expect(self.page.get_by_role("button", name="Vector Store Creation", exact=True)).to_be_disabled()
        self.page.get_by_role("button", name="Log Out", exact=True).click()
        self.expect(self.page.locator(".login-btn")).to_be_visible()
        self.page.goto(self.fixture.base_url + "/admin/users")
        self.assertNotIn("System Configuration</h1>", self.page.content())

    def test_metadata_load_edit_export_import_and_autofill(self):
        self.governance()
        panel = self.load_governance("#document-metadata-admin")
        self.expect(panel.get_by_text("manual.pdf", exact=True)).to_be_visible()
        panel.locator("summary").first.click()
        form = panel.locator(".document-metadata-edit-form").first
        form.locator('[name="publication_date"]').fill("2026-08-01")
        form.locator('[name="metadata_status"]').select_option("confirmed")
        form.get_by_role("button", name="Save", exact=True).click()
        self.expect(panel.get_by_text("Document Metadata Saved", exact=True)).to_be_visible()
        self.assertEqual(self.fixture.documents[0]["publication_date"], "2026-08-01")
        with self.page.expect_download() as downloaded:
            panel.get_by_role("link", name="Export CSV", exact=True).click()
        self.assertIn("manual.pdf", Path(downloaded.value.path()).read_text(encoding="utf-8-sig"))
        panel.locator('[name="metadata_csv"]').set_input_files({"name": "metadata.csv", "mimeType": "text/csv",
            "buffer": b"doc_id,publication_date,metadata_status\ndoc-1,2026-08-02,confirmed\n"})
        panel.get_by_role("button", name="Import CSV", exact=True).click()
        self.expect(panel.get_by_text("Metadata CSV Imported", exact=True)).to_be_visible()
        self.assertEqual(self.fixture.documents[0]["publication_date"], "2026-08-02")
        panel.get_by_role("button", name="Auto-fill Metadata", exact=True).click()
        self.expect(panel.get_by_text("Metadata Auto-fill Complete", exact=True)).to_be_visible()

    def test_json_inspector_refresh_discovers_new_files_and_opens_real_payload(self):
        self.governance()
        self.page.get_by_role("tab", name="JSON Inspector", exact=True).click()
        self.expect(self.page.locator("#json-inspector-file option")).to_have_count(1)
        directory = self.fixture.uploads / "inspector" / "raw_stage"
        directory.mkdir(parents=True)
        payload = [{"type": "Title", "element_id": "title-1", "text": "Browser inspected title",
                    "metadata": {"page_number": 1}},
                   {"type": "NarrativeText", "element_id": "paragraph-1",
                    "text": '<img src=x onerror="window.inspectorUnsafe=true">',
                    "metadata": {"page_number": 2, "parent_id": "title-1", "category_depth": 1}}]
        (directory / "browser.json").write_text(json.dumps(payload), encoding="utf-8")
        picker = self.page.locator(".json-inspector-toolbar")
        picker.get_by_role("button", name="Refresh", exact=True).click()
        self.expect(self.page.locator('#json-inspector-file option[value="raw_stage:browser.json"]')).to_have_count(1)
        self.page.locator("#json-inspector-file").select_option("raw_stage:browser.json")
        picker.get_by_role("button", name="Open", exact=True).click()
        result = self.page.locator("#json-inspector-result")
        self.expect(result.locator("[data-json-viewer-item]")).to_have_count(2)
        self.expect(result).to_contain_text("Hierarchical")
        result.locator('[data-json-viewer-tab="text"]').click()
        self.expect(result.locator("[data-json-viewer-code]")).to_have_text("Browser inspected title")
        result.locator('[data-json-viewer-item][data-index="2"]').click()
        self.expect(result.locator("[data-json-viewer-code]")).to_have_text(payload[1]["text"])
        self.assertFalse(self.page.evaluate("() => Boolean(window.inspectorUnsafe)"))
        result.locator("[data-json-viewer-filter]").fill("no matching text")
        self.expect(result.locator("[data-json-viewer-code]")).to_have_text("")
        result.locator("[data-json-viewer-filter]").fill("")
        self.expect(result.locator('[data-json-viewer-item].is-selected')).to_have_count(1)
        (directory / "invalid.json").write_text("{", encoding="utf-8")
        picker.get_by_role("button", name="Refresh", exact=True).click()
        self.expect(self.page.locator('#json-inspector-file option[value="raw_stage:invalid.json"]')).to_have_count(1)
        self.page.locator("#json-inspector-file").select_option("raw_stage:invalid.json")
        picker.get_by_role("button", name="Open", exact=True).click()
        self.expect(result).to_contain_text("Inspection Failed")

    def test_relationship_initialize_add_edit_export_delete(self):
        self.governance()
        panel = self.load_governance("#document-relation-admin")
        panel.get_by_role("button", name="Initialize bdrel", exact=True).click()
        self.expect(panel.get_by_text("bdrel Ready", exact=True)).to_be_visible()
        form = panel.locator(".document-relation-admin-form")
        form.locator('[name="from_doc_id"]').select_option("doc-1")
        form.locator('[name="to_doc_id"]').select_option("doc-2")
        form.locator('[name="relation_type"]').select_option("related_to")
        form.locator('[name="relation_description"]').fill("Browser-created relationship")
        form.get_by_role("button", name="Save", exact=True).click()
        self.expect(panel.get_by_text("Relationship Saved", exact=True)).to_be_visible()
        panel.locator("summary").click()
        edit = panel.locator("details form")
        edit.locator('[name="relation_description"]').fill("Browser-updated relationship")
        edit.get_by_role("button", name="Update", exact=True).click()
        self.expect(panel.get_by_text("Browser-updated relationship", exact=True)).to_be_visible()
        with self.page.expect_download() as download:
            panel.get_by_role("link", name="Export CSV", exact=True).click()
        self.assertIn("related_to", Path(download.value.path()).read_text(encoding="utf-8-sig"))
        self.page.once("dialog", lambda dialog: dialog.accept())
        panel.get_by_role("button", name="Delete", exact=True).click()
        self.expect(panel.get_by_text("Relationships (0)", exact=True)).to_be_visible()

    def test_system_configuration_profile_create_edit_delete_with_dialog_cancel(self):
        self.login()
        self.page.get_by_role("link", name="System Configuration", exact=True).click()
        self.page.get_by_role("link", name="Add", exact=True).click()
        form = self.page.locator(".system-connection-form")
        for name, value in {"connection_name": "Secondary browser", "host": "secondary.invalid",
                            "username": "fixture", "password": "secondary-password", "pat_token": "secondary-pat",
                            "ues_url": "https://secondary.invalid/open-analytics"}.items():
            form.locator(f'[name="{name}"]').fill(value)
        form.locator('[name="pem_file"]').set_input_files({"name": "secondary.pem", "mimeType": "text/plain", "buffer": self.fixture.pem})
        form.get_by_role("button", name="Create connection", exact=True).click()
        self.expect(self.page.get_by_role("heading", name="Edit Secondary browser", exact=True)).to_be_visible()
        form.locator('[name="connection_name"]').fill("Secondary renamed")
        form.get_by_role("button", name="Save changes", exact=True).click()
        self.expect(self.page.get_by_role("heading", name="Edit Secondary renamed", exact=True)).to_be_visible()
        self.assertEqual(len(self.fixture.store.list_connection_profiles()), 2)
        self.page.once("dialog", lambda dialog: dialog.dismiss())
        form.get_by_role("button", name="Delete", exact=True).click()
        self.assertEqual(len(self.fixture.store.list_connection_profiles()), 2)
        self.page.once("dialog", lambda dialog: dialog.accept())
        form.get_by_role("button", name="Delete", exact=True).click()
        self.expect(self.page.get_by_role("heading", name="Edit Secondary renamed", exact=True)).to_have_count(0)
        self.assertEqual(len(self.fixture.store.list_connection_profiles()), 1)

    def test_management_health_list_select_and_destroy_cancel_confirm(self):
        self.login()
        self.connect()
        self.page.get_by_role("button", name="Vector Store Health check", exact=True).click()
        self.expect(self.page.locator(".monitor-status-health")).to_contain_text("ok")
        self.assertIn("health", self.fixture.calls)
        self.page.get_by_role("button", name="Get Vector Store List", exact=True).click()
        row = self.page.locator('tr[data-vs-name="e2e_store"]')
        self.expect(row).to_be_visible()
        row.click()
        self.expect(self.page.locator("[data-destroy-selected-name]")).to_have_text("e2e_store")
        self.page.locator("[data-destroy-btn]").click()
        dialog = self.page.get_by_role("dialog", name="Delete Vector Store", exact=True)
        self.expect(dialog).to_be_visible()
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        self.assertNotIn("destroy", self.fixture.calls)
        self.page.locator("[data-destroy-btn]").click()
        dialog.get_by_role("button", name="Delete", exact=True).click()
        self.expect(self.page.locator("[data-destroy-feedback]")).to_contain_text("Deleted 'e2e_store'")
        self.assertEqual(self.fixture.stores, [])

    def test_retrieval_list_ask_similarity_search_and_clear(self):
        self.login()
        self.connect()
        self.page.get_by_role("button", name="Vector Store Retrieval", exact=True).click()
        self.page.get_by_role("button", name="Run List", exact=True).click()
        self.expect(self.page.locator('#chat-selected-vs option[value="e2e_store"]')).to_have_count(1)
        self.page.locator("#chat-selected-vs").select_option("e2e_store")
        self.page.locator("#chat-message").fill("What is in the manual?")
        self.page.get_by_role("button", name="Send", exact=True).click()
        self.expect(self.page.locator("#chat-messages")).to_contain_text("Fixture grounded answer")
        self.page.locator("#validation-target").select_option("vectorstore.similarity_search")
        self.page.locator("#chat-message").fill("Find evidence")
        self.page.get_by_role("button", name="Send", exact=True).click()
        self.expect(self.page.locator("#chat-messages")).to_contain_text("Fixture retrieval evidence")
        self.assertIn("ask", self.fixture.calls)
        self.assertIn("search", self.fixture.calls)
        evidence = {"vector_store_name": "e2e_store", "package_count": 1,
                    "evidence_text": "API fixture evidence", "retrieval_scope": {"allowed_doc_ids": ["doc-1"]},
                    "packages": [{"rank": 1, "match": {"doc_id": "doc-1", "node_id": "node-1",
                                                          "content": "API fixture evidence"},
                                  "document": {"doc_id": "doc-1", "filename": "manual.pdf"}}]}
        with mock.patch("app.routers.api.retrieve_adaptive_bookrag_evidence", return_value=(evidence, "candidate")), \
                mock.patch("app.routers.api.lock_similarity_result_to_evidence", return_value="locked"):
            self.page.locator("#retrieval-mode-api").check()
            self.page.locator("#bookrag-api-top-k").fill("7")
            self.page.locator("#chat-message").fill("Find BookRAG API evidence")
            with self.page.expect_response(lambda response: response.url.endswith("/api/bookrag/retrieve")) as api_response:
                self.page.get_by_role("button", name="Send", exact=True).click()
            self.assertEqual(api_response.value.status, 200)
            self.assertEqual(api_response.value.request.post_data_json["top_k"], 7)
            self.expect(self.page.locator("#chat-messages")).to_contain_text("API fixture evidence")
            self.expect(self.page.get_by_role("button", name="Send", exact=True)).to_be_enabled()
            self.assertEqual(self.fixture.calls.count("ask"), 1, "API submit must not also run native HTMX submission")
        self.page.get_by_role("button", name="Clear", exact=True).click()
        self.expect(self.page.locator("#chat-messages")).not_to_contain_text("Fixture retrieval evidence")

    def test_unstructured_secrets_save_keep_clear_and_user_management(self):
        self.login()
        self.page.get_by_role("link", name="System Configuration", exact=True).click()
        self.page.locator('label[for="system-config-tab-unstructured"]').click()
        form = self.page.locator(".unstructured-connection-form")
        key = "browser-service-key-" + "x" * 80
        form.locator('[name="unstructured_api_key"]').fill(key)
        form.get_by_role("button", name="Save Unstructured IO", exact=True).click()
        self.expect(form.locator('[name="unstructured_api_key"]')).to_have_value("")
        self.assertEqual(self.fixture.store.get_unstructured_config()["api_key"], key)
        form.get_by_role("button", name="Save Unstructured IO", exact=True).click()
        self.assertEqual(self.fixture.store.get_unstructured_config()["api_key"], key)
        form.locator('[name="clear_unstructured_api_key"]').check()
        form.get_by_role("button", name="Save Unstructured IO", exact=True).click()
        self.assertEqual(self.fixture.store.get_unstructured_config()["api_key"], "")
        self.page.locator('label[for="system-config-tab-users"]').click()
        create = self.page.locator(".user-create-form")
        create.locator('[name="username"]').fill("browser_new_user")
        create.locator('[name="password"]').fill("new-user-password")
        create.get_by_role("button", name="Create user", exact=True).click()
        row = self.page.locator("tr").filter(has=self.page.get_by_text("browser_new_user", exact=True))
        self.expect(row).to_be_visible()
        row.locator('select[name="role"]').select_option("operator")
        row.get_by_role("button", name="Set role", exact=True).click()
        self.expect(row.locator('select[name="role"]')).to_have_value("operator")
        row.get_by_role("button", name="Disable", exact=True).click()
        self.expect(row.get_by_role("button", name="Enable", exact=True)).to_be_visible()
        row.get_by_role("button", name="Enable", exact=True).click()
        row.locator('.user-password-form input[name="password"]').fill("reset-browser-password")
        row.get_by_role("button", name="Reset", exact=True).click()
        self.expect(row.get_by_role("button", name="Disable", exact=True)).to_be_visible()

    def test_viewer_has_read_only_governance_and_no_creation_actions(self):
        self.login("e2e_viewer")
        self.expect(self.page.get_by_role("link", name="System Configuration", exact=True)).to_have_count(0)
        self.connect()
        self.expect(self.page.get_by_role("button", name="Vector Store Creation", exact=True)).to_have_count(0)
        self.page.get_by_role("button", name="BookRAG Governance", exact=True).click()
        panel = self.load_governance("#document-metadata-admin")
        self.expect(panel.locator("summary")).to_have_count(0)
        self.expect(panel.get_by_role("button", name="Auto-fill Metadata")).to_have_count(0)
        self.expect(panel.get_by_role("link", name="Export CSV")).to_be_visible()

if __name__ == "__main__":
    unittest.main()
