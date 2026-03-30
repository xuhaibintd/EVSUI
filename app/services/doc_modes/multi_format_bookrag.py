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


def _append_bookrag_details(message: str, summary: dict | None) -> str:
    message = append_multi_format_summary(message, summary)
    if not summary:
        return message

    effective_strategy = summary.get("effective_partition_strategy")
    effective_languages = summary.get("effective_ocr_languages")
    file_mode = summary.get("file_mode")
    if file_mode == "per-extension":
        message += " per-file partition options enabled."
    block_count = summary.get("block_count")
    node_count = summary.get("node_count")
    leaf_node_count = summary.get("leaf_node_count")
    if block_count is not None:
        message += f" blocks={block_count}."
    if node_count is not None:
        message += f" nodes={node_count}."
    if leaf_node_count is not None:
        message += f" leaf_nodes={leaf_node_count}."
    profile = summary.get("bookrag_profile")
    if profile:
        message += f" profile={profile}."
    entity_count = summary.get("entity_count")
    entity_link_count = summary.get("entity_link_count")
    if entity_count is not None:
        message += f" entities={entity_count}."
    if entity_link_count is not None:
        message += f" entity_links={entity_link_count}."
    bookrag_tables = summary.get("bookrag_tables") or {}
    if bookrag_tables:
        docs_table = bookrag_tables.get("documents")
        blocks_table = bookrag_tables.get("blocks")
        nodes_table = bookrag_tables.get("nodes")
        entities_table = bookrag_tables.get("entities")
        entity_links_table = bookrag_tables.get("entity_links")
        leaf_nodes_view = bookrag_tables.get("leaf_nodes")
        message += (
            f" tables=docs:{docs_table}, blocks:{blocks_table}, nodes:{nodes_table}, "
            f"entities:{entities_table}, entity_links:{entity_links_table}, leaf_nodes:{leaf_nodes_view}."
        )
    if effective_strategy:
        message += f" strategy={effective_strategy}."
    if effective_languages:
        message += f" ocr_languages={','.join(effective_languages)}."
    debug_dir = summary.get("debug_dir")
    if debug_dir:
        message += f" Unstructured debug files saved to {debug_dir}."
    csv_stage_dir = summary.get("bookrag_csv_stage_dir")
    if csv_stage_dir:
        message += f" CSV stage files saved to {csv_stage_dir}."
    insert_stats = summary.get("bookrag_insert_stats") or {}
    if insert_stats:
        message += (
            " insert_stats="
            f"read_csv_calls:{insert_stats.get('read_csv_calls', 0)},"
            f"read_csv_rows:{insert_stats.get('read_csv_rows', 0)},"
            f"read_csv_fallbacks:{insert_stats.get('read_csv_fallbacks', 0)},"
            f"copy_to_sql_calls:{insert_stats.get('copy_to_sql_calls', 0)},"
            f"single_row_statements:{insert_stats.get('single_row_statements', 0)}."
        )
    return message


def build_skip_create_message(summary: dict | None) -> str:
    message = "Step 2 completed. Built BookIndex tree tables for Multi-Format BookRAG mode."
    return _append_bookrag_details(message, summary)


def append_success_message(message: str, summary: dict | None) -> str:
    bookrag_tables = summary.get("bookrag_tables") or {} if summary else {}
    leaf_nodes_view = bookrag_tables.get("leaf_nodes") if bookrag_tables else None
    if leaf_nodes_view:
        message += f" BookRAG tree tables built and VectorStore indexed from leaf nodes view {leaf_nodes_view} using content/node_id."
    else:
        message += " BookRAG tree tables built and VectorStore indexed from BookRAG leaf nodes."
    return _append_bookrag_details(message, summary)
