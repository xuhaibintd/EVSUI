from __future__ import annotations

from app.services.doc_modes.common import append_multi_format_summary
from app.services.multi_format import apply_multi_format_pipeline

MODE = "multi_format_bookrag"
LABEL = "Multi-Format BookRAG"
SKIP_VECTORSTORE_CREATE = True


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


def build_skip_create_message(summary: dict | None) -> str:
    message = "Step 2 completed. Skipped VectorStore.create() for Multi-Format BookRAG mode."
    message = append_multi_format_summary(message, summary)
    if not summary:
        return message

    effective_strategy = summary.get("effective_partition_strategy")
    effective_languages = summary.get("effective_ocr_languages")
    file_mode = summary.get("file_mode")
    if file_mode == "per-extension":
        message += " per-file partition options enabled."
    if effective_strategy:
        message += f" strategy={effective_strategy}."
    if effective_languages:
        message += f" ocr_languages={','.join(effective_languages)}."
    debug_dir = summary.get("debug_dir")
    if debug_dir:
        message += f" Unstructured debug files saved to {debug_dir}."
    return message
