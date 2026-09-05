from __future__ import annotations

import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.db.migrations import migrate_database
from app.db.sqlite import SQLiteDatabase
from app.repositories.job_repository import JobRepository
from app.services import workflow_jobs
from app.services import multi_format
from app.services.credential_vault import CredentialVault
from app.services.doc_modes import multi_format_bookrag_mode, multi_format_mode
from app.services.job_worker import PersistentJobWorker
from app.main import create_app


class DurableWorkflowRegressionTests(unittest.TestCase):
    @contextmanager
    def database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            migrate_database(path)
            database = SQLiteDatabase(path)
            vault = CredentialVault(database_path=path, runtime_dir=Path(directory) / "pem")
            yield database, JobRepository(database, credential_vault=vault)

    def test_two_workers_cannot_claim_the_same_job(self):
        with self.database() as (_database, jobs):
            created = jobs.create(kind="work")
            with ThreadPoolExecutor(max_workers=2) as executor:
                claimed = list(executor.map(lambda _: jobs.claim_next(kinds={"work"}), range(2)))
            self.assertEqual([item["id"] for item in claimed if item], [created["id"]])

    def test_recovered_attempt_rejects_old_worker_heartbeat_success_and_failure(self):
        with self.database() as (database, jobs):
            job = jobs.create(kind="work")
            original = jobs.claim_next(kinds={"work"})
            with database.connect() as connection:
                connection.execute("UPDATE jobs SET heartbeat_at=0, progress=80 WHERE id=?", (job["id"],))
            self.assertEqual(jobs.recover_stale(stale_before=int(time.time()) - 60), 1)
            self.assertEqual(jobs.get(job["id"])["progress"], 0)
            replacement = jobs.claim_next(kinds={"work"})
            self.assertEqual(replacement["attempt"], original["attempt"] + 1)
            self.assertFalse(jobs.heartbeat(job["id"], progress=90, expected_attempt=original["attempt"]))
            self.assertFalse(jobs.succeed(job["id"], {"old": True}, expected_attempt=original["attempt"]))
            self.assertFalse(jobs.fail(job["id"], "stale error", expected_attempt=original["attempt"]))
            self.assertEqual(jobs.get(job["id"])["status"], "running")
            self.assertTrue(jobs.succeed(job["id"], {"new": True}, expected_attempt=replacement["attempt"]))
            self.assertEqual(jobs.get(job["id"])["result"], {"new": True})

    def test_worker_without_handlers_leaves_queued_jobs_untouched(self):
        with self.database() as (_database, jobs):
            job = jobs.create(kind="unregistered")
            self.assertIsNone(PersistentJobWorker(jobs, handlers={}).run_once())
            self.assertEqual(jobs.get(job["id"])["status"], "queued")

    def test_unreadable_secret_does_not_crash_or_block_the_worker(self):
        with self.database() as (database, jobs):
            broken = jobs.create(kind="work", secret_payload={"api_key": "original-secret"})
            with database.connect() as connection:
                connection.execute(
                    "UPDATE jobs SET secret_payload_ciphertext='invalid-ciphertext', created_at=0 WHERE id=?",
                    (broken["id"],),
                )
            good = jobs.create(kind="work", payload={"valid": True})
            completed = PersistentJobWorker(jobs, handlers={"work": lambda payload, _: payload}).run_until_empty()
            self.assertEqual([job["status"] for job in completed], ["failed", "succeeded"])
            self.assertEqual(jobs.get(good["id"])["result"]["valid"], True)
            self.assertNotIn("ciphertext", jobs.get(broken["id"])["error"])

    def test_cancel_cannot_interrupt_a_running_job(self):
        with self.database() as (_database, jobs):
            job = jobs.create(kind="work")
            jobs.claim_next(kinds={"work"})
            self.assertFalse(jobs.cancel(job["id"]))
            self.assertEqual(jobs.get(job["id"])["status"], "running")

    def test_failed_file_summary_persists_as_failed_job_with_redacted_details(self):
        with self.database() as (_database, jobs), mock.patch.object(
            workflow_jobs, "run_bookrag_document_parsing",
            return_value={
                "status": "partial", "failure_count": 1, "success_count": 1,
                "files": [{"filename": "bad.pdf", "error": "rejected runtime-secret"}],
            },
        ):
            auth_store = SimpleNamespace(get_unstructured_config=lambda: {"api_key": "runtime-secret"})
            jobs.create(kind=workflow_jobs.BOOKRAG_PARSE_JOB)
            completed = PersistentJobWorker(jobs, workflow_jobs.build_workflow_job_handlers(auth_store)).run_once()
            self.assertEqual(completed["status"], "failed")
            self.assertEqual(completed["result"]["summary"]["failure_count"], 1)
            self.assertIn("bad.pdf", str(completed["result"]))
            self.assertNotIn("runtime-secret", str(completed))

    @contextmanager
    def create_environment(self, *, bookrag=False, existing=False, source_rows=3, index_rows=3):
        mode = multi_format_bookrag_mode if bookrag else multi_format_mode
        source_table = "demo_bnode" if bookrag else "demo_unstructured"
        summary = {
            "status": "ready", "csv_run_id": "loaded-run", "vector_store_name": "demo",
            "target_database": "fixture", "table_name": source_table,
            "node_table": f"fixture.{source_table}", "table_targets": {"nodes": source_table},
        }
        statements = []

        def sql(statement):
            statements.append(statement)
            return [[index_rows if "vectorstore_demo_index" in statement else source_rows]]

        @contextmanager
        def activated(_store, profile_id):
            self.assertEqual(profile_id, 8)
            yield {"execute_sql": sql, "profile": {
                "host": "fixture.invalid", "username": "fixture", "ues_url": "https://ues.invalid/open-analytics",
            }}

        vector_store = mock.Mock()
        vector_store.create.return_value = "submitted"
        vector_store.status.return_value = "Ready"
        loader = "get_ready_bookrag_csv_load_summary" if bookrag else "get_ready_multi_format_csv_load_summary"
        run_key = "bookrag_loaded_csv_run_id" if bookrag else "multi_format_loaded_csv_run_id"
        payload = {
            "vector_store_name": "demo", "doc_pipeline_mode": mode.MODE,
            "create_values": {run_key: "loaded-run"},
            "exec_payload": {"embeddings_model": "fixture-model", "document_files": ["obsolete.pdf"]},
            "_job": {"connection_profile_id": 8},
        }
        auth_store = SimpleNamespace(get_unstructured_config=lambda: {})
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(workflow_jobs, "activated_connection", side_effect=activated))
            stack.enter_context(mock.patch.object(workflow_jobs, "_vector_store_exists", return_value=existing))
            stack.enter_context(mock.patch.object(workflow_jobs, "VectorStore", return_value=vector_store))
            stack.enter_context(mock.patch.object(workflow_jobs, loader, return_value=summary))
            stack.enter_context(mock.patch.object(mode, loader, return_value=summary))
            preprocess = stack.enter_context(mock.patch.object(mode, "preprocess_create_payload", wraps=mode.preprocess_create_payload))
            mark = stack.enter_context(mock.patch.object(mode, "mark_vectorstore_status"))
            handler = workflow_jobs.build_workflow_job_handlers(auth_store)[workflow_jobs.VECTOR_STORE_CREATE_JOB]
            yield handler, payload, vector_store, preprocess, mark, statements

    def test_loaded_runs_create_from_verified_tables_and_display_actual_execution_payload(self):
        for bookrag in (False, True):
            with self.subTest(bookrag=bookrag), self.create_environment(bookrag=bookrag) as env:
                handler, payload, vector_store, _preprocess, mark, statements = env
                result = handler(payload, lambda _: None)["create_result"]
                arguments = vector_store.create.call_args.kwargs
                self.assertEqual(arguments["target_database"], "fixture")
                self.assertEqual(arguments["data_columns"], ["content"] if bookrag else ["text"])
                self.assertEqual(arguments["key_columns"], ["doc_id", "node_id"] if bookrag else ["id"])
                self.assertNotIn("document_files", arguments)
                self.assertEqual(result["status"], "ok")
                self.assertIn("vectorstore_demo_index=3", result["status_output_preview"])
                self.assertIn(arguments["object_names"], result["create_execute_payload_json"])
                self.assertEqual(len(statements), 2)
                self.assertEqual(mark.call_args.kwargs["status"], "ready")

    def test_ready_but_empty_incomplete_or_oversized_index_fails(self):
        for bookrag in (False, True):
            for index_rows in (0, 2, 4):
                with self.subTest(bookrag=bookrag, index_rows=index_rows), self.create_environment(
                    bookrag=bookrag, index_rows=index_rows,
                ) as env:
                    handler, payload, _vector_store, _preprocess, mark, _statements = env
                    with self.assertRaisesRegex(RuntimeError, "index"):
                        handler(payload, lambda _: None)
                    self.assertEqual(mark.call_args.kwargs["status"], "failed")

    def test_existing_store_reuse_skips_all_preprocessing_and_checks_index(self):
        for bookrag in (False, True):
            with self.subTest(bookrag=bookrag), self.create_environment(bookrag=bookrag, existing=True) as env:
                handler, payload, vector_store, preprocess, mark, statements = env
                result = handler(payload, lambda _: None)["create_result"]
                preprocess.assert_not_called()
                vector_store.create.assert_not_called()
                self.assertEqual(result["status"], "ok_with_warnings")
                self.assertEqual(len(statements), 2)
                self.assertEqual(mark.call_args.kwargs["status"], "ready")

    def test_existing_failed_store_does_not_reload_its_source_tables(self):
        with self.create_environment(existing=True) as env:
            handler, payload, vector_store, preprocess, mark, _statements = env
            vector_store.status.return_value = "Failed"
            with self.assertRaisesRegex(RuntimeError, "failed"):
                handler(payload, lambda _: None)
            preprocess.assert_not_called()
            vector_store.create.assert_not_called()
            self.assertEqual(mark.call_args.kwargs["status"], "failed")

    def test_monitoring_timeout_keeps_remote_operation_processing(self):
        with self.create_environment() as env, mock.patch.object(
            workflow_jobs, "_wait_for_ready", return_value=("pending", "Creating", "deadline reached"),
        ):
            handler, payload, _vector_store, _preprocess, mark, _statements = env
            result = handler(payload, lambda _: None)["create_result"]
            self.assertEqual(result["status"], "pending")
            self.assertIn("not cancelled", result["message"])
            self.assertEqual(mark.call_args.kwargs["status"], "creating")

    def test_non_vector_table_exists_error_is_not_mistaken_for_success(self):
        with self.create_environment() as env:
            handler, payload, vector_store, _preprocess, mark, _statements = env
            vector_store.create.side_effect = RuntimeError("Source table already exists")
            with self.assertRaisesRegex(RuntimeError, "Source table"):
                handler(payload, lambda _: None)
            self.assertEqual(mark.call_args.kwargs["status"], "failed")

    def test_existence_probe_matches_exact_names_in_nested_list_payloads(self):
        manager = SimpleNamespace(list=lambda **_: {"items": [{"vector_store_name": "demo_one"}]})
        with mock.patch.object(workflow_jobs, "VSManager", manager):
            self.assertTrue(workflow_jobs._vector_store_exists("demo_one"))
            self.assertFalse(workflow_jobs._vector_store_exists("demoone"))

    def test_existence_probe_never_treats_error_or_unknown_json_as_absence(self):
        for output in ({"error": "unavailable"}, {"message": "maintenance"}, {"response_code": 500, "items": []}, {}, ["invalid response"]):
            with self.subTest(output=output), mock.patch.object(
                workflow_jobs, "VSManager", SimpleNamespace(list=lambda **_: output),
            ), mock.patch.object(workflow_jobs, "VectorStore", return_value=SimpleNamespace(status=lambda: "Unknown")):
                with self.assertRaisesRegex(RuntimeError, "Cannot verify"):
                    workflow_jobs._vector_store_exists("demo")
        for output in ([], {"items": []}, {"data": {"vector_stores": []}}):
            with self.subTest(valid_empty=output), mock.patch.object(
                workflow_jobs, "VSManager", SimpleNamespace(list=lambda **_: output),
            ):
                self.assertFalse(workflow_jobs._vector_store_exists("demo"))

    def test_interrupted_csv_load_never_mutates_tables_automatically(self):
        for bookrag in (False, True):
            with self.subTest(bookrag=bookrag):
                resolver = "_resolve_bookrag_csv_manifest" if bookrag else "_resolve_multi_format_csv_manifest"
                load = multi_format.run_bookrag_csv_load if bookrag else multi_format.run_multi_format_csv_load
                manifest = {
                    "status": "ready", "load_status": "loading",
                    "complete_table_contract": multi_format.BOOKRAG_COMPLETE_TABLE_CONTRACT,
                }
                sql = mock.Mock()
                with mock.patch.object(multi_format, resolver, return_value=(Path("never-written.json"), manifest)):
                    with self.assertRaisesRegex(RuntimeError, "inspect the target table"):
                        load(csv_run_id="interrupted-run", execute_sql_fn=sql)
                sql.assert_not_called()
                self.assertEqual(manifest["load_status"], "loading")

    def test_loaded_run_cannot_reuse_success_from_another_database_or_unbound_legacy_load(self):
        for bookrag in (False, True):
            for profile_id in (7, None):
                with self.subTest(bookrag=bookrag, stored_profile=profile_id):
                    resolver = "_resolve_bookrag_csv_manifest" if bookrag else "_resolve_multi_format_csv_manifest"
                    load = multi_format.run_bookrag_csv_load if bookrag else multi_format.run_multi_format_csv_load
                    ready = multi_format.get_ready_bookrag_csv_load_summary if bookrag else multi_format.get_ready_multi_format_csv_load_summary
                    manifest = {
                        "status": "ready", "load_status": "ready", "connection_profile_id": profile_id,
                        "connection_target_fingerprint": "original-target" if profile_id is not None else None,
                        "complete_table_contract": multi_format.BOOKRAG_COMPLETE_TABLE_CONTRACT,
                        "load_summary": {"status": "ready", "vector_store_name": "demo", "target_database": "fixture", "node_table": "fixture.demo_bnode"},
                    }
                    sql = mock.Mock()
                    with mock.patch.object(multi_format, resolver, return_value=(Path("never-written.json"), manifest)):
                        with self.assertRaisesRegex(RuntimeError, "connection"):
                            load(csv_run_id="bound-run", execute_sql_fn=sql, connection_profile_id=8, connection_target_fingerprint="original-target")
                        with self.assertRaisesRegex(RuntimeError, "connection"):
                            ready(csv_run_id="bound-run", connection_profile_id=8, connection_target_fingerprint="original-target")
                        if profile_id is not None:
                            self.assertTrue(load(csv_run_id="bound-run", execute_sql_fn=sql, connection_profile_id=7, connection_target_fingerprint="original-target")["already_loaded"])
                            self.assertTrue(ready(csv_run_id="bound-run", connection_profile_id=7, connection_target_fingerprint="original-target")["already_loaded"])
                    sql.assert_not_called()

    def test_same_profile_target_edit_rejects_cached_load_but_credential_rotation_reuses_it(self):
        original = {
            "host": "database-a.invalid", "username": "fixture", "ues_url": "https://ues.invalid/account-a/open-analytics",
            "password": "old-password", "pat_token": "old-token", "pem_file": "old.pem",
        }
        target = workflow_jobs._connection_target_fingerprint(original)
        rotated = {**original, "password": "new-password", "pat_token": "new-token", "pem_file": "new.pem"}
        self.assertEqual(workflow_jobs._connection_target_fingerprint(rotated), target)
        for bookrag in (False, True):
            resolver = "_resolve_bookrag_csv_manifest" if bookrag else "_resolve_multi_format_csv_manifest"
            load = multi_format.run_bookrag_csv_load if bookrag else multi_format.run_multi_format_csv_load
            ready = multi_format.get_ready_bookrag_csv_load_summary if bookrag else multi_format.get_ready_multi_format_csv_load_summary
            mode = "multi_format_bookrag" if bookrag else "multi_format"
            run_key = "bookrag_loaded_csv_run_id" if bookrag else "multi_format_loaded_csv_run_id"
            manifest = {
                "status": "ready", "load_status": "ready", "connection_profile_id": 7,
                "connection_target_fingerprint": target,
                "complete_table_contract": multi_format.BOOKRAG_COMPLETE_TABLE_CONTRACT,
                "load_summary": {"status": "ready", "vector_store_name": "demo", "target_database": "fixture", "node_table": "fixture.demo_bnode"},
            }
            sql = mock.Mock()
            with mock.patch.object(multi_format, resolver, return_value=(Path("never-written.json"), manifest)):
                self.assertTrue(load(
                    csv_run_id="bound-run", execute_sql_fn=sql, connection_profile_id=7,
                    connection_target_fingerprint=workflow_jobs._connection_target_fingerprint(rotated),
                )["already_loaded"])
                for field, value in (
                    ("host", "database-b.invalid"), ("username", "other-user"),
                    ("ues_url", "https://ues.invalid/account-b/open-analytics"),
                ):
                    with self.subTest(bookrag=bookrag, changed_field=field):
                        changed_target = workflow_jobs._connection_target_fingerprint({**original, field: value})
                        with self.assertRaisesRegex(RuntimeError, "different target"):
                            load(csv_run_id="bound-run", execute_sql_fn=sql, connection_profile_id=7, connection_target_fingerprint=changed_target)
                        with self.assertRaisesRegex(RuntimeError, "different target"):
                            ready(csv_run_id="bound-run", connection_profile_id=7, connection_target_fingerprint=changed_target)
                        with self.assertRaisesRegex(RuntimeError, "different target"):
                            workflow_jobs._loaded_run_summary({run_key: "bound-run"}, mode, "demo", 7, changed_target)
                manifest["connection_target_fingerprint"] = ""
                with self.assertRaisesRegex(RuntimeError, "legacy"):
                    ready(csv_run_id="bound-run", connection_profile_id=7, connection_target_fingerprint=target)
            sql.assert_not_called()

    def test_parser_redacts_provider_errors_before_writing_manifest(self):
        for bookrag in (False, True):
            with self.subTest(bookrag=bookrag), tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                source = root / "source.txt"
                source.write_text("Fixture document", encoding="utf-8")
                raw_dir = root / "raw"
                stage = "_prepare_bookrag_raw_stage_dir" if bookrag else "_prepare_multi_format_raw_stage_dir"
                parse = multi_format.run_bookrag_document_parsing if bookrag else multi_format.run_multi_format_document_parsing
                patches = {
                    stage: {"return_value": raw_dir},
                    "_load_unstructured_runtime_config": {"return_value": ("api-secret", "https://example.invalid")},
                    "_create_unstructured_client": {"return_value": object()},
                    "_load_unstructured_runtime_settings": {"return_value": {}},
                    "_enforce_unstructured_job_submission_spacing": {"side_effect": lambda value: value},
                    "_resolve_bookrag_image_partition_options": {"return_value": ({}, [], {})},
                    "_build_bookrag_reusable_workflow_definition": {"return_value": ("Fixture", [], {}, [], "fast")},
                    "_workflow_builder_build_multi_format_workflow_definition": {"return_value": ({}, [], "fast")},
                    "_run_unstructured_workflow_job_for_file": {"side_effect": RuntimeError("Rejected api-secret and provider-secret")},
                }
                for name, kwargs in patches.items():
                    stack.enter_context(mock.patch.object(multi_format, name, **kwargs))
                summary = parse(
                    create_values={"multi_format_bookrag_vlm_provider_api_key": "provider-secret"},
                    vector_store_name="fixture",
                    uploaded_documents=[{"saved_path": str(source), "doc_id": "fixture-doc"}],
                    connection_params={}, resolve_path_hint=lambda value: value,
                )
                self.assertEqual(summary["failure_count"], 1)
                manifest_text = Path(summary["manifest_path"]).read_text(encoding="utf-8")
                self.assertNotIn("api-secret", manifest_text)
                self.assertNotIn("provider-secret", manifest_text)
                self.assertIn("[REDACTED]", manifest_text)


class WorkflowJobHttpRegressionTests(unittest.TestCase):
    @contextmanager
    def application(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict("os.environ", {
            "EVSUI_ENVIRONMENT": "test", "EVSUI_EXTERNAL_API_ENABLED": "false",
            "EVSUI_DATABASE_PATH": str(Path(directory) / "app.db"),
            "EVSUI_CREDENTIAL_KEY_FILE": str(Path(directory) / "credentials.key"),
        }):
            app = create_app(Settings.from_env(project_dir=Path(directory)))
            owner = app.state.auth_store.create_user(username="owner", password="fixture-password", role="operator")
            viewer = app.state.auth_store.create_user(username="viewer", password="fixture-password", role="viewer")
            admin = app.state.auth_store.create_user(username="administrator", password="fixture-password", role="admin")
            sessions = {person.role: app.state.auth_store.create_session(person) for person in (owner, viewer, admin)}
            with TestClient(app) as client:
                client.cookies.set("evsui_sid", sessions["operator"])
                yield app, client, owner, viewer, sessions

    def test_every_completed_workflow_renders_and_exposes_its_correct_next_action(self):
        summary = {
            "status": "ready", "parse_run_id": "raw-fixture", "csv_run_id": "csv-fixture",
            "vector_store_name": "fixture-store", "target_database": "fixture-db",
            "file_count": 1, "success_count": 1, "failure_count": 0, "workers": 1,
            "elapsed_seconds": 0.1, "files": [], "warnings": [], "csv_files_created": 1,
            "csv_file_count": 1, "row_count": 3, "run_csv_files": [], "run_error": "",
            "task_count": 1, "inserted_rows": 3, "node_table": "fixture-db.fixture_bnode",
            "qualified_table": "fixture-db.fixture_unstructured",
        }
        cases = [
            (workflow_jobs.BOOKRAG_PARSE_JOB, "/ui/create/generate-csv", False),
            (workflow_jobs.MULTI_FORMAT_PARSE_JOB, "/ui/create/multi-format/generate-csv", False),
            (workflow_jobs.BOOKRAG_CSV_GENERATE_JOB, "/ui/create/load-csv-tables", True),
            (workflow_jobs.MULTI_FORMAT_CSV_GENERATE_JOB, "/ui/create/multi-format/load-csv-table", True),
            (workflow_jobs.BOOKRAG_CSV_LOAD_JOB, "bookrag_loaded_csv_run_id", True),
            (workflow_jobs.MULTI_FORMAT_CSV_LOAD_JOB, "multi_format_loaded_csv_run_id", True),
            (workflow_jobs.VECTOR_STORE_CREATE_JOB, "Completed fixture creation", False),
        ]
        with self.application() as (app, client, owner, _viewer, _sessions):
            for kind, marker, expect_oob in cases:
                with self.subTest(kind=kind):
                    job = app.state.job_repository.create(kind=kind, owner_user_id=owner.user_id)
                    result = {"summary": summary}
                    if kind == workflow_jobs.VECTOR_STORE_CREATE_JOB:
                        result = {"create_result": {
                            "status": "ok", "message": "Completed fixture creation", "vector_store_name": "fixture-store",
                            "uploaded_files": [], "warnings": [], "create_payload_json": "{}",
                            "create_execute_payload_json": "{}", "multi_format_summary": None,
                        }}
                    worker = PersistentJobWorker(app.state.job_repository, {kind: lambda _payload, _heartbeat: result})
                    self.assertEqual(worker.run_once()["status"], "succeeded")
                    response = client.get(f"/ui/jobs/{job['id']}", headers={"HX-Request": "true"})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertIn(marker, response.text)
                    self.assertNotIn("hx-trigger=", response.text)
                    if expect_oob:
                        self.assertIn('hx-swap-oob="outerHTML"', response.text)

    def test_only_owner_or_admin_can_read_jobs_and_viewer_cannot_cancel(self):
        with self.application() as (app, client, owner, viewer, sessions):
            owned = app.state.job_repository.create(kind=workflow_jobs.BOOKRAG_PARSE_JOB, owner_user_id=owner.user_id)
            viewer_owned = app.state.job_repository.create(kind=workflow_jobs.BOOKRAG_PARSE_JOB, owner_user_id=viewer.user_id)
            client.cookies.set("evsui_sid", sessions["viewer"])
            self.assertEqual(client.get(f"/ui/jobs/{owned['id']}").status_code, 404)
            self.assertEqual(client.post(f"/ui/jobs/{owned['id']}/cancel").status_code, 404)
            self.assertEqual(client.get(f"/ui/jobs/{viewer_owned['id']}").status_code, 200)
            self.assertEqual(client.post(f"/ui/jobs/{viewer_owned['id']}/cancel").status_code, 403)
            self.assertEqual(app.state.job_repository.get(viewer_owned["id"])["status"], "queued")
            client.cookies.set("evsui_sid", sessions["admin"])
            self.assertEqual(client.get(f"/ui/jobs/{owned['id']}").status_code, 200)
            self.assertEqual(client.post(f"/ui/jobs/{owned['id']}/cancel").status_code, 200)
            self.assertEqual(app.state.job_repository.get(owned["id"])["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
