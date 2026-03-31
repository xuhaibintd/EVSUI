from __future__ import annotations

from app.services.doc_modes.common import append_multi_format_summary
from app.services.multi_format import apply_multi_format_pipeline

MODE = "multi_format_bookrag"
LABEL = "Multi-Format BookRAG"
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
    message = append_multi_format_summary(message, summary)
    if not summary:
        return message

    table_name = str(summary.get("table_name") or "").strip()
    if table_name:
        message += f" VectorStore indexed from leaf nodes view {table_name} using content/node_id."

    block_count = summary.get("block_count")
    node_count = summary.get("node_count")
    leaf_node_count = summary.get("leaf_node_count")
    entity_count = summary.get("entity_count")
    entity_link_count = summary.get("entity_link_count")
    stats = summary.get("bookrag_insert_stats") or {}

    details = []
    if block_count is not None:
        details.append(f"blocks={block_count}")
    if node_count is not None:
        details.append(f"nodes={node_count}")
    if leaf_node_count is not None:
        details.append(f"leaf_nodes={leaf_node_count}")
    if entity_count is not None:
        details.append(f"entities={entity_count}")
    if entity_link_count is not None:
        details.append(f"entity_links={entity_link_count}")
    if details:
        message += " " + " ".join(details) + "."

    stat_parts = []
    for key in (
        "read_csv_calls",
        "read_csv_rows",
        "read_csv_fallbacks",
        "copy_to_sql_calls",
        "copy_to_sql_rows",
        "batch_insert_statements",
        "single_row_statements",
    ):
        value = stats.get(key)
        if value:
            stat_parts.append(f"{key}={value}")
    if stat_parts:
        message += " insert_stats=" + ", ".join(stat_parts) + "."

    return message
