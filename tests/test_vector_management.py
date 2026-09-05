from __future__ import annotations

import unittest
from enum import Enum

from app.services.vector_management import (
    disconnect_sessions,
    empty_management_state,
    load_resource_details,
    load_sessions,
    remove_resource,
    refresh_management,
    select_resource,
)
from app.utils.table_state import format_preview, table_from_result


class FileType(Enum):
    FILE_CONTENT_BASED = "FILE-CONTENT-BASED"


class VectorManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.auth_data = object()
        self.calls: list[tuple] = []
        calls = self.calls
        auth_data = self.auth_data

        class V1Manager:
            def __init__(manager_self, auth_data=None):
                calls.append(("v1_init", auth_data))

            def health(manager_self, **kwargs):
                return {"status": "ok"}

            def list(manager_self, **kwargs):
                return [{
                    "vs_name": "legacy_docs",
                    "store_type": "CONTENT-BASED",
                    "vs_status": "READY",
                    "username": "alice",
                    "database_name": "analytics",
                }]

            def list_sessions(manager_self, **kwargs):
                return {"session_details": [{"username": "legacy", "session_id": "v1-1"}]}

        class V1Store:
            def __init__(store_self, name=None, auth_data=None):
                calls.append(("v1_store_init", name, auth_data))

            def get_details(store_self, **kwargs):
                return {"description": "BookRAG documents unstructured_bookrag_flg"}

        class V2Manager:
            def __init__(manager_self, auth_data=None):
                calls.append(("v2_init", auth_data))

            def health(manager_self, **kwargs):
                return {"status": "healthy"}

            def list(manager_self, **kwargs):
                return {"collection_list": [{
                    "collection_name": "file_docs",
                    "collection_type": "FILE-CONTENT-BASED",
                    "status": "READY",
                    "owner": "bob",
                    "target_database": "knowledge",
                }]}

            def list_sessions(manager_self, **kwargs):
                return {"session_details": [{
                    "username": "bob", "session_id": "v2-1", "status": "active",
                }]}

            def disconnect(manager_self, user_names=None):
                calls.append(("disconnect", user_names))

        class Collection:
            def __init__(collection_self, name=None, auth_data=None):
                calls.append(("collection_init", name, auth_data))

            def get_details(collection_self, **kwargs):
                return {"collection_name": "file_docs", "description": "documents"}

            def status(collection_self, **kwargs):
                return {"status": "READY"}

            def list_user_permissions(collection_self, **kwargs):
                return [{"username": "bob", "permission": "ADMIN"}]

        class Ingestor:
            def __init__(ingestor_self, name=None, type=None, auth_data=None):
                calls.append(("ingestor_init", name, type, auth_data))

            def get_file_store(ingestor_self, **kwargs):
                return [{"filename": "guide.pdf", "status": "processed"}]

        self.V1Manager = V1Manager
        self.V1Store = V1Store
        self.V2Manager = V2Manager
        self.Collection = Collection
        self.Ingestor = Ingestor

    def test_refresh_only_shows_resources_for_active_database_connection(self):
        state = empty_management_state()
        refresh_management(
            state,
            auth_data=self.auth_data,
            vs_manager_class=self.V1Manager,
            collection_manager_class=self.V2Manager,
            connection_username="alice",
            table_from_result=table_from_result,
            format_preview=format_preview,
            now=lambda: "2026-09-05 12:00:00",
            vector_store_class=self.V1Store,
        )

        self.assertEqual(state["management_health"], "Healthy")
        self.assertEqual(state["management_checked_at"], "2026-09-05 12:00:00")
        self.assertEqual(
            state["resource_rows"],
            [[
                "legacy_docs",
                "BookRAG documents unstructured_bookrag_flg",
                "CONTENT-BASED",
                "READY",
                "analytics",
                "alice",
            ]],
        )
        self.assertIn(("v1_init", self.auth_data), self.calls)
        self.assertIn(("v1_store_init", "legacy_docs", self.auth_data), self.calls)
        self.assertIn(("v2_init", self.auth_data), self.calls)

    def test_selection_is_state_only_and_does_not_initialize_sdk_resource(self):
        state = empty_management_state()
        state["resource_records"] = [{
            "kind": "v2", "name": "file_docs", "type": "FILE-CONTENT-BASED",
        }]
        calls_before = list(self.calls)

        selected = select_resource(state, kind="v2", name="file_docs")

        self.assertTrue(selected)
        self.assertEqual(state["selected_resource_name"], "file_docs")
        self.assertEqual(self.calls, calls_before)

    def test_missing_resource_values_remain_empty(self):
        class Manager:
            @staticmethod
            def health(**kwargs):
                return {"status": "ok"}

            @staticmethod
            def list(**kwargs):
                return [{"vs_name": "empty_docs", "database_name": "alice"}]

        class Store:
            def __init__(store_self, name=None, auth_data=None):
                pass

            def get_details(store_self, **kwargs):
                return {"description": ""}

        state = empty_management_state()
        refresh_management(
            state,
            auth_data=self.auth_data,
            vs_manager_class=Manager,
            collection_manager_class=None,
            connection_username="alice",
            table_from_result=table_from_result,
            format_preview=format_preview,
            now=lambda: "now",
            vector_store_class=Store,
        )

        self.assertEqual(
            state["resource_rows"],
            [["empty_docs", "", "", "", "alice", ""]],
        )

        remove_resource(state, kind="missing-kind", name="missing-name")
        self.assertEqual(
            state["resource_rows"],
            [["empty_docs", "", "", "", "alice", ""]],
        )

    def test_description_detail_failure_leaves_cell_empty_and_adds_warning(self):
        class Manager:
            @staticmethod
            def health(**kwargs):
                return {"status": "ok"}

            @staticmethod
            def list(**kwargs):
                return [{"vs_name": "private_docs", "database_name": "alice"}]

        class Store:
            def __init__(store_self, name=None, auth_data=None):
                pass

            def get_details(store_self, **kwargs):
                raise PermissionError("not authorized")

        state = empty_management_state()
        refresh_management(
            state,
            auth_data=self.auth_data,
            vs_manager_class=Manager,
            collection_manager_class=None,
            connection_username="alice",
            table_from_result=table_from_result,
            format_preview=format_preview,
            now=lambda: "now",
            vector_store_class=Store,
        )

        self.assertEqual(state["resource_records"][0]["description"], "")
        self.assertTrue(any("private_docs" in warning for warning in state["management_warnings"]))

    def test_v2_details_include_status_files_and_admin_permissions(self):
        state = empty_management_state()
        state["resource_records"] = [{
            "kind": "v2", "name": "file_docs", "type": "FILE-CONTENT-BASED",
        }]
        load_resource_details(
            state,
            kind="v2",
            name="file_docs",
            role="admin",
            auth_data=self.auth_data,
            vector_store_class=None,
            collection_class=self.Collection,
            ingestor_class=self.Ingestor,
            collection_type_class=FileType,
            table_from_result=table_from_result,
            format_preview=format_preview,
        )

        self.assertTrue(state["resource_detail_rows"])
        self.assertTrue(state["resource_status_rows"])
        self.assertTrue(state["resource_file_rows"])
        self.assertTrue(state["resource_permission_rows"])
        self.assertIn(("collection_init", "file_docs", self.auth_data), self.calls)
        self.assertIn(("ingestor_init", "file_docs", FileType.FILE_CONTENT_BASED, self.auth_data), self.calls)

    def test_sessions_use_v2_and_disconnect_by_distinct_username(self):
        state = empty_management_state()
        load_sessions(
            state,
            auth_data=self.auth_data,
            vs_manager_class=self.V1Manager,
            collection_manager_class=self.V2Manager,
            format_preview=format_preview,
            now=lambda: "now",
        )
        disconnect_sessions(
            usernames=["bob", "bob", ""],
            auth_data=self.auth_data,
            collection_manager_class=self.V2Manager,
        )

        self.assertEqual(state["session_rows"][0][1:3], ["bob", "v2-1"])
        self.assertIn(("disconnect", ["bob"]), self.calls)


if __name__ == "__main__":
    unittest.main()
