from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable

from app.services.bookrag_schema import (
    BOOKRAG_DOCUMENT_RELATION_COLUMNS,
    build_bookrag_table_targets,
    prepare_bookrag_document_relation_table,
)
from app.services.teradata_sql import (
    ExecuteSqlFn,
    _qualified_table_sql,
    _sql_literal,
    _sql_typed_literal,
    _teradata_table_exists,
)


BOOKRAG_DOCUMENT_RELATION_TYPES: tuple[str, ...] = (
    "summary_of",
    "next_issue_of",
    "updates",
    "supplement_to",
    "follow_up_to",
    "references",
    "related_to",
)
BOOKRAG_DOCUMENT_RELATION_SOURCE_TYPES: tuple[str, ...] = (
    "human",
    "rule",
    "import",
    "llm",
)

_RELATION_COLUMN_TYPES = dict(BOOKRAG_DOCUMENT_RELATION_COLUMNS)


def _as_text(value: Any, *, max_len: int | None = None) -> str:
    text = str(value or "").strip()
    if max_len is not None:
        return text[:max_len]
    return text


def _cursor_rows(cursor: Any) -> list[dict[str, Any]]:
    if cursor is None:
        return []
    description = getattr(cursor, "description", None) or []
    column_names = [str(item[0]) for item in description if item]
    fetchall = getattr(cursor, "fetchall", None)
    if not callable(fetchall):
        return []
    raw_rows = fetchall() or []
    rows: list[dict[str, Any]] = []
    for raw_row in raw_rows:
        if isinstance(raw_row, dict):
            rows.append({str(key).lower(): value for key, value in raw_row.items()})
        elif column_names:
            rows.append(
                {
                    column_names[index].lower(): value
                    for index, value in enumerate(raw_row)
                    if index < len(column_names)
                }
            )
    return rows


def normalize_uploaded_documents(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    seen_doc_ids: set[str] = set()
    for item in items:
        doc_id = _as_text(item.get("doc_id"), max_len=64)
        filename = _as_text(item.get("filename") or item.get("name"), max_len=255)
        if not doc_id or not filename or doc_id in seen_doc_ids:
            continue
        seen_doc_ids.add(doc_id)
        documents.append({"doc_id": doc_id, "filename": filename})
    return documents


def _document_kind(filename: str) -> str:
    compact = filename.lstrip()
    if compact.startswith("①"):
        return "main"
    if compact.startswith("②"):
        return "summary"
    if compact.startswith(("③", "④")) and "月次" in compact:
        return "monthly"
    if compact.startswith("⑤") or "GMAP_Spot" in compact:
        return "spot"
    if compact.startswith("⑥") or "Topics" in compact:
        return "topics"
    return "other"


def _issue_key(filename: str) -> tuple[int, int] | None:
    match = re.search(r"(20\d{2})年(新春|春|夏|秋|冬)号", filename)
    if not match:
        return None
    season_order = {"新春": 1, "春": 2, "夏": 3, "秋": 4, "冬": 5}
    return int(match.group(1)), season_order[match.group(2)]


def _monthly_key(filename: str) -> tuple[int, int] | None:
    match = re.search(r"(20\d{2})年\s*(\d{1,2})月", filename)
    if not match:
        return None
    month = int(match.group(2))
    return (int(match.group(1)), month) if 1 <= month <= 12 else None


def suggest_document_relations(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return conservative filename-based drafts; suggestions are never active implicitly."""
    documents = normalize_uploaded_documents(items)
    suggestions: list[dict[str, Any]] = []
    main_by_issue = {
        key: document
        for document in documents
        if _document_kind(document["filename"]) == "main"
        and (key := _issue_key(document["filename"])) is not None
    }
    for summary in documents:
        if _document_kind(summary["filename"]) != "summary":
            continue
        issue_key = _issue_key(summary["filename"])
        target = main_by_issue.get(issue_key) if issue_key else None
        if target:
            suggestions.append(
                _draft_relation(
                    summary,
                    "summary_of",
                    target,
                    "Filename rule matched the summary and full report issue.",
                )
            )

    for kind, key_fn in (("main", _issue_key), ("summary", _issue_key), ("monthly", _monthly_key)):
        series = sorted(
            (
                (key, document)
                for document in documents
                if _document_kind(document["filename"]) == kind
                and (key := key_fn(document["filename"])) is not None
            ),
            key=lambda item: item[0],
        )
        for index in range(1, len(series)):
            newer = series[index][1]
            older = series[index - 1][1]
            suggestions.append(
                _draft_relation(
                    newer,
                    "next_issue_of",
                    older,
                    f"Filename rule ordered the {kind} series by issue date.",
                )
            )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in suggestions:
        key = (row["from_doc_id"], row["relation_type"], row["to_doc_id"])
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped


def _draft_relation(
    source: dict[str, Any],
    relation_type: str,
    target: dict[str, Any],
    description: str,
) -> dict[str, Any]:
    return {
        "from_doc_id": source["doc_id"],
        "from_filename": source["filename"],
        "relation_type": relation_type,
        "to_doc_id": target["doc_id"],
        "to_filename": target["filename"],
        "relation_description": description,
        "source_type": "rule",
        "confidence": 1.0,
        "is_active": 0,
        "confirmed": False,
    }


def validate_document_relation(
    relation: dict[str, Any],
    documents: Iterable[dict[str, Any]],
    *,
    allow_unconfirmed: bool = False,
) -> dict[str, Any]:
    document_map = {
        document["doc_id"]: document["filename"]
        for document in normalize_uploaded_documents(documents)
    }
    from_doc_id = _as_text(relation.get("from_doc_id"), max_len=64)
    to_doc_id = _as_text(relation.get("to_doc_id"), max_len=64)
    relation_type = _as_text(relation.get("relation_type"), max_len=64)
    if not from_doc_id or from_doc_id not in document_map:
        raise ValueError(f"Unknown source document: {from_doc_id or '(empty)'}. ")
    if not to_doc_id or to_doc_id not in document_map:
        raise ValueError(f"Unknown target document: {to_doc_id or '(empty)'}. ")
    if from_doc_id == to_doc_id:
        raise ValueError("A document cannot relate to itself.")
    if relation_type not in BOOKRAG_DOCUMENT_RELATION_TYPES:
        raise ValueError(f"Unsupported document relation type: {relation_type or '(empty)' }.")
    if not allow_unconfirmed and relation.get("confirmed") is False:
        raise ValueError("The document relationship suggestion has not been confirmed.")
    source_type = _as_text(relation.get("source_type") or "human", max_len=32).lower()
    if source_type not in BOOKRAG_DOCUMENT_RELATION_SOURCE_TYPES:
        raise ValueError(f"Unsupported document relation source: {source_type}.")
    raw_confidence = relation.get("confidence")
    confidence = None if raw_confidence in (None, "") else float(raw_confidence)
    if confidence is not None and not 0.0 <= confidence <= 1.0:
        raise ValueError("Document relation confidence must be between 0 and 1.")
    return {
        "from_doc_id": from_doc_id,
        "from_filename": document_map[from_doc_id],
        "relation_type": relation_type,
        "to_doc_id": to_doc_id,
        "to_filename": document_map[to_doc_id],
        "relation_description": _as_text(relation.get("relation_description"), max_len=4000) or None,
        "source_type": source_type,
        "confidence": confidence,
        "is_active": 1 if str(relation.get("is_active", "1")).strip().lower() not in {"0", "false", "off", "no"} else 0,
    }


def validate_document_relations(
    relations: Iterable[dict[str, Any]],
    documents: Iterable[dict[str, Any]],
    *,
    allow_unconfirmed: bool = False,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for relation in relations:
        row = validate_document_relation(
            relation,
            documents,
            allow_unconfirmed=allow_unconfirmed,
        )
        key = (row["from_doc_id"], row["relation_type"], row["to_doc_id"])
        if key in seen:
            raise ValueError(f"Duplicate document relationship: {key!r}.")
        seen.add(key)
        normalized.append(row)
    return normalized


def ensure_document_relation_table(
    *,
    vector_store_name: str,
    schema_name: str | None,
    execute_sql_fn: ExecuteSqlFn | None,
) -> bool:
    targets = build_bookrag_table_targets(vector_store_name)
    qualified_table = _qualified_table_sql(schema_name, targets["document_relations"])
    if _teradata_table_exists(qualified_table, execute_sql_fn):
        return False
    prepare_bookrag_document_relation_table(schema_name, targets, execute_sql_fn)
    return True


def document_relation_table_exists(
    *,
    vector_store_name: str,
    schema_name: str | None,
    execute_sql_fn: ExecuteSqlFn | None,
) -> bool:
    table_name = build_bookrag_table_targets(vector_store_name)["document_relations"]
    return _teradata_table_exists(
        _qualified_table_sql(schema_name, table_name),
        execute_sql_fn,
    )


def fetch_bookrag_documents(
    *,
    vector_store_name: str,
    schema_name: str | None,
    execute_sql_fn: ExecuteSqlFn | None,
) -> list[dict[str, Any]]:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    table_name = build_bookrag_table_targets(vector_store_name)["documents"]
    qualified = _qualified_table_sql(schema_name, table_name)
    cursor = execute_sql_fn(
        f'SELECT "doc_id", "filename" FROM {qualified} ORDER BY "filename"'
    )
    return normalize_uploaded_documents(_cursor_rows(cursor))


def fetch_document_relations(
    *,
    vector_store_name: str,
    schema_name: str | None,
    execute_sql_fn: ExecuteSqlFn | None,
    doc_ids: Iterable[str] | None = None,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    table_name = build_bookrag_table_targets(vector_store_name)["document_relations"]
    qualified = _qualified_table_sql(schema_name, table_name)
    if not _teradata_table_exists(qualified, execute_sql_fn):
        return []
    where_sql = ' WHERE "is_active" = 1' if active_only else ""
    normalized_ids = sorted({_as_text(value, max_len=64) for value in (doc_ids or []) if _as_text(value)})
    if normalized_ids:
        values = ", ".join(_sql_literal(value) for value in normalized_ids)
        connector = " AND " if where_sql else " WHERE "
        where_sql += f'{connector}("from_doc_id" IN ({values}) OR "to_doc_id" IN ({values}))'
    columns = ", ".join(f'"{name}"' for name, _ in BOOKRAG_DOCUMENT_RELATION_COLUMNS)
    cursor = execute_sql_fn(
        f'SELECT {columns} FROM {qualified}{where_sql} '
        'ORDER BY "from_filename", "relation_type", "to_filename"'
    )
    return _cursor_rows(cursor)


def persist_document_relations(
    *,
    vector_store_name: str,
    schema_name: str | None,
    relations: Iterable[dict[str, Any]],
    documents: Iterable[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    username: str = "",
) -> int:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    rows = validate_document_relations(relations, documents)
    if not rows:
        return 0
    ensure_document_relation_table(
        vector_store_name=vector_store_name,
        schema_name=schema_name,
        execute_sql_fn=execute_sql_fn,
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")
    table_name = build_bookrag_table_targets(vector_store_name)["document_relations"]
    qualified = _qualified_table_sql(schema_name, table_name)
    columns = [name for name, _ in BOOKRAG_DOCUMENT_RELATION_COLUMNS]
    quoted_columns = ", ".join(f'"{name}"' for name in columns)
    for row in rows:
        complete_row = {
            **row,
            "created_by": _as_text(username, max_len=128) or None,
            "created_at": now,
            "updated_by": _as_text(username, max_len=128) or None,
            "updated_at": now,
        }
        values = ", ".join(
            _sql_typed_literal(complete_row.get(name), _RELATION_COLUMN_TYPES[name])
            for name in columns
        )
        execute_sql_fn(f"INSERT INTO {qualified} ({quoted_columns}) VALUES ({values})")
    return len(rows)


def delete_document_relation(
    *,
    vector_store_name: str,
    schema_name: str | None,
    from_doc_id: str,
    relation_type: str,
    to_doc_id: str,
    execute_sql_fn: ExecuteSqlFn | None,
) -> None:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    table_name = build_bookrag_table_targets(vector_store_name)["document_relations"]
    qualified = _qualified_table_sql(schema_name, table_name)
    execute_sql_fn(
        f'DELETE FROM {qualified} WHERE "from_doc_id"={_sql_literal(from_doc_id)} '
        f'AND "relation_type"={_sql_literal(relation_type)} '
        f'AND "to_doc_id"={_sql_literal(to_doc_id)}'
    )


def save_document_relation(
    *,
    vector_store_name: str,
    schema_name: str | None,
    relation: dict[str, Any],
    documents: Iterable[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    username: str = "",
    original_key: tuple[str, str, str] | None = None,
) -> dict[str, Any]:
    normalized = validate_document_relation(relation, documents)
    key = (
        normalized["from_doc_id"],
        normalized["relation_type"],
        normalized["to_doc_id"],
    )
    ensure_document_relation_table(
        vector_store_name=vector_store_name,
        schema_name=schema_name,
        execute_sql_fn=execute_sql_fn,
    )
    delete_key = original_key or key
    existing_keys = {
        (
            _as_text(row.get("from_doc_id"), max_len=64),
            _as_text(row.get("relation_type"), max_len=64),
            _as_text(row.get("to_doc_id"), max_len=64),
        )
        for row in fetch_document_relations(
            vector_store_name=vector_store_name,
            schema_name=schema_name,
            execute_sql_fn=execute_sql_fn,
            active_only=False,
        )
    }
    if delete_key == key and key in existing_keys:
        if execute_sql_fn is None:
            raise RuntimeError("teradataml.execute_sql is unavailable.")
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")
        table_name = build_bookrag_table_targets(vector_store_name)["document_relations"]
        qualified = _qualified_table_sql(schema_name, table_name)
        update_values = {
            "from_filename": normalized["from_filename"],
            "to_filename": normalized["to_filename"],
            "relation_description": normalized["relation_description"],
            "source_type": normalized["source_type"],
            "confidence": normalized["confidence"],
            "is_active": normalized["is_active"],
            "updated_by": _as_text(username, max_len=128) or None,
            "updated_at": now,
        }
        assignments = ", ".join(
            f'"{name}"={_sql_typed_literal(value, _RELATION_COLUMN_TYPES[name])}'
            for name, value in update_values.items()
        )
        execute_sql_fn(
            f'UPDATE {qualified} SET {assignments} '
            f'WHERE "from_doc_id"={_sql_literal(key[0])} '
            f'AND "relation_type"={_sql_literal(key[1])} '
            f'AND "to_doc_id"={_sql_literal(key[2])}'
        )
        return normalized
    if delete_key != key:
        if key in existing_keys:
            raise ValueError(f"Duplicate document relationship: {key!r}.")
    persist_document_relations(
        vector_store_name=vector_store_name,
        schema_name=schema_name,
        relations=[{**normalized, "confirmed": True}],
        documents=documents,
        execute_sql_fn=execute_sql_fn,
        username=username,
    )
    if delete_key != key and delete_key in existing_keys:
        delete_document_relation(
            vector_store_name=vector_store_name,
            schema_name=schema_name,
            from_doc_id=delete_key[0],
            relation_type=delete_key[1],
            to_doc_id=delete_key[2],
            execute_sql_fn=execute_sql_fn,
        )
    return normalized
