from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.workflows.create_flow import (
    _scalar_from_sql_result,
    _wait_for_vectorstore_ready,
    handle_upload_and_prepare_create,
)


class _DummyRequest:
    def __init__(self, form_data):
        self._form_data = form_data

    async def form(self):
        return self._form_data


class _DummyTemplates:
    def TemplateResponse(self, request, template_name, context):
        return {"template": template_name, "context": context}


class _DummyCursor:
    def __init__(self, row):
        self._row = row
        self.closed = False

    def fetchone(self):
        return self._row

    def close(self):
        self.closed = True


class CreateFlowDocumentSourceTests(unittest.IsolatedAsyncioTestCase):
    def _build_app(self):
        state = SimpleNamespace(
            evs_state={"connected": True, "last_success": "", "last_error": "", "params": {}},
            document_uploads=[],
            document_upload_notices=[],
            create_form_values={},
            last_create_operation=None,
        )
        return SimpleNamespace(state=state)

    async def _run_flow(self, form_data):
        return await handle_upload_and_prepare_create(
            _DummyRequest(form_data),
            self._build_app(),
            _DummyTemplates(),
            vector_store_cls=None,
            execute_sql_fn=lambda *args, **kwargs: None,
            save_document_uploads_fn=self._save_document_uploads,
            collect_upload_files_fn=lambda form, field_name="files": [],
            resolve_path_hint_fn=lambda value: value,
            now_ts=lambda: "2026-04-14 00:00:00",
            is_htmx=True,
            is_vectorstore_already_exists_error_fn=lambda value: False,
            verify_vectorstore_exists_fn=lambda *args, **kwargs: (False, "", ""),
            append_connect_step=lambda *args, **kwargs: None,
        )

    async def _save_document_uploads(self, files):
        return [], []

    def test_scalar_from_sql_result_reads_cursor_fetchone(self):
        cursor = _DummyCursor((42,))
        self.assertEqual(_scalar_from_sql_result(cursor), 42)
        self.assertTrue(cursor.closed)

    def test_scalar_from_sql_result_reads_mapping_cursor_row(self):
        cursor = _DummyCursor({"Count(*)": 7033})
        self.assertEqual(_scalar_from_sql_result(cursor), 7033)
        self.assertTrue(cursor.closed)

    def test_scalar_from_sql_result_reads_scalar_cursor_row(self):
        cursor = _DummyCursor("7033")
        self.assertEqual(_scalar_from_sql_result(cursor), 7033)
        self.assertTrue(cursor.closed)

    async def test_ready_wait_has_no_default_time_cutoff(self):
        statuses = iter(("Processing", "Ready"))

        class VectorStore:
            def status(self):
                return next(statuses)

        with patch(
            "app.workflows.create_flow.CREATE_READY_TIMEOUT_SECONDS",
            None,
        ), patch(
            "app.workflows.create_flow.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep_mock:
            ready, _preview, error, _status_text, state = await _wait_for_vectorstore_ready(VectorStore())

        self.assertTrue(ready)
        self.assertEqual(error, "")
        self.assertEqual(state, "ready")
        sleep_mock.assert_awaited_once()

    async def test_manual_document_files_satisfy_required_document_source(self):
        response = await self._run_flow({
            "vector_store_name": "demo_vs",
            "doc_pipeline_mode": "text_core",
            "embeddings_model": "text-embedding-3-small",
            "document_files": "uploads/documents/sample.pdf",
            "create_mode": "core",
            "create_preset": "auto",
        })

        result = response["context"]["create_result"]
        self.assertEqual(result["message"], "Step 2 failed: VectorStore runtime is unavailable in current environment.")
        payload = json.loads(result["create_payload_json"])
        exec_payload = json.loads(result["create_execute_payload_json"])
        self.assertEqual(payload["document_files"], "uploads/documents/sample.pdf")
        self.assertEqual(exec_payload["document_files"], ["uploads/documents/sample.pdf"])

    async def test_missing_document_source_still_blocks_create(self):
        response = await self._run_flow({
            "vector_store_name": "demo_vs",
            "doc_pipeline_mode": "text_core",
            "embeddings_model": "text-embedding-3-small",
            "create_mode": "core",
            "create_preset": "auto",
        })

        result = response["context"]["create_result"]
        self.assertEqual(result["message"], "Required fields missing: document_source")

    async def test_final_create_strips_file_ingestor_params_from_preprocessed_payload(self):
        captured_kwargs = {}

        class VectorStore:
            def __init__(self, name):
                self.name = name

            def create(self, **kwargs):
                captured_kwargs.update(kwargs)
                return "created"

            def status(self):
                return "Ready"

        def preprocess_create_payload(**kwargs):
            payload = dict(kwargs["exec_payload"])
            payload["object_names"] = "demo_nodes"
            payload["data_columns"] = ["content"]
            payload["key_columns"] = ["node_id"]
            payload["nv_ingestor"] = "legacy-ingestor"
            payload["custom_ingestor"] = "legacy-custom-ingestor"
            payload["ingest_host"] = "legacy-host"
            return payload, {"skip_vectorstore_create": False}

        handler = SimpleNamespace(
            MODE="multi_format_bookrag",
            LABEL="Multi-Format BookRAG",
            should_run_vectorstore_create=lambda create_values: True,
            preprocess_create_payload=preprocess_create_payload,
            build_skip_create_message=lambda summary: "skipped",
        )

        app = self._build_app()
        with patch("app.workflows.create_flow.get_doc_pipeline_handler", return_value=handler):
            response = await handle_upload_and_prepare_create(
                _DummyRequest({
                    "vector_store_name": "demo_vs",
                    "doc_pipeline_mode": "multi_format_bookrag",
                    "embeddings_model": "text-embedding-3-small",
                    "document_files": "uploads/documents/sample.pdf",
                    "create_mode": "core",
                    "create_preset": "auto",
                }),
                app,
                _DummyTemplates(),
                vector_store_cls=VectorStore,
                execute_sql_fn=lambda *args, **kwargs: None,
                save_document_uploads_fn=self._save_document_uploads,
                collect_upload_files_fn=lambda form, field_name="files": [],
                resolve_path_hint_fn=lambda value: value,
                now_ts=lambda: "2026-04-14 00:00:00",
                is_htmx=True,
                is_vectorstore_already_exists_error_fn=lambda value: False,
                verify_vectorstore_exists_fn=lambda *args, **kwargs: (False, "", ""),
                append_connect_step=lambda *args, **kwargs: None,
            )

        result = response["context"]["create_result"]
        self.assertIn(result["status"], {"ok", "ok_with_warnings"})
        self.assertIsNone(captured_kwargs["nv_ingestor"])
        self.assertNotIn("custom_ingestor", captured_kwargs)
        self.assertNotIn("ingest_host", captured_kwargs)
        self.assertEqual(captured_kwargs["object_names"], "demo_nodes")
        self.assertEqual(captured_kwargs["data_columns"], ["content"])
        self.assertEqual(captured_kwargs["key_columns"], ["node_id"])

    async def test_text_core_final_create_keeps_document_files(self):
        captured_kwargs = {}

        class VectorStore:
            def __init__(self, name):
                self.name = name

            def create(self, **kwargs):
                captured_kwargs.update(kwargs)
                return "created"

            def status(self):
                return "Ready"

        response = await handle_upload_and_prepare_create(
            _DummyRequest({
                "vector_store_name": "demo_vs",
                "doc_pipeline_mode": "text_core",
                "embeddings_model": "text-embedding-3-small",
                "document_files": "uploads/documents/sample.pdf",
                "create_mode": "core",
                "create_preset": "auto",
            }),
            self._build_app(),
            _DummyTemplates(),
            vector_store_cls=VectorStore,
            execute_sql_fn=lambda *args, **kwargs: None,
            save_document_uploads_fn=self._save_document_uploads,
            collect_upload_files_fn=lambda form, field_name="files": [],
            resolve_path_hint_fn=lambda value: value,
            now_ts=lambda: "2026-04-14 00:00:00",
            is_htmx=True,
            is_vectorstore_already_exists_error_fn=lambda value: False,
            verify_vectorstore_exists_fn=lambda *args, **kwargs: (False, "", ""),
            append_connect_step=lambda *args, **kwargs: None,
        )

        result = response["context"]["create_result"]
        self.assertIn(result["status"], {"ok", "ok_with_warnings"})
        self.assertEqual(captured_kwargs["document_files"], ["uploads/documents/sample.pdf"])

    async def test_loaded_bookrag_run_uses_existing_create_controls_without_document_preprocessing(self):
        captured_kwargs = {}
        status_calls = []
        csv_run_id = "bookrag_parse_bb63c12e__b8f3fb_csv_20260715_041444_f1d21ae4"
        load_summary = {
            "status": "ready",
            "csv_run_id": csv_run_id,
            "vector_store_name": "demo_vs",
            "target_database": "demo_schema",
            "node_table": "demo_schema.demo_vs_bk_bnode",
            "table_targets": {"nodes": "demo_vs_bk_bnode"},
            "persisted_row_counts": {"nodes": 10, "entities": 2, "entity_relations": 1},
            "warnings": [],
        }

        def _load_summary_for_run(*, csv_run_id: str):
            self.assertEqual(csv_run_id, load_summary["csv_run_id"])
            return load_summary

        class VectorStore:
            def __init__(self, name):
                self.name = name

            def create(self, **kwargs):
                captured_kwargs.update(kwargs)
                return "created"

            def status(self):
                return "Ready"

        form_data = {
            "bookrag_loaded_csv_run_id": csv_run_id,
            "doc_pipeline_mode": "multi_format_bookrag",
            "embeddings_model": "text-embedding-3-small",
            "search_algorithm": "VECTORDISTANCE",
            "create_mode": "core",
            "create_preset": "auto",
        }
        with patch(
            "app.workflows.create_flow.get_ready_bookrag_csv_load_summary",
            side_effect=_load_summary_for_run,
        ), patch(
            "app.services.doc_modes.multi_format_bookrag_mode.get_ready_bookrag_csv_load_summary",
            side_effect=_load_summary_for_run,
        ), patch(
            "app.services.doc_modes.multi_format_bookrag_mode.update_bookrag_csv_vector_store_status",
            side_effect=lambda **kwargs: status_calls.append(kwargs),
        ):
            response = await handle_upload_and_prepare_create(
                _DummyRequest(form_data),
                self._build_app(),
                _DummyTemplates(),
                vector_store_cls=VectorStore,
                execute_sql_fn=lambda *args, **kwargs: [{"Count(*)": 10}],
                save_document_uploads_fn=self._save_document_uploads,
                collect_upload_files_fn=lambda form, field_name="files": [],
                resolve_path_hint_fn=lambda value: value,
                now_ts=lambda: "2026-04-14 00:00:00",
                is_htmx=True,
                is_vectorstore_already_exists_error_fn=lambda value: False,
                verify_vectorstore_exists_fn=lambda *args, **kwargs: (False, "", ""),
                append_connect_step=lambda *args, **kwargs: None,
            )

        result = response["context"]["create_result"]
        self.assertIn(result["status"], {"ok", "ok_with_warnings"})
        self.assertIn("Elapsed:", result["message"])
        self.assertIn(" min.", result["message"])
        self.assertEqual(result["vector_store_name"], "demo_vs")
        self.assertEqual(captured_kwargs["target_database"], "demo_schema")
        self.assertEqual(captured_kwargs["object_names"], "demo_vs_bk_bnode")
        self.assertEqual(captured_kwargs["data_columns"], ["content"])
        self.assertEqual(captured_kwargs["key_columns"], ["doc_id", "node_id"])
        self.assertNotIn("document_files", captured_kwargs)
        self.assertEqual([call["status"] for call in status_calls], ["creating", "ready"])

    async def test_existing_ready_store_reconciles_loaded_run_manifest(self):
        status_calls = []
        csv_run_id = "csv-run-existing-ready"
        load_summary = {
            "status": "ready",
            "csv_run_id": csv_run_id,
            "vector_store_name": "demo_vs",
            "target_database": "demo_schema",
            "node_table": "demo_schema.demo_vs_bk_bnode",
            "table_targets": {"nodes": "demo_vs_bk_bnode"},
            "persisted_row_counts": {"nodes": 10},
            "warnings": [],
        }

        class VectorStore:
            def __init__(self, name):
                self.name = name

            def status(self):
                return "Ready"

            def create(self, **kwargs):
                raise AssertionError("existing Ready store must not be created again")

        form_data = {
            "bookrag_loaded_csv_run_id": csv_run_id,
            "doc_pipeline_mode": "multi_format_bookrag",
            "embeddings_model": "text-embedding-3-small",
            "search_algorithm": "VECTORDISTANCE",
            "create_mode": "core",
            "create_preset": "auto",
        }
        with patch(
            "app.workflows.create_flow.get_ready_bookrag_csv_load_summary",
            return_value=load_summary,
        ), patch(
            "app.services.doc_modes.multi_format_bookrag_mode.update_bookrag_csv_vector_store_status",
            side_effect=lambda **kwargs: status_calls.append(kwargs),
        ):
            response = await handle_upload_and_prepare_create(
                _DummyRequest(form_data),
                self._build_app(),
                _DummyTemplates(),
                vector_store_cls=VectorStore,
                execute_sql_fn=lambda sql: _DummyCursor((10,)),
                save_document_uploads_fn=self._save_document_uploads,
                collect_upload_files_fn=lambda form, field_name="files": [],
                resolve_path_hint_fn=lambda value: value,
                now_ts=lambda: "2026-04-14 00:00:00",
                is_htmx=True,
                is_vectorstore_already_exists_error_fn=lambda value: False,
                verify_vectorstore_exists_fn=lambda *args, **kwargs: (True, "found", ""),
                append_connect_step=lambda *args, **kwargs: None,
            )

        result = response["context"]["create_result"]
        self.assertEqual(result["status"], "ok_with_warnings")
        self.assertEqual([call["status"] for call in status_calls], ["ready"])

    async def test_loaded_bookrag_run_fails_when_vector_index_is_empty(self):
        status_calls = []
        csv_run_id = "bookrag_parse_bb63c12e__b8f3fb_csv_20260715_041444_f1d21ae4"
        load_summary = {
            "status": "ready",
            "csv_run_id": csv_run_id,
            "vector_store_name": "demo_vs",
            "target_database": "demo_schema",
            "node_table": "demo_schema.demo_vs_bk_bnode",
            "table_targets": {"nodes": "demo_vs_bk_bnode"},
            "persisted_row_counts": {"nodes": 10},
            "warnings": [],
        }

        class VectorStore:
            def __init__(self, name):
                self.name = name

            def create(self, **kwargs):
                return "created"

            def status(self):
                return "Ready"

        form_data = {
            "bookrag_loaded_csv_run_id": csv_run_id,
            "doc_pipeline_mode": "multi_format_bookrag",
            "embeddings_model": "text-embedding-3-small",
            "search_algorithm": "VECTORDISTANCE",
            "create_mode": "core",
            "create_preset": "auto",
        }
        with patch(
            "app.workflows.create_flow.get_ready_bookrag_csv_load_summary",
            return_value=load_summary,
        ), patch(
            "app.services.doc_modes.multi_format_bookrag_mode.get_ready_bookrag_csv_load_summary",
            return_value=load_summary,
        ), patch(
            "app.services.doc_modes.multi_format_bookrag_mode.update_bookrag_csv_vector_store_status",
            side_effect=lambda **kwargs: status_calls.append(kwargs),
        ), patch(
            "app.workflows.create_flow.BOOKRAG_INDEX_READY_TIMEOUT_SECONDS",
            0,
        ):
            response = await handle_upload_and_prepare_create(
                _DummyRequest(form_data),
                self._build_app(),
                _DummyTemplates(),
                vector_store_cls=VectorStore,
                execute_sql_fn=lambda *args, **kwargs: [{"Count(*)": 0}],
                save_document_uploads_fn=self._save_document_uploads,
                collect_upload_files_fn=lambda form, field_name="files": [],
                resolve_path_hint_fn=lambda value: value,
                now_ts=lambda: "2026-04-14 00:00:00",
                is_htmx=True,
                is_vectorstore_already_exists_error_fn=lambda value: False,
                verify_vectorstore_exists_fn=lambda *args, **kwargs: (False, "", ""),
                append_connect_step=lambda *args, **kwargs: None,
            )

        result = response["context"]["create_result"]
        self.assertEqual(result["status"], "error")
        self.assertIn("vector index table is empty", result["message"])
        self.assertIn("Elapsed:", result["message"])
        self.assertIn(" min.", result["message"])
        self.assertEqual([call["status"] for call in status_calls], ["creating", "failed"])

    async def test_loaded_bookrag_run_remains_creating_when_status_times_out(self):
        status_calls = []
        sql_calls = []
        csv_run_id = "csv-run-pending"
        load_summary = {
            "status": "ready",
            "csv_run_id": csv_run_id,
            "vector_store_name": "demo_vs",
            "target_database": "demo_schema",
            "node_table": "demo_schema.demo_vs_bk_bnode",
            "table_targets": {"nodes": "demo_vs_bk_bnode"},
            "persisted_row_counts": {"nodes": 10},
            "warnings": [],
        }

        class VectorStore:
            def __init__(self, name):
                self.name = name

            def create(self, **kwargs):
                return "submitted"

            def status(self):
                return "Processing"

        def execute_sql(sql):
            sql_calls.append(sql)
            raise AssertionError("index SQL must not run before VectorStore is Ready")

        form_data = {
            "bookrag_loaded_csv_run_id": csv_run_id,
            "doc_pipeline_mode": "multi_format_bookrag",
            "embeddings_model": "text-embedding-3-small",
            "search_algorithm": "VECTORDISTANCE",
            "create_mode": "core",
            "create_preset": "auto",
        }
        with patch(
            "app.workflows.create_flow.get_ready_bookrag_csv_load_summary",
            return_value=load_summary,
        ), patch(
            "app.services.doc_modes.multi_format_bookrag_mode.get_ready_bookrag_csv_load_summary",
            return_value=load_summary,
        ), patch(
            "app.services.doc_modes.multi_format_bookrag_mode.update_bookrag_csv_vector_store_status",
            side_effect=lambda **kwargs: status_calls.append(kwargs),
        ), patch(
            "app.workflows.create_flow.CREATE_READY_TIMEOUT_SECONDS",
            0,
        ):
            response = await handle_upload_and_prepare_create(
                _DummyRequest(form_data),
                self._build_app(),
                _DummyTemplates(),
                vector_store_cls=VectorStore,
                execute_sql_fn=execute_sql,
                save_document_uploads_fn=self._save_document_uploads,
                collect_upload_files_fn=lambda form, field_name="files": [],
                resolve_path_hint_fn=lambda value: value,
                now_ts=lambda: "2026-04-14 00:00:00",
                is_htmx=True,
                is_vectorstore_already_exists_error_fn=lambda value: False,
                verify_vectorstore_exists_fn=lambda *args, **kwargs: (False, "", ""),
                append_connect_step=lambda *args, **kwargs: None,
            )

        result = response["context"]["create_result"]
        self.assertEqual(result["status"], "pending")
        self.assertIn("server-side operation", result["message"])
        self.assertEqual(sql_calls, [])
        self.assertEqual([call["status"] for call in status_calls], ["creating"])

    async def test_loaded_bookrag_run_marks_explicit_status_failure(self):
        status_calls = []
        csv_run_id = "csv-run-failed"
        load_summary = {
            "status": "ready",
            "csv_run_id": csv_run_id,
            "vector_store_name": "demo_vs",
            "target_database": "demo_schema",
            "node_table": "demo_schema.demo_vs_bk_bnode",
            "table_targets": {"nodes": "demo_vs_bk_bnode"},
            "persisted_row_counts": {"nodes": 10},
            "warnings": [],
        }

        class VectorStore:
            def __init__(self, name):
                self.name = name

            def create(self, **kwargs):
                return "submitted"

            def status(self):
                return "Create Failed"

        form_data = {
            "bookrag_loaded_csv_run_id": csv_run_id,
            "doc_pipeline_mode": "multi_format_bookrag",
            "embeddings_model": "text-embedding-3-small",
            "search_algorithm": "VECTORDISTANCE",
            "create_mode": "core",
            "create_preset": "auto",
        }
        with patch(
            "app.workflows.create_flow.get_ready_bookrag_csv_load_summary",
            return_value=load_summary,
        ), patch(
            "app.services.doc_modes.multi_format_bookrag_mode.get_ready_bookrag_csv_load_summary",
            return_value=load_summary,
        ), patch(
            "app.services.doc_modes.multi_format_bookrag_mode.update_bookrag_csv_vector_store_status",
            side_effect=lambda **kwargs: status_calls.append(kwargs),
        ):
            response = await handle_upload_and_prepare_create(
                _DummyRequest(form_data),
                self._build_app(),
                _DummyTemplates(),
                vector_store_cls=VectorStore,
                execute_sql_fn=lambda sql: (_ for _ in ()).throw(
                    AssertionError("index SQL must not run after status failure")
                ),
                save_document_uploads_fn=self._save_document_uploads,
                collect_upload_files_fn=lambda form, field_name="files": [],
                resolve_path_hint_fn=lambda value: value,
                now_ts=lambda: "2026-04-14 00:00:00",
                is_htmx=True,
                is_vectorstore_already_exists_error_fn=lambda value: False,
                verify_vectorstore_exists_fn=lambda *args, **kwargs: (False, "", ""),
                append_connect_step=lambda *args, **kwargs: None,
            )

        result = response["context"]["create_result"]
        self.assertEqual(result["status"], "error")
        self.assertIn("reported failure", result["message"])
        self.assertEqual([call["status"] for call in status_calls], ["creating", "failed"])

    async def test_ready_status_with_unavailable_row_check_is_warning_not_failure(self):
        status_calls = []
        csv_run_id = "csv-run-row-check-unavailable"
        load_summary = {
            "status": "ready",
            "csv_run_id": csv_run_id,
            "vector_store_name": "demo_vs",
            "target_database": "demo_schema",
            "node_table": "demo_schema.demo_vs_bk_bnode",
            "table_targets": {"nodes": "demo_vs_bk_bnode"},
            "persisted_row_counts": {"nodes": 10},
            "warnings": [],
        }

        class VectorStore:
            def __init__(self, name):
                self.name = name

            def create(self, **kwargs):
                return "submitted"

            def status(self):
                return "Ready"

        form_data = {
            "bookrag_loaded_csv_run_id": csv_run_id,
            "doc_pipeline_mode": "multi_format_bookrag",
            "embeddings_model": "text-embedding-3-small",
            "search_algorithm": "VECTORDISTANCE",
            "create_mode": "core",
            "create_preset": "auto",
        }
        with patch(
            "app.workflows.create_flow.get_ready_bookrag_csv_load_summary",
            return_value=load_summary,
        ), patch(
            "app.services.doc_modes.multi_format_bookrag_mode.get_ready_bookrag_csv_load_summary",
            return_value=load_summary,
        ), patch(
            "app.services.doc_modes.multi_format_bookrag_mode.update_bookrag_csv_vector_store_status",
            side_effect=lambda **kwargs: status_calls.append(kwargs),
        ), patch(
            "app.workflows.create_flow.BOOKRAG_INDEX_READY_TIMEOUT_SECONDS",
            0,
        ):
            response = await handle_upload_and_prepare_create(
                _DummyRequest(form_data),
                self._build_app(),
                _DummyTemplates(),
                vector_store_cls=VectorStore,
                execute_sql_fn=lambda sql: _DummyCursor(("not-a-number",)),
                save_document_uploads_fn=self._save_document_uploads,
                collect_upload_files_fn=lambda form, field_name="files": [],
                resolve_path_hint_fn=lambda value: value,
                now_ts=lambda: "2026-04-14 00:00:00",
                is_htmx=True,
                is_vectorstore_already_exists_error_fn=lambda value: False,
                verify_vectorstore_exists_fn=lambda *args, **kwargs: (False, "", ""),
                append_connect_step=lambda *args, **kwargs: None,
            )

        result = response["context"]["create_result"]
        self.assertEqual(result["status"], "ok_with_warnings")
        self.assertTrue(any("verification was unavailable" in warning for warning in result["warnings"]))
        self.assertEqual([call["status"] for call in status_calls], ["creating", "ready"])


    async def test_loaded_multi_format_run_creates_from_unstructured_table_without_documents(self):
        captured_kwargs = {}
        status_calls = []
        sql_calls = []
        csv_run_id = "multi-format-csv-run"
        load_summary = {
            "status": "ready",
            "csv_run_id": csv_run_id,
            "vector_store_name": "demo_vs",
            "target_database": "demo_schema",
            "table_name": "demo_vs_unstructured",
            "qualified_table": "demo_schema.demo_vs_unstructured",
            "persisted_row_count": 7,
            "csv_file_count": 2,
            "warnings": [],
        }

        class VectorStore:
            def __init__(self, name):
                self.name = name

            def create(self, **kwargs):
                captured_kwargs.update(kwargs)
                return "created"

            def status(self):
                return "Ready"

        form_data = {
            "multi_format_loaded_csv_run_id": csv_run_id,
            "doc_pipeline_mode": "multi_format",
            "embeddings_model": "text-embedding-3-small",
            "search_algorithm": "VECTORDISTANCE",
            "create_mode": "core",
            "create_preset": "auto",
        }

        def execute_sql(sql):
            sql_calls.append(sql)
            if '"demo_vs_unstructured"' in sql:
                return _DummyCursor((7,))
            if '"vectorstore_demo_vs_index"' in sql:
                return _DummyCursor((7,))
            raise AssertionError(f"Unexpected SQL: {sql}")

        with patch(
            "app.workflows.create_flow.get_ready_multi_format_csv_load_summary",
            return_value=load_summary,
        ), patch(
            "app.services.doc_modes.multi_format_mode.get_ready_multi_format_csv_load_summary",
            return_value=load_summary,
        ), patch(
            "app.services.doc_modes.multi_format_mode.update_multi_format_csv_vector_store_status",
            side_effect=lambda **kwargs: status_calls.append(kwargs),
        ):
            response = await handle_upload_and_prepare_create(
                _DummyRequest(form_data),
                self._build_app(),
                _DummyTemplates(),
                vector_store_cls=VectorStore,
                execute_sql_fn=execute_sql,
                save_document_uploads_fn=self._save_document_uploads,
                collect_upload_files_fn=lambda form, field_name="files": [],
                resolve_path_hint_fn=lambda value: value,
                now_ts=lambda: "2026-07-16 00:00:00",
                is_htmx=True,
                is_vectorstore_already_exists_error_fn=lambda value: False,
                verify_vectorstore_exists_fn=lambda *args, **kwargs: (False, "", ""),
                append_connect_step=lambda *args, **kwargs: None,
            )

        result = response["context"]["create_result"]
        self.assertIn(result["status"], {"ok", "ok_with_warnings"})
        self.assertEqual(result["vector_store_name"], "demo_vs")
        self.assertEqual(captured_kwargs["target_database"], "demo_schema")
        self.assertEqual(captured_kwargs["object_names"], "demo_vs_unstructured")
        self.assertEqual(captured_kwargs["data_columns"], ["text"])
        self.assertEqual(captured_kwargs["key_columns"], ["id"])
        self.assertNotIn("document_files", captured_kwargs)
        self.assertIn("7 rows from 2 file(s)", result["message"])
        self.assertEqual([call["status"] for call in status_calls], ["creating", "ready"])
        self.assertTrue(any('"demo_vs_unstructured"' in sql for sql in sql_calls))
        self.assertTrue(any('"vectorstore_demo_vs_index"' in sql for sql in sql_calls))

    async def test_loaded_multi_format_run_fails_when_vector_index_is_empty(self):
        status_calls = []
        csv_run_id = "multi-format-empty-index"
        load_summary = {
            "status": "ready",
            "csv_run_id": csv_run_id,
            "vector_store_name": "demo_vs",
            "target_database": "demo_schema",
            "table_name": "demo_vs_unstructured",
            "qualified_table": "demo_schema.demo_vs_unstructured",
            "persisted_row_count": 7,
            "csv_file_count": 2,
            "warnings": [],
        }

        class VectorStore:
            def __init__(self, name):
                self.name = name

            def create(self, **kwargs):
                return "created"

            def status(self):
                return "Ready"

        def execute_sql(sql):
            if '"demo_vs_unstructured"' in sql:
                return _DummyCursor((7,))
            if '"vectorstore_demo_vs_index"' in sql:
                return _DummyCursor((0,))
            raise AssertionError(f"Unexpected SQL: {sql}")

        form_data = {
            "multi_format_loaded_csv_run_id": csv_run_id,
            "doc_pipeline_mode": "multi_format",
            "embeddings_model": "text-embedding-3-small",
            "search_algorithm": "VECTORDISTANCE",
            "create_mode": "core",
            "create_preset": "auto",
        }
        with patch(
            "app.workflows.create_flow.get_ready_multi_format_csv_load_summary",
            return_value=load_summary,
        ), patch(
            "app.services.doc_modes.multi_format_mode.get_ready_multi_format_csv_load_summary",
            return_value=load_summary,
        ), patch(
            "app.services.doc_modes.multi_format_mode.update_multi_format_csv_vector_store_status",
            side_effect=lambda **kwargs: status_calls.append(kwargs),
        ), patch(
            "app.workflows.create_flow.BOOKRAG_INDEX_READY_TIMEOUT_SECONDS",
            0,
        ):
            response = await handle_upload_and_prepare_create(
                _DummyRequest(form_data),
                self._build_app(),
                _DummyTemplates(),
                vector_store_cls=VectorStore,
                execute_sql_fn=execute_sql,
                save_document_uploads_fn=self._save_document_uploads,
                collect_upload_files_fn=lambda form, field_name="files": [],
                resolve_path_hint_fn=lambda value: value,
                now_ts=lambda: "2026-07-16 00:00:00",
                is_htmx=True,
                is_vectorstore_already_exists_error_fn=lambda value: False,
                verify_vectorstore_exists_fn=lambda *args, **kwargs: (False, "", ""),
                append_connect_step=lambda *args, **kwargs: None,
            )

        result = response["context"]["create_result"]
        self.assertEqual(result["status"], "error")
        self.assertIn("Multi-Format vector index table is empty", result["message"])
        self.assertEqual([call["status"] for call in status_calls], ["creating", "failed"])

    async def test_existing_ready_multi_format_store_requires_complete_index(self):
        status_calls = []
        csv_run_id = "multi-format-existing-ready"
        load_summary = {
            "status": "ready",
            "csv_run_id": csv_run_id,
            "vector_store_name": "demo_vs",
            "target_database": "demo_schema",
            "table_name": "demo_vs_unstructured",
            "qualified_table": "demo_schema.demo_vs_unstructured",
            "persisted_row_count": 7,
            "csv_file_count": 2,
            "warnings": [],
        }

        class VectorStore:
            def __init__(self, name):
                self.name = name

            def create(self, **kwargs):
                raise AssertionError("existing Ready store must not be created again")

            def status(self):
                return "Ready"

        def execute_sql(sql):
            if '"demo_vs_unstructured"' in sql or '"vectorstore_demo_vs_index"' in sql:
                return _DummyCursor((7,))
            raise AssertionError(f"Unexpected SQL: {sql}")

        form_data = {
            "multi_format_loaded_csv_run_id": csv_run_id,
            "doc_pipeline_mode": "multi_format",
            "embeddings_model": "text-embedding-3-small",
            "search_algorithm": "VECTORDISTANCE",
            "create_mode": "core",
            "create_preset": "auto",
        }
        with patch(
            "app.workflows.create_flow.get_ready_multi_format_csv_load_summary",
            return_value=load_summary,
        ), patch(
            "app.services.doc_modes.multi_format_mode.update_multi_format_csv_vector_store_status",
            side_effect=lambda **kwargs: status_calls.append(kwargs),
        ):
            response = await handle_upload_and_prepare_create(
                _DummyRequest(form_data),
                self._build_app(),
                _DummyTemplates(),
                vector_store_cls=VectorStore,
                execute_sql_fn=execute_sql,
                save_document_uploads_fn=self._save_document_uploads,
                collect_upload_files_fn=lambda form, field_name="files": [],
                resolve_path_hint_fn=lambda value: value,
                now_ts=lambda: "2026-07-16 00:00:00",
                is_htmx=True,
                is_vectorstore_already_exists_error_fn=lambda value: False,
                verify_vectorstore_exists_fn=lambda *args, **kwargs: (True, "found", ""),
                append_connect_step=lambda *args, **kwargs: None,
            )

        result = response["context"]["create_result"]
        self.assertEqual(result["status"], "ok_with_warnings")
        self.assertIn("Multi-Format vector index rows", result["status_output_preview"])
        self.assertEqual([call["status"] for call in status_calls], ["ready"])


if __name__ == "__main__":
    unittest.main()
