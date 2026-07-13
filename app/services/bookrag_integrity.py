from __future__ import annotations

from typing import Any


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _row_key(row: dict[str, Any], columns: tuple[str, ...]) -> tuple[Any, ...]:
    return tuple(row.get(column) for column in columns)


def _validate_table_keys(
    *,
    table_name: str,
    rows: list[dict[str, Any]],
    key_columns: tuple[str, ...],
    doc_id: str,
) -> None:
    seen: set[tuple[Any, ...]] = set()
    for index, row in enumerate(rows, start=1):
        if _as_text(row.get("doc_id")) != doc_id:
            raise RuntimeError(
                f"BookRAG integrity validation failed: table={table_name}, row={index}, "
                f"expected doc_id={doc_id}, actual doc_id={row.get('doc_id')!r}."
            )
        key = _row_key(row, key_columns)
        if any(value is None or _as_text(value) is None for value in key):
            raise RuntimeError(
                f"BookRAG integrity validation failed: table={table_name}, row={index}, "
                f"empty primary key {key_columns}={key!r}."
            )
        if key in seen:
            raise RuntimeError(
                f"BookRAG integrity validation failed: table={table_name}, "
                f"duplicate primary key {key_columns}={key!r}."
            )
        seen.add(key)


def _require_target(
    *,
    relationship: str,
    source_key: tuple[str, str],
    target_keys: set[tuple[str, str]],
) -> None:
    if source_key not in target_keys:
        raise RuntimeError(
            f"BookRAG integrity validation failed: relationship={relationship}, "
            f"missing target key={source_key!r}."
        )


def validate_bookrag_dataset_relationships(
    *,
    document_row: dict[str, Any],
    raw_rows: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    entity_links: list[dict[str, Any]],
    entity_relations: list[dict[str, Any]],
    graph_enabled: bool,
) -> None:
    """Fail before CSV persistence if a document-scoped relation is broken."""
    doc_id = _as_text(document_row.get("doc_id"))
    if not doc_id:
        raise RuntimeError("BookRAG integrity validation failed: bdoc.doc_id is empty.")

    _validate_table_keys(
        table_name="braw",
        rows=raw_rows,
        key_columns=("doc_id", "ordinal_raw"),
        doc_id=doc_id,
    )
    _validate_table_keys(
        table_name="bblk",
        rows=blocks,
        key_columns=("doc_id", "element_id"),
        doc_id=doc_id,
    )
    _validate_table_keys(
        table_name="bnode",
        rows=nodes,
        key_columns=("doc_id", "node_id"),
        doc_id=doc_id,
    )

    block_keys = {
        (doc_id, str(row["element_id"]))
        for row in blocks
        if _as_text(row.get("element_id"))
    }
    node_keys = {
        (doc_id, str(row["node_id"]))
        for row in nodes
        if _as_text(row.get("node_id"))
    }
    root_nodes = [
        row for row in nodes if str(row.get("node_type") or "").strip().lower() == "document"
    ]
    if len(root_nodes) != 1:
        raise RuntimeError(
            f"BookRAG integrity validation failed: doc_id={doc_id}, "
            f"expected exactly one document root node, found {len(root_nodes)}."
        )

    for row in nodes:
        node_id = str(row.get("node_id") or "")
        is_root = str(row.get("node_type") or "").strip().lower() == "document"
        parent_node_id = _as_text(row.get("parent_node_id"))
        source_element_id = _as_text(row.get("source_element_id"))
        if is_root:
            if parent_node_id or source_element_id:
                raise RuntimeError(
                    f"BookRAG integrity validation failed: bnode root={node_id!r} "
                    "must not have parent_node_id or source_element_id."
                )
            continue
        if not parent_node_id or not source_element_id:
            raise RuntimeError(
                f"BookRAG integrity validation failed: bnode={node_id!r} requires "
                "parent_node_id and source_element_id."
            )
        _require_target(
            relationship="node_parent",
            source_key=(doc_id, parent_node_id),
            target_keys=node_keys,
        )
        _require_target(
            relationship="node_source_block",
            source_key=(doc_id, source_element_id),
            target_keys=block_keys,
        )

    if not graph_enabled:
        if entities or entity_links or entity_relations:
            raise RuntimeError(
                "BookRAG integrity validation failed: Graph rows exist while Graph is disabled."
            )
        return

    _validate_table_keys(
        table_name="bent",
        rows=entities,
        key_columns=("doc_id", "entity_id"),
        doc_id=doc_id,
    )
    _validate_table_keys(
        table_name="belnk",
        rows=entity_links,
        key_columns=("doc_id", "link_id"),
        doc_id=doc_id,
    )
    _validate_table_keys(
        table_name="brel",
        rows=entity_relations,
        key_columns=("doc_id", "relation_id"),
        doc_id=doc_id,
    )
    entity_keys = {
        (doc_id, str(row["entity_id"]))
        for row in entities
        if _as_text(row.get("entity_id"))
    }

    for row in entity_links:
        link_id = str(row.get("link_id") or "")
        node_id = _as_text(row.get("node_id"))
        entity_id = _as_text(row.get("entity_id"))
        if not node_id or not entity_id:
            raise RuntimeError(
                f"BookRAG integrity validation failed: belnk={link_id!r} requires node_id and entity_id."
            )
        _require_target(
            relationship="entity_link_node",
            source_key=(doc_id, node_id),
            target_keys=node_keys,
        )
        _require_target(
            relationship="entity_link_entity",
            source_key=(doc_id, entity_id),
            target_keys=entity_keys,
        )
        section_node_id = _as_text(row.get("section_node_id"))
        if section_node_id:
            _require_target(
                relationship="entity_link_section",
                source_key=(doc_id, section_node_id),
                target_keys=node_keys,
            )

    for row in entity_relations:
        relation_id = str(row.get("relation_id") or "")
        source_element_id = _as_text(row.get("source_element_id"))
        source_node_id = _as_text(row.get("source_node_id"))
        from_entity_id = _as_text(row.get("from_entity_id"))
        to_entity_id = _as_text(row.get("to_entity_id"))
        if not all((source_element_id, source_node_id, from_entity_id, to_entity_id)):
            raise RuntimeError(
                f"BookRAG integrity validation failed: brel={relation_id!r} requires "
                "source_element_id, source_node_id, from_entity_id and to_entity_id."
            )
        _require_target(
            relationship="relation_source_block",
            source_key=(doc_id, source_element_id),
            target_keys=block_keys,
        )
        _require_target(
            relationship="relation_source_node",
            source_key=(doc_id, source_node_id),
            target_keys=node_keys,
        )
        _require_target(
            relationship="relation_from_entity",
            source_key=(doc_id, from_entity_id),
            target_keys=entity_keys,
        )
        _require_target(
            relationship="relation_to_entity",
            source_key=(doc_id, to_entity_id),
            target_keys=entity_keys,
        )
        section_node_id = _as_text(row.get("section_node_id"))
        if section_node_id:
            _require_target(
                relationship="relation_section",
                source_key=(doc_id, section_node_id),
                target_keys=node_keys,
            )
