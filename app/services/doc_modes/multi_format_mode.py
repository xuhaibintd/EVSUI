from __future__ import annotations

from app.services.doc_modes.messages import append_multi_format_summary
from app.services.multi_format import (
    apply_multi_format_pipeline,
    get_ready_multi_format_csv_load_summary,
    strip_file_based_create_params,
)

MODE = "multi_format"
LABEL = "Multi-Format"
SKIP_VECTORSTORE_CREATE = False


def preprocess_create_payload(**kwargs) -> tuple[dict, dict | None]:
    csv_run_id = str(kwargs["create_values"].get("multi_format_loaded_csv_run_id") or "").strip()
    if csv_run_id:
        load_summary = get_ready_multi_format_csv_load_summary(csv_run_id=csv_run_id)
        vector_store_name = str(load_summary.get("vector_store_name") or "").strip()
        if vector_store_name != str(kwargs["vector_store_name"] or "").strip():
            raise RuntimeError("Selected Multi-Format loaded-table run does not match the Vector Store name.")
        payload = strip_file_based_create_params(dict(kwargs["exec_payload"]))
        payload.update(
            {
                "target_database": str(load_summary["target_database"]),
                "object_names": str(load_summary["table_name"]),
                "data_columns": ["text"],
                "key_columns": ["id"],
                "nv_ingestor": None,
            }
        )
        return payload, {
            **load_summary,
            "source": "loaded_multi_format_csv_table",
            "skip_vectorstore_create": False,
            "chunk_count": load_summary.get("persisted_row_count"),
        }
    return apply_multi_format_pipeline(
        exec_payload=kwargs["exec_payload"],
        create_values=kwargs["create_values"],
        vector_store_name=kwargs["vector_store_name"],
        connection_params=kwargs.get("connection_params"),
        execute_sql_fn=kwargs.get("execute_sql_fn"),
        resolve_path_hint=kwargs["resolve_path_hint"],
        pipeline_mode=MODE,
    )


def append_success_message(message: str, summary: dict | None) -> str:
    return append_multi_format_summary(message, summary)
