from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.workflows.create_flow import handle_upload_and_prepare_create


class _DummyRequest:
    def __init__(self, form_data):
        self._form_data = form_data

    async def form(self):
        return self._form_data


class _DummyTemplates:
    def TemplateResponse(self, request, template_name, context):
        return {"template": template_name, "context": context}


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


if __name__ == "__main__":
    unittest.main()
