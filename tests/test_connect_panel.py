from __future__ import annotations

import unittest
from types import SimpleNamespace
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.routers import web as web_router_module


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "app" / "templates"


def _base_evs(connected):
    return {
        "connected": connected,
        "params": {
            "host": "h",
            "username": "u",
            "password": "p",
            "ues_url": "https://example.com/open-analytics",
            "pat_token": "token",
            "pem_file": r"uploads\pem\demo.pem",
            "unstructured_api_url": "https://platform.unstructuredapp.io/api/v1",
            "unstructured_api_key": "unstructured-key",
        },
        "health_preview": "",
        "health_columns": [],
        "health_rows": [],
        "list_preview": "",
        "list_columns": [],
        "list_rows": [],
        "selected_vs_name": "",
        "destroy_status": "neutral",
        "destroy_preview": "",
        "last_success": "",
        "last_error": "",
        "connected_at": "",
    }


class CreatePanelBookRAGToggleTests(unittest.TestCase):
    def test_bookrag_uses_grouped_core_audit_graph_controls(self):
        source = (TEMPLATES_DIR / "partials" / "create_panel.html").read_text(encoding="utf-8")

        self.assertIn("Core (bdoc + bblk + bnode + bdrel)", source)
        self.assertIn("Audit (braw)", source)
        self.assertIn("Graph (bent + belnk + brel)", source)
        self.assertIn('name="multi_format_bookrag_generate_graph"', source)
        self.assertNotIn('name="multi_format_bookrag_generate_entities"', source)
        self.assertNotIn('name="multi_format_bookrag_generate_entity_links"', source)
        self.assertNotIn('name="multi_format_bookrag_generate_entity_relations"', source)


class ConnectPanelTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
        cls.template = cls.env.get_template("partials/evs_connect_panel.html")

    def _render(self, connected):
        return self.template.render(evs=_base_evs(connected), is_htmx=False)

    def test_disconnected_state_enables_connect_and_disables_disconnect(self):
        html = self._render(False)
        self.assertIn('data-step1-connected="false"', html)
        self.assertNotIn('name="unstructured_api_url"', html)
        self.assertNotIn('name="unstructured_api_key"', html)
        self.assertIn('<button type="submit" form="evs-connect-form" class="connect-submit-btn progress-btn" data-progress-button aria-disabled="false">', html)
        self.assertIn('<form id="evs-reset-form" class="connect-reset-form" hx-post="/ui/evs/reset" hx-target="#section-connect-content" hx-swap="innerHTML">', html)
        self.assertIn('<button type="submit" class="ghost progress-btn" data-progress-button disabled aria-disabled="true">', html)

    def test_connected_state_disables_connect_and_enables_disconnect(self):
        html = self._render(True)
        self.assertIn('data-step1-connected="true"', html)
        self.assertIn('<button type="submit" form="evs-connect-form" class="connect-submit-btn progress-btn" data-progress-button disabled aria-disabled="true">', html)
        self.assertIn('<form id="evs-reset-form" class="connect-reset-form" hx-post="/ui/evs/reset" hx-target="#section-connect-content" hx-swap="innerHTML">', html)
        self.assertIn('<button type="submit" class="ghost progress-btn" data-progress-button aria-disabled="false">', html)

    def test_string_connected_values_are_normalized(self):
        html_true = self._render("true")
        html_false = self._render("false")
        self.assertIn('data-step1-connected="true"', html_true)
        self.assertIn('data-step1-connected="false"', html_false)
        self.assertIn('connect-submit-btn progress-btn" data-progress-button disabled aria-disabled="true"', html_true)
        self.assertIn('<button type="submit" class="ghost progress-btn" data-progress-button disabled aria-disabled="true">', html_false)


class UnstructuredAdminPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
        cls.template = cls.env.get_template("partials/bookrag_admin_panel.html")

    def test_save_confirmation_status_is_rendered(self):
        html = self.template.render(
            evs=_base_evs(True),
            unstructured_status={
                "kind": "ok",
                "title": "Saved",
                "detail": "Unstructured IO account saved for the current session.",
            },
        )

        self.assertIn('hx-post="/ui/admin/unstructured-config"', html)
        self.assertIn('role="status" aria-live="polite"', html)
        self.assertIn("Saved", html)
        self.assertIn("Unstructured IO account saved for the current session.", html)

    def test_admin_tabs_are_rendered(self):
        html = self.template.render(evs=_base_evs(True), unstructured_status=None, json_inspector={"files": [], "selected_file": "", "summary": None, "error": ""})

        self.assertIn("External Account Configuration", html)
        self.assertIn("Business Configuration", html)
        self.assertIn('class="admin-rule-tab-panel admin-rule-panel-business"', html)
        self.assertIn("Unstructured IO", html)


class ConnectResetRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_evs_reset_reinitializes_create_values_without_name_error(self):
        original_is_logged_in = web_router_module._is_logged_in
        original_activate = web_router_module._activate_session_state
        original_cleanup = web_router_module._cleanup_context
        original_default_state = web_router_module._default_evs_state
        original_persist = web_router_module._persist_active_session_state
        original_render = web_router_module._render_connect_panel
        try:
            persisted = {"called": False}
            web_router_module._is_logged_in = lambda request, app: True
            web_router_module._activate_session_state = lambda request, app: None
            web_router_module._cleanup_context = lambda: {"vs_disconnect": "ok"}
            web_router_module._default_evs_state = lambda: {
                "connected": False,
                "params": {},
                "last_success": "",
                "connect_steps": [],
            }
            web_router_module._persist_active_session_state = lambda request, app: persisted.update(called=True)
            web_router_module._render_connect_panel = lambda request, app: {
                "evs": app.state.evs_state,
                "create_form_values": app.state.create_form_values,
                "chat_history": app.state.chat_history,
            }

            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
                evs_state={"connected": True, "params": {"host": "x"}},
                create_form_values={"vector_store_name": "before"},
                last_create_operation={"x": 1},
                document_uploads=[{"name": "demo"}],
                document_upload_notices=["n"],
                chat_history=[{"role": "user", "content": "before"}],
            )))

            result = await web_router_module.evs_reset(request)

            self.assertFalse(result["evs"]["connected"])
            self.assertEqual(result["evs"]["last_success"], "Disconnected and reset completed.")
            self.assertIsInstance(result["create_form_values"], dict)
            self.assertIn("vector_store_name", result["create_form_values"])
            self.assertEqual(result["chat_history"], [])
            self.assertTrue(persisted["called"])
        finally:
            web_router_module._is_logged_in = original_is_logged_in
            web_router_module._activate_session_state = original_activate
            web_router_module._cleanup_context = original_cleanup
            web_router_module._default_evs_state = original_default_state
            web_router_module._persist_active_session_state = original_persist
            web_router_module._render_connect_panel = original_render


class UnstructuredAdminRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_updates_session_params_and_returns_confirmation(self):
        original_is_logged_in = web_router_module._is_logged_in
        original_activate = web_router_module._activate_session_state
        original_persist = web_router_module._persist_active_session_state
        try:
            persisted = {"called": False}
            web_router_module._is_logged_in = lambda request, app: True
            web_router_module._activate_session_state = lambda request, app: None
            web_router_module._persist_active_session_state = lambda request, app: persisted.update(called=True)

            def template_response(request, template_name, context):
                return {
                    "template_name": template_name,
                    "context": context,
                }

            app = SimpleNamespace(
                state=SimpleNamespace(
                    evs_state={"params": {}},
                    templates=SimpleNamespace(TemplateResponse=template_response),
                )
            )
            request = SimpleNamespace(app=app)

            result = await web_router_module.update_unstructured_config_panel(
                request,
                unstructured_api_url=" https://session.example/api ",
                unstructured_api_key=" session-key ",
            )

            self.assertEqual(app.state.evs_state["params"]["unstructured_api_url"], "https://session.example/api")
            self.assertEqual(app.state.evs_state["params"]["unstructured_api_key"], "session-key")
            self.assertTrue(persisted["called"])
            self.assertEqual(result["template_name"], "partials/bookrag_admin_panel.html")
            self.assertEqual(result["context"]["unstructured_status"]["title"], "Saved")
        finally:
            web_router_module._is_logged_in = original_is_logged_in
            web_router_module._activate_session_state = original_activate
            web_router_module._persist_active_session_state = original_persist


if __name__ == "__main__":
    unittest.main()
