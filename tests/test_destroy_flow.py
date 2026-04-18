from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.workflows.destroy_flow import handle_destroy_selected


class _DummyRequest:
    pass


class DestroyFlowTests(unittest.IsolatedAsyncioTestCase):
    def _base_state(self, row: list[str]) -> dict:
        return {
            "connected": True,
            "selected_vs_name": "demo_vs",
            "destroy_status": "neutral",
            "destroy_preview": "",
            "last_error": "",
            "last_success": "",
            "params": {"username": "USECASES_JAPAN"},
            "list_columns": ["#", "vs_name", "store_type", "description", "database_name", "vs_status"],
            "list_rows": [row],
        }

    async def test_bookrag_destroy_drops_vs_before_bookrag_objects(self):
        actions: list[str] = []
        state = self._base_state(["1", "demo_vs", "file-based", "demo unstructured_bookrag_flg", "USECASES_JAPAN", "READY"])

        class _VectorStore:
            def __init__(self, name):
                self.name = name

            def destroy(self):
                actions.append("vs_destroy")
                return None

        vs_manager = SimpleNamespace(list=lambda: [])

        def execute_sql(sql: str):
            actions.append(sql)

        await handle_destroy_selected(
            _DummyRequest(),
            state,
            "demo_vs",
            vector_store_cls=_VectorStore,
            vs_manager=vs_manager,
            execute_sql_fn=execute_sql,
            teradata_import_error="",
            render_connect_panel=lambda request: {"state": state},
            append_connect_step=lambda *args, **kwargs: None,
        )

        self.assertEqual(actions[0], "vs_destroy")
        self.assertIn('DROP VIEW "USECASES_JAPAN"."demo_vs_bk_bleaf"', actions)
        self.assertIn('DROP TABLE "USECASES_JAPAN"."demo_vs_bk_bnode"', actions)
        self.assertIn('DROP TABLE "USECASES_JAPAN"."demo_vs_bk_brel"', actions)
        self.assertEqual(state["destroy_status"], "ok")

    async def test_non_bookrag_destroy_skips_bookrag_cleanup(self):
        actions: list[str] = []
        state = self._base_state(["1", "demo_vs", "file-based", "plain description", "USECASES_JAPAN", "READY"])

        class _VectorStore:
            def __init__(self, name):
                self.name = name

            def destroy(self):
                actions.append("vs_destroy")
                return None

        vs_manager = SimpleNamespace(list=lambda: [])

        def execute_sql(sql: str):
            actions.append(sql)

        await handle_destroy_selected(
            _DummyRequest(),
            state,
            "demo_vs",
            vector_store_cls=_VectorStore,
            vs_manager=vs_manager,
            execute_sql_fn=execute_sql,
            teradata_import_error="",
            render_connect_panel=lambda request: {"state": state},
            append_connect_step=lambda *args, **kwargs: None,
        )

        self.assertEqual(actions, ["vs_destroy"])
        self.assertEqual(state["destroy_status"], "ok")


if __name__ == "__main__":
    unittest.main()
