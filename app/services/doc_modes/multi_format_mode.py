from __future__ import annotations

from app.services.doc_modes.messages import append_multi_format_summary
from app.services.multi_format import apply_multi_format_pipeline

MODE = "multi_format"
LABEL = "Unstructured"
SKIP_VECTORSTORE_CREATE = False


def preprocess_create_payload(**kwargs) -> tuple[dict, dict | None]:
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
