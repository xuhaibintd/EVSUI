from __future__ import annotations

from fastapi import Form, Request
from fastapi.responses import HTMLResponse

from app.utils.table_state import (
    apply_list_output_to_state,
    chunk_table_sql_for_vs,
    destroy_output_indicates_failure,
    find_list_row_for_vs,
    find_vs_row_by_name,
    format_preview,
    is_content_based_vs_row,
    row_value_by_header,
    table_from_result,
)


async def handle_destroy_selected(
    request: Request,
    state: dict,
    vs_name: str,
    *,
    vector_store_cls,
    vs_manager,
    execute_sql_fn,
    teradata_import_error: str,
    render_connect_panel,
    append_connect_step,
):
    target_name = vs_name.strip() or str(state.get("selected_vs_name", "")).strip()
    state["selected_vs_name"] = target_name
    list_headers, selected_row = find_list_row_for_vs(state, target_name)
    should_drop_chunk_table = is_content_based_vs_row(list_headers, selected_row)
    chunk_schema_name, chunk_table_name, chunk_table_sql = chunk_table_sql_for_vs(
        list_headers,
        selected_row,
        target_name,
        state,
    )

    if not state["connected"]:
        state["destroy_status"] = "warn"
        state["destroy_preview"] = "Connect in Step 1 first."
        state["last_error"] = "Destroy blocked: connection is not established."
        append_connect_step(state, "VectorStore.destroy()", "warn", "Blocked: Step 1 is not connected.")
        return render_connect_panel(request)

    if not target_name:
        state["destroy_status"] = "warn"
        state["destroy_preview"] = "Select a vector store row first."
        state["last_error"] = "Destroy blocked: no vector store selected."
        append_connect_step(state, "VectorStore.destroy()", "warn", "Blocked: no vector store selected.")
        return render_connect_panel(request)

    if vector_store_cls is None:
        state["destroy_status"] = "err"
        state["destroy_preview"] = f"Cannot run destroy: {teradata_import_error}"
        state["last_error"] = "VectorStore runtime is unavailable."
        append_connect_step(state, "VectorStore.destroy()", "error", f"Runtime unavailable: {teradata_import_error}")
        return render_connect_panel(request)

    try:
        vector_store = vector_store_cls(target_name)
        destroy_fn = getattr(vector_store, "destroy", None)
        if not callable(destroy_fn):
            raise RuntimeError("VectorStore.destroy() is not callable.")

        destroy_output = destroy_fn()
        output_preview = format_preview(destroy_output, max_chars=500)
        destroy_output_failed = destroy_output_indicates_failure(output_preview)
        chunk_drop_note = ""

        post_check_failed = False
        post_check_note = ""
        list_fn = getattr(vs_manager, "list", None) if vs_manager is not None else None
        if callable(list_fn):
            try:
                list_output = list_fn()
                headers_all, rows_all = table_from_result(list_output)
                row_after = find_vs_row_by_name(headers_all, rows_all, target_name)
                status_after = row_value_by_header(
                    headers_all,
                    row_after or [],
                    ("status", "state", "lifecycle", "vsstatus"),
                )
                status_after_low = status_after.lower()
                if row_after is None:
                    post_check_note = "Post-check: target not present in VSManager.list()."
                elif any(marker in status_after_low for marker in ("deleted", "destroyed", "dropped", "removed")):
                    post_check_note = f"Post-check: target has terminal status '{status_after}'."
                else:
                    post_check_failed = True
                    post_check_note = f"Post-check failed: target still listed with status '{status_after or 'unknown'}'."
                visible_rows, _total_rows, _username_filter = apply_list_output_to_state(
                    state,
                    list_output,
                    sync_chat_options=False,
                )
                append_connect_step(
                    state,
                    "VSManager.list()",
                    "warn" if post_check_failed else "ok",
                    f"Step 1 list refreshed after destroy. rows={visible_rows}. {post_check_note}",
                )
            except Exception as list_ex:
                post_check_failed = True
                post_check_note = f"Post-check failed: Step 1 list refresh failed: {list_ex}"
                append_connect_step(state, "VSManager.list()", "warn", post_check_note)
        else:
            post_check_note = "Post-check skipped: VSManager.list() unavailable."
            append_connect_step(state, "VSManager.list()", "warn", post_check_note)

        destroy_failed = destroy_output_failed or post_check_failed
        if destroy_failed:
            reason_parts: list[str] = []
            if destroy_output_failed:
                reason_parts.append(f"destroy output indicates failure: {output_preview}")
            if post_check_note:
                reason_parts.append(post_check_note)
            reason = " ".join(reason_parts).strip() or "destroy did not pass verification."
            state["destroy_status"] = "err"
            state["destroy_preview"] = f"Delete failed for '{target_name}': {reason}{chunk_drop_note}"
            state["last_error"] = f"VectorStore.destroy() failed for '{target_name}': {reason}"
            state["last_success"] = ""
            append_connect_step(state, "VectorStore.destroy()", "error", f"Verification failed: {reason}")
        else:
            if should_drop_chunk_table:
                if execute_sql_fn is None:
                    chunk_drop_note = f" Chunk table cleanup skipped: execute_sql unavailable for {chunk_table_sql}."
                    append_connect_step(
                        state,
                        "Chunk table cleanup",
                        "warn",
                        f"Skipped (execute_sql unavailable): {chunk_table_sql}",
                    )
                else:
                    try:
                        execute_sql_fn(f"DROP TABLE {chunk_table_sql}")
                        chunk_drop_note = f" Removed chunk table {chunk_table_sql}."
                        append_connect_step(
                            state,
                            "Chunk table cleanup",
                            "ok",
                            f"Dropped content-based chunk table {chunk_table_sql}.",
                        )
                    except Exception as drop_ex:
                        drop_msg = str(drop_ex).lower()
                        if "3807" in drop_msg or "does not exist" in drop_msg or "not found" in drop_msg:
                            chunk_drop_note = f" Chunk table {chunk_table_sql} not found (already removed)."
                            append_connect_step(
                                state,
                                "Chunk table cleanup",
                                "warn",
                                f"Chunk table already absent: {chunk_table_sql}.",
                            )
                        else:
                            chunk_drop_note = f" Chunk table cleanup failed for {chunk_table_sql}: {drop_ex}"
                            append_connect_step(
                                state,
                                "Chunk table cleanup",
                                "warn",
                                f"Failed to drop chunk table {chunk_table_sql}: {drop_ex}",
                            )
            if output_preview and output_preview != "None":
                state["destroy_preview"] = f"Deleted '{target_name}'. Result: {output_preview}{chunk_drop_note}"
            else:
                state["destroy_preview"] = f"Deleted '{target_name}'.{chunk_drop_note}"
            state["destroy_status"] = "ok"
            state["last_error"] = ""
            state["last_success"] = f"VectorStore.destroy() completed for '{target_name}'.{chunk_drop_note}"
            if should_drop_chunk_table:
                append_connect_step(
                    state,
                    "VectorStore.destroy()",
                    "ok",
                    (
                        f"Destroyed vector store '{target_name}'. "
                        f"Chunk table target: {chunk_table_sql} (schema='{chunk_schema_name or '<default>'}', table='{chunk_table_name}')."
                    ),
                )
            else:
                append_connect_step(state, "VectorStore.destroy()", "ok", f"Destroyed vector store '{target_name}'.")
            state["selected_vs_name"] = ""
    except Exception as ex:
        state["destroy_status"] = "err"
        state["destroy_preview"] = f"Delete failed for '{target_name}': {ex}"
        state["last_error"] = f"VectorStore.destroy() failed for '{target_name}': {ex}"
        append_connect_step(state, "VectorStore.destroy()", "error", f"Execution failed: {ex}")

    return render_connect_panel(request)
