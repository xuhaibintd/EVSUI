from __future__ import annotations

from typing import Any

from app.services.bookrag_schema import _qualified_table_sql, _sql_literal, build_bookrag_table_targets
from app.utils.table_state import format_preview, normalize_header_key, table_from_result

NodeRow = dict[str, Any]
EvidencePackage = dict[str, Any]
BookRAGEvidenceResult = dict[str, Any]


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _cursor_to_rows(cursor: Any) -> list[dict[str, Any]]:
    if cursor is None:
        return []
    columns: list[str] = []
    description = getattr(cursor, "description", None)
    if description:
        try:
            for item in description:
                if isinstance(item, (list, tuple)) and item:
                    columns.append(str(item[0]))
                else:
                    columns.append(str(getattr(item, "name", item)))
        except Exception:
            columns = []

    fetchall = getattr(cursor, "fetchall", None)
    rows_raw = []
    if callable(fetchall):
        try:
            rows_raw = fetchall() or []
        except Exception:
            rows_raw = []

    rows: list[dict[str, Any]] = []
    for raw in rows_raw:
        if isinstance(raw, dict):
            rows.append({str(key): value for key, value in raw.items()})
            continue
        if isinstance(raw, (list, tuple)):
            if columns and len(columns) == len(raw):
                rows.append({columns[idx]: raw[idx] for idx in range(len(columns))})
            else:
                rows.append({f"col_{idx + 1}": value for idx, value in enumerate(raw)})
            continue
        if columns:
            rows.append({columns[0]: raw})
        else:
            rows.append({"value": raw})
    return rows


def _extract_similarity_matches(similarity_result: Any) -> tuple[list[dict[str, Any]], str | None]:
    headers, rows = table_from_result(similarity_result)
    if not headers or not rows:
        return [], None

    normalized_headers = [normalize_header_key(header) for header in headers]

    def _find_index(*candidates: str) -> int:
        for idx, header in enumerate(normalized_headers):
            if any(header == candidate or candidate in header for candidate in candidates):
                return idx
        return -1

    score_idx = _find_index("score", "similarityscore")
    schema_idx = _find_index("databasename", "database", "schemaname", "schema")
    node_id_idx = _find_index("nodeid", "tdid", "kbid")
    if node_id_idx < 0:
        for idx, header in enumerate(normalized_headers):
            if header in {"id", "key", "keycolumn", "keycolumns"}:
                node_id_idx = idx
                break
    if node_id_idx < 0:
        excluded_headers = {
            "#",
            "score",
            "databasename",
            "database",
            "schemaname",
            "schema",
            "tablename",
            "table",
            "indexlabel",
        }
        id_like_indices = [
            idx
            for idx, header in enumerate(normalized_headers)
            if header not in excluded_headers and header.endswith("id")
        ]
        if len(id_like_indices) == 1:
            node_id_idx = id_like_indices[0]

    content_idx = _find_index("content", "chunks", "text")
    if node_id_idx < 0 and content_idx < 0:
        return [], None

    matches: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    inferred_schema_name: str | None = None
    for row in rows:
        node_id = _as_text(row[node_id_idx]) if 0 <= node_id_idx < len(row) else None
        content = _as_text(row[content_idx]) if 0 <= content_idx < len(row) else None
        if not node_id and not content:
            continue
        dedupe_key = f"id:{node_id}" if node_id else f"content:{content}"
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        score = _as_float(row[score_idx]) if 0 <= score_idx < len(row) else None
        if inferred_schema_name is None and 0 <= schema_idx < len(row):
            inferred_schema_name = _as_text(row[schema_idx])
        matches.append({"node_id": node_id, "content": content, "score": score})
    return matches, inferred_schema_name


def _iter_batches(values: list[str], size: int = 64) -> list[list[str]]:
    return [values[idx:idx + size] for idx in range(0, len(values), size)]


def _fetch_rows_by_ids(
    *,
    schema_name: str | None,
    table_name: str,
    id_column: str,
    ids: list[str],
    columns: list[str],
    execute_sql_fn,
) -> list[dict[str, Any]]:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    if not ids:
        return []
    qualified_table = _qualified_table_sql(schema_name, table_name)
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    quoted_id = id_column.replace('"', '""')
    rows: list[dict[str, Any]] = []
    for batch in _iter_batches(ids):
        id_sql = ", ".join(_sql_literal(value) for value in batch)
        cursor = execute_sql_fn(
            f'SELECT {quoted_columns} FROM {qualified_table} WHERE "{quoted_id}" IN ({id_sql})'
        )
        rows.extend(_cursor_to_rows(cursor))
    return rows


def _fetch_rows_by_values(
    *,
    schema_name: str | None,
    table_name: str,
    value_column: str,
    values: list[str],
    columns: list[str],
    execute_sql_fn,
) -> list[dict[str, Any]]:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    cleaned_values = [value for value in values if _as_text(value)]
    if not cleaned_values:
        return []
    qualified_table = _qualified_table_sql(schema_name, table_name)
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    quoted_value_column = value_column.replace('"', '""')
    rows: list[dict[str, Any]] = []
    for batch in _iter_batches(cleaned_values, size=16):
        value_sql = ", ".join(_sql_literal(value) for value in batch)
        cursor = execute_sql_fn(
            f'SELECT {quoted_columns} FROM {qualified_table} WHERE "{quoted_value_column}" IN ({value_sql})'
        )
        rows.extend(_cursor_to_rows(cursor))
    return rows


def _nearest_section(node: NodeRow, node_map: dict[str, NodeRow]) -> NodeRow | None:
    current = node
    while current is not None:
        if str(current.get("node_type") or "").strip().lower() == "section":
            return current
        parent_id = _as_text(current.get("parent_node_id"))
        if not parent_id:
            return None
        current = node_map.get(parent_id)
    return None


def _section_chain(node: NodeRow, node_map: dict[str, NodeRow]) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    current = _nearest_section(node, node_map)
    while current is not None:
        chain.append(
            {
                "node_id": _as_text(current.get("node_id")),
                "title": _as_text(current.get("title")),
                "content": _as_text(current.get("content")),
                "path": _as_text(current.get("path")),
                "page_start": _as_int(current.get("page_start")),
                "page_end": _as_int(current.get("page_end")),
            }
        )
        parent_id = _as_text(current.get("parent_node_id"))
        if not parent_id:
            break
        current = node_map.get(parent_id)
        if current is not None and str(current.get("node_type") or "").strip().lower() != "section":
            current = _nearest_section(current, node_map)
    chain.reverse()
    return chain


def _resolve_match_node(
    match: dict[str, Any],
    node_map: dict[str, NodeRow],
    content_node_map: dict[str, list[NodeRow]],
) -> NodeRow | None:
    node_id = _as_text(match.get("node_id"))
    if node_id:
        node = node_map.get(node_id)
        if node is not None:
            return node
    content = _as_text(match.get("content"))
    if content:
        candidates = content_node_map.get(content) or []
        if candidates:
            return candidates[0]
    return None


def build_bookrag_evidence_packages(
    *,
    vector_store_name: str,
    similarity_result: Any,
    execute_sql_fn,
    schema_name: str | None = None,
) -> list[EvidencePackage]:
    matches, inferred_schema_name = _extract_similarity_matches(similarity_result)
    if not matches:
        return []

    effective_schema_name = schema_name or inferred_schema_name
    table_targets = build_bookrag_table_targets(vector_store_name)
    node_ids = [node_id for match in matches if (node_id := _as_text(match.get("node_id")))]
    content_values = [content for match in matches if (content := _as_text(match.get("content")))]
    node_columns = [
        "node_id",
        "doc_id",
        "source_block_id",
        "parent_node_id",
        "node_type",
        "level",
        "ordinal",
        "title",
        "content",
        "page_start",
        "page_end",
        "path",
        "is_leaf",
    ]
    node_rows: list[dict[str, Any]] = []
    if node_ids:
        node_rows.extend(
            _fetch_rows_by_ids(
                schema_name=effective_schema_name,
                table_name=table_targets["nodes"],
                id_column="node_id",
                ids=node_ids,
                columns=node_columns,
                execute_sql_fn=execute_sql_fn,
            )
        )
    if content_values:
        node_rows.extend(
            _fetch_rows_by_values(
                schema_name=effective_schema_name,
                table_name=table_targets["nodes"],
                value_column="content",
                values=content_values,
                columns=node_columns,
                execute_sql_fn=execute_sql_fn,
            )
        )
    node_map: dict[str, NodeRow] = {
        str(row.get("node_id")): row for row in node_rows if _as_text(row.get("node_id"))
    }
    content_node_map: dict[str, list[NodeRow]] = {}
    for row in node_rows:
        content = _as_text(row.get("content"))
        if not content:
            continue
        content_node_map.setdefault(content, []).append(row)

    pending_parent_ids = {
        _as_text(row.get("parent_node_id"))
        for row in node_rows
        if _as_text(row.get("parent_node_id")) and _as_text(row.get("parent_node_id")) not in node_map
    }
    while pending_parent_ids:
        parent_rows = _fetch_rows_by_ids(
            schema_name=effective_schema_name,
            table_name=table_targets["nodes"],
            id_column="node_id",
            ids=sorted(pending_parent_ids),
            columns=node_columns,
            execute_sql_fn=execute_sql_fn,
        )
        pending_parent_ids = set()
        for row in parent_rows:
            node_id = _as_text(row.get("node_id"))
            if not node_id or node_id in node_map:
                continue
            node_map[node_id] = row
            parent_id = _as_text(row.get("parent_node_id"))
            if parent_id and parent_id not in node_map:
                pending_parent_ids.add(parent_id)

    resolved_nodes: list[NodeRow] = []
    for match in matches:
        node = _resolve_match_node(match, node_map, content_node_map)
        if node is not None:
            resolved_nodes.append(node)

    source_block_ids = [
        _as_text(node.get("source_block_id"))
        for node in resolved_nodes
        if _as_text(node.get("source_block_id"))
    ]
    block_columns = [
        "block_id",
        "block_type",
        "page_number",
        "ordinal",
        "section_title",
        "text",
        "text_as_html",
    ]
    block_rows = _fetch_rows_by_ids(
        schema_name=effective_schema_name,
        table_name=table_targets["blocks"],
        id_column="block_id",
        ids=source_block_ids,
        columns=block_columns,
        execute_sql_fn=execute_sql_fn,
    )
    block_map = {
        str(row.get("block_id")): row for row in block_rows if _as_text(row.get("block_id"))
    }

    packages: list[EvidencePackage] = []
    for rank, match in enumerate(matches, start=1):
        node = _resolve_match_node(match, node_map, content_node_map)
        if node is None:
            continue
        source_block_id = _as_text(node.get("source_block_id"))
        block = block_map.get(source_block_id) if source_block_id else None
        nearest_section = _nearest_section(node, node_map)
        packages.append(
            {
                "rank": rank,
                "score": match.get("score"),
                "schema_name": effective_schema_name,
                "tables": table_targets,
                "match": {
                    "node_id": _as_text(node.get("node_id")),
                    "doc_id": _as_text(node.get("doc_id")),
                    "node_type": _as_text(node.get("node_type")),
                    "title": _as_text(node.get("title")),
                    "content": _as_text(node.get("content")),
                    "path": _as_text(node.get("path")),
                    "page_start": _as_int(node.get("page_start")),
                    "page_end": _as_int(node.get("page_end")),
                    "source_block_id": source_block_id,
                    "parent_node_id": _as_text(node.get("parent_node_id")),
                    "ordinal": _as_int(node.get("ordinal")),
                },
                "section": {
                    "node_id": _as_text(nearest_section.get("node_id")),
                    "title": _as_text(nearest_section.get("title")),
                    "content": _as_text(nearest_section.get("content")),
                    "path": _as_text(nearest_section.get("path")),
                    "page_start": _as_int(nearest_section.get("page_start")),
                    "page_end": _as_int(nearest_section.get("page_end")),
                }
                if nearest_section is not None
                else None,
                "section_chain": _section_chain(node, node_map),
                "block": {
                    "block_id": _as_text(block.get("block_id")),
                    "block_type": _as_text(block.get("block_type")),
                    "section_title": _as_text(block.get("section_title")),
                    "text": _as_text(block.get("text")),
                    "text_as_html": _as_text(block.get("text_as_html")),
                    "page_number": _as_int(block.get("page_number")),
                    "ordinal": _as_int(block.get("ordinal")),
                }
                if block is not None
                else None,
            }
        )
    return packages


def render_bookrag_evidence_packages(packages: list[EvidencePackage]) -> str:
    parts: list[str] = []
    for package in packages:
        match = package.get("match") or {}
        section = package.get("section") or {}
        block = package.get("block") or {}
        score = package.get("score")
        lines = [f"[Evidence {package.get('rank')}]" ]
        if score is not None:
            lines.append(f"Score: {score:.6f}" if isinstance(score, float) else f"Score: {score}")
        lines.append(f"Node ID: {match.get('node_id') or ''}")
        if match.get("path"):
            lines.append(f"Path: {match.get('path')}")
        if match.get("page_start") is not None:
            page_end = match.get("page_end")
            if page_end is not None and page_end != match.get("page_start"):
                lines.append(f"Pages: {match.get('page_start')}-{page_end}")
            else:
                lines.append(f"Page: {match.get('page_start')}")
        if section.get("title"):
            lines.append(f"Section: {section.get('title')}")
        if section.get("content"):
            lines.append(f"Section Content: {section.get('content')}")
        if match.get("content"):
            lines.append(f"Content: {match.get('content')}")
        if block.get("text_as_html"):
            lines.append(f"Table HTML: {block.get('text_as_html')}")
        elif block.get("text") and block.get("text") != match.get("content"):
            lines.append(f"Block Text: {block.get('text')}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def retrieve_bookrag_evidence(
    *,
    vector_store_name: str,
    similarity_result: Any,
    execute_sql_fn,
    schema_name: str | None = None,
) -> BookRAGEvidenceResult:
    similarity_headers, similarity_rows = table_from_result(similarity_result)
    packages = build_bookrag_evidence_packages(
        vector_store_name=vector_store_name,
        similarity_result=similarity_result,
        execute_sql_fn=execute_sql_fn,
        schema_name=schema_name,
    )
    return {
        "vector_store_name": vector_store_name,
        "schema_name": schema_name,
        "packages": packages,
        "package_count": len(packages),
        "similarity_row_count": len(similarity_rows),
        "similarity_headers": similarity_headers[1:] if similarity_headers[:1] == ["#"] else similarity_headers,
        "similarity_preview": format_preview(similarity_result, max_chars=500),
        "evidence_text": render_bookrag_evidence_packages(packages),
    }
