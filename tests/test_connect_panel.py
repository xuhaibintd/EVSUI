from __future__ import annotations

import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

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
    def test_create_upload_validation_script_cachebuster_is_current(self):
        source = (TEMPLATES_DIR / "base.html").read_text(encoding="utf-8")

        self.assertIn("js/modules/create-uploads.js') }}?v=20260716-1", source)

    def test_bookrag_mandatory_stages_do_not_render_optional_controls(self):
        source = (TEMPLATES_DIR / "partials" / "create_panel.html").read_text(encoding="utf-8")

        self.assertNotIn("BookRAG Tables", source)
        self.assertNotIn('name="multi_format_bookrag_generate_raw"', source)
        self.assertNotIn('name="multi_format_bookrag_generate_graph"', source)
        self.assertNotIn('name="multi_format_bookrag_run_embedding"', source)

    def test_upload_panel_is_file_only(self):
        source = (TEMPLATES_DIR / "partials" / "selected_documents.html").read_text(encoding="utf-8")

        self.assertNotIn("Document Relationships", source)
        self.assertNotIn("document_relations_json", source)
        self.assertNotIn("data-document-relation-editor", source)

    def test_document_parse_button_is_after_enrichment_nodes(self):
        source = (
            TEMPLATES_DIR / "partials" / "create_doc_modes" / "multi_format_bookrag_fields.html"
        ).read_text(encoding="utf-8")

        self.assertIn('hx-post="/ui/create/parse-documents"', source)
        self.assertIn('data-bookrag-parse-button', source)
        self.assertIn('hx-post="/ui/create/generate-csv"', source)
        self.assertIn('name="bookrag_parse_run_id"', source)
        self.assertIn('name="bookrag_csv_vector_store_name"', source)
        self.assertIn('name="bookrag_csv_target_database"', source)
        self.assertIn('bookrag-csv-generate-actions', source)
        self.assertIn('partials/bookrag_csv_load_panel.html', source)
        self.assertNotIn('bookrag_vector_store_create_panel.html', source)
        load_source = (TEMPLATES_DIR / "partials" / "bookrag_csv_load_panel.html").read_text(encoding="utf-8")
        self.assertIn('bookrag-csv-load-actions', load_source)
        self.assertIn('hx-post="/ui/create/load-csv-tables"', load_source)
        self.assertIn('name="bookrag_csv_run_id"', load_source)
        create_panel_source = (TEMPLATES_DIR / "partials" / "create_panel.html").read_text(encoding="utf-8")
        self.assertIn('partials/bookrag_vector_store_name_field.html', create_panel_source)
        self.assertIn("section.get('title') == 'Basic' and _doc_pipeline_mode == 'multi_format_bookrag'", create_panel_source)
        select_source = (TEMPLATES_DIR / "partials" / "bookrag_vector_store_name_field.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('name="bookrag_loaded_csv_run_id"', select_source)
        self.assertIn('Vector Store Name', select_source)
        self.assertLess(source.index("Named Entity Recognition"), source.index("Document Parsing"))

    def test_document_parsing_result_scrolls_only_after_ten_files_and_shows_total_minutes(self):
        template = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR))).get_template(
            "partials/bookrag_document_parsing_result.html"
        )

        def render(file_count):
            files = [
                {
                    "status": "success",
                    "filename": f"file-{index}.pdf",
                    "element_count": 10,
                    "elapsed_seconds": 3.5,
                }
                for index in range(file_count)
            ]
            return template.render(
                bookrag_document_parsing_error="",
                bookrag_document_parsing={
                    "status": "ok",
                    "success_count": file_count,
                    "failure_count": 0,
                    "file_count": file_count,
                    "workers": 5,
                    "elapsed_seconds": 120,
                    "raw_stage_dir": "raw",
                    "warnings": [],
                    "files": files,
                },
            )

        ten_files = render(10)
        eleven_files = render(11)
        self.assertIn("Elapsed: 2.00 min", ten_files)
        self.assertIn('class="bookrag-parse-file-list"', ten_files)
        self.assertNotIn("bookrag-parse-file-list is-scrollable", ten_files)
        self.assertIn('class="bookrag-parse-file-list is-scrollable"', eleven_files)


class DocumentParseRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_submits_uploaded_documents_and_current_bookrag_settings(self):
        class Request:
            def __init__(self, app):
                self.app = app

            async def form(self):
                return {
                    "vector_store_name": "demo_vs",
                    "multi_format_bookrag_strategy": "vlm",
                    "multi_format_bookrag_ocr_languages": "jpn",
                }

        captured_response = {}

        def template_response(request, template_name, context):
            captured_response.update(template=template_name, context=context)
            return captured_response

        uploads = [{"doc_id": "doc-1", "saved_path": "uploads/documents/doc-1/sample.pdf"}]
        app = SimpleNamespace(
            state=SimpleNamespace(
                document_uploads=uploads,
                evs_state={"params": {"unstructured_api_key": "key"}},
                templates=SimpleNamespace(TemplateResponse=template_response),
            )
        )
        summary = {"status": "ok", "file_count": 1, "success_count": 1, "failure_count": 0}

        with mock.patch.object(web_router_module, "_is_logged_in", return_value=True), mock.patch.object(
            web_router_module, "_activate_session_state"
        ), mock.patch.object(
            web_router_module, "run_bookrag_document_parsing", return_value=summary
        ) as parse_mock:
            response = await web_router_module.parse_documents_for_create(Request(app))

        self.assertEqual(response["template"], "partials/bookrag_document_parsing_result.html")
        self.assertEqual(response["context"]["bookrag_document_parsing"], summary)
        call_kwargs = parse_mock.call_args.kwargs
        self.assertEqual(call_kwargs["vector_store_name"], "demo_vs")
        self.assertEqual(call_kwargs["uploaded_documents"], uploads)
        self.assertEqual(call_kwargs["create_values"]["multi_format_bookrag_strategy"], "vlm")
        self.assertEqual(call_kwargs["create_values"]["multi_format_bookrag_ocr_languages"], "jpn")

    async def test_generate_csv_route_uses_selected_manifest_and_does_not_load_database(self):
        class Request:
            def __init__(self, app):
                self.app = app

            async def form(self):
                return {
                    "bookrag_parse_run_id": "old-run",
                    "bookrag_parse_run_id_current": "current-run",
                    "bookrag_csv_vector_store_name": "demo_vs",
                    "bookrag_csv_target_database": "demo_schema",
                    "multi_format_bookrag_generate_raw": "true",
                }

        captured_response = {}

        def template_response(request, template_name, context):
            captured_response.update(template=template_name, context=context)
            return captured_response

        app = SimpleNamespace(
            state=SimpleNamespace(
                evs_state={"params": {"username": "fallback_schema"}},
                templates=SimpleNamespace(TemplateResponse=template_response),
            )
        )
        summary = {"status": "ready", "file_count": 2, "success_count": 2, "failure_count": 0}

        with mock.patch.object(web_router_module, "_is_logged_in", return_value=True), mock.patch.object(
            web_router_module, "_activate_session_state"
        ), mock.patch.object(
            web_router_module, "run_bookrag_json_to_csv", return_value=summary
        ) as csv_mock:
            response = await web_router_module.generate_csv_for_create(Request(app))

        self.assertEqual(response["template"], "partials/bookrag_csv_generation_result.html")
        self.assertEqual(response["context"]["bookrag_csv_generation"], summary)
        self.assertEqual(response["context"]["bookrag_load_csv_runs"], [summary])
        self.assertTrue(response["context"]["bookrag_load_panel_oob"])
        self.assertEqual(csv_mock.call_args.kwargs["parse_run_id"], "current-run")
        self.assertEqual(csv_mock.call_args.kwargs["vector_store_name"], "demo_vs")
        self.assertEqual(csv_mock.call_args.kwargs["target_database"], "demo_schema")
        self.assertEqual(csv_mock.call_args.kwargs["create_values"]["multi_format_bookrag_generate_raw"], "true")

    async def test_load_route_only_loads_and_verifies_database_tables(self):
        class Request:
            def __init__(self, app):
                self.app = app

            async def form(self):
                return {
                    "bookrag_csv_run_id": "csv-run-1",
                }

        captured_response = {}
        events = []

        def template_response(request, template_name, context):
            captured_response.update(template=template_name, context=context)
            return captured_response

        app = SimpleNamespace(
            state=SimpleNamespace(
                evs_state={"connected": True, "params": {}, "last_success": "", "last_error": ""},
                templates=SimpleNamespace(TemplateResponse=template_response),
            )
        )
        load_summary = {
            "status": "ready",
            "csv_run_id": "csv-run-1",
            "vector_store_name": "demo_vs",
            "target_database": "demo_schema",
            "node_table": "demo_schema.demo_vs_bk_bnode",
            "inserted_rows": 20,
            "task_count": 4,
            "workers": 4,
            "elapsed_seconds": 10,
            "warnings": [],
        }

        def run_load(**kwargs):
            events.append("load")
            return load_summary

        vector_store_mock = mock.Mock()
        with mock.patch.object(web_router_module, "_is_logged_in", return_value=True), mock.patch.object(
            web_router_module, "_activate_session_state"
        ), mock.patch.object(
            web_router_module, "list_bookrag_csv_runs", return_value=[{"csv_run_id": "csv-run-1", "vector_store_name": "demo_vs"}]
        ), mock.patch.object(
            web_router_module, "run_bookrag_csv_load", side_effect=run_load
        ), mock.patch.object(
            web_router_module, "VectorStore", vector_store_mock
        ), mock.patch.object(
            web_router_module, "execute_sql", mock.Mock()
        ), mock.patch.object(
            web_router_module, "_persist_active_session_state"
        ):
            response = await web_router_module.load_csv_tables(Request(app))

        self.assertEqual(events, ["load"])
        vector_store_mock.assert_not_called()
        self.assertEqual(response["template"], "partials/bookrag_csv_load_result.html")
        self.assertEqual(response["context"]["bookrag_csv_load"], load_summary)
        self.assertEqual(response["context"]["bookrag_loaded_csv_runs"], [load_summary])

    async def test_load_route_never_creates_vector_store_when_csv_loading_fails(self):
        class Request:
            def __init__(self, app):
                self.app = app

            async def form(self):
                return {
                    "bookrag_csv_run_id": "csv-run-1",
                    "embeddings_model": "text-embedding-3-small",
                }

        captured_response = {}

        def template_response(request, template_name, context):
            captured_response.update(template=template_name, context=context)
            return captured_response

        app = SimpleNamespace(
            state=SimpleNamespace(
                evs_state={"connected": True, "params": {}, "last_success": "", "last_error": ""},
                templates=SimpleNamespace(TemplateResponse=template_response),
            )
        )
        vector_store_mock = mock.Mock()
        with mock.patch.object(web_router_module, "_is_logged_in", return_value=True), mock.patch.object(
            web_router_module, "_activate_session_state"
        ), mock.patch.object(
            web_router_module, "list_bookrag_csv_runs", return_value=[{"csv_run_id": "csv-run-1", "vector_store_name": "demo_vs"}]
        ), mock.patch.object(
            web_router_module, "run_bookrag_csv_load", side_effect=RuntimeError("one CSV failed")
        ), mock.patch.object(
            web_router_module, "VectorStore", vector_store_mock
        ), mock.patch.object(
            web_router_module, "execute_sql", mock.Mock()
        ):
            response = await web_router_module.load_csv_tables(Request(app))

        vector_store_mock.assert_not_called()
        self.assertEqual(response["template"], "partials/bookrag_csv_load_result.html")
        self.assertIn("one CSV failed", response["context"]["bookrag_csv_load_error"])


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


class DocumentRelationshipAdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
        cls.template = cls.env.get_template("partials/document_relation_admin.html")

    def test_initial_panel_auto_refreshes_and_exposes_manual_refresh(self):
        html = self.template.render(document_relation_admin={"auto_refresh": True})

        self.assertIn('hx-get="/ui/admin/document-relations?refresh=true"', html)
        self.assertIn('hx-trigger="load"', html)
        self.assertIn('name="refresh" value="true"', html)
        self.assertIn("Refresh Vector Stores", html)

    def test_refresh_uses_vsmanager_list_without_changing_selection(self):
        original_manager = web_router_module.VSManager
        original_ensure = web_router_module._ensure_connected_runtime_for_session
        original_apply = web_router_module._apply_chat_list_output_to_state
        try:
            state = {
                "connected": False,
                "selected_vs_name": "mubk_wm3",
                "chat_vs_options": [],
            }
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(evs_state=state)))
            web_router_module.VSManager = SimpleNamespace(list=lambda: object())

            def _ensure(request, app, *, allow_saved_params=False):
                self.assertTrue(allow_saved_params)
                app.state.evs_state["connected"] = True

            web_router_module._ensure_connected_runtime_for_session = _ensure

            def _apply(current_state, _list_output):
                current_state["chat_vs_options"] = ["mubk_wm3", "another_store"]
                current_state["selected_vs_name"] = "another_store"
                return 2, 2, ""

            web_router_module._apply_chat_list_output_to_state = _apply

            status = web_router_module._refresh_document_relation_vector_store_options(request)

            self.assertEqual(status["kind"], "ok")
            self.assertTrue(state["connected"])
            self.assertEqual(state["chat_vs_options"], ["mubk_wm3", "another_store"])
            self.assertEqual(state["selected_vs_name"], "mubk_wm3")
        finally:
            web_router_module.VSManager = original_manager
            web_router_module._ensure_connected_runtime_for_session = original_ensure
            web_router_module._apply_chat_list_output_to_state = original_apply


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
