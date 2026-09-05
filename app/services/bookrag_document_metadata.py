from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Iterable

from app.services.bookrag_query_planner import TemporalScope, parse_temporal_scope
from app.services.bookrag_retrieval_policy import load_bookrag_retrieval_policy
from app.services.bookrag_schema import (
    BOOKRAG_DOCUMENT_METADATA_COLUMNS,
    build_bookrag_table_targets,
    ensure_bookrag_retrieval_view,
    migrate_bookrag_document_metadata_columns,
)
from app.services.teradata_sql import (
    ExecuteSqlFn,
    _qualified_table_sql,
    _sql_literal,
    _sql_typed_literal,
)


BOOKRAG_PUBLICATION_DATE_SOURCES: tuple[str, ...] = ("content", "filename", "manual")
BOOKRAG_PUBLICATION_DATE_PRECISIONS: tuple[str, ...] = ("day", "month")
BOOKRAG_DOCUMENT_SERIES: tuple[str, ...] = (
    "main",
    "summary",
    "monthly",
    "spot",
    "topics",
    "other",
)
BOOKRAG_DOCUMENT_ROLES: tuple[str, ...] = (
    "comprehensive",
    "update",
    "theme",
    "performance",
    "other",
)
BOOKRAG_METADATA_STATUSES: tuple[str, ...] = ("confirmed", "review", "missing")

_METADATA_COLUMN_TYPES = dict(BOOKRAG_DOCUMENT_METADATA_COLUMNS)
_CONTENT_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:発行日|発行年月日|発行)[\s:：]*"
        r"(20\d{2})\s*[年/\-.]\s*(\d{1,2})\s*[月/\-.]\s*(\d{1,2})\s*日?"
    ),
    re.compile(
        r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
        r"[\s　]*(?:発行|現在)"
    ),
)
_FILENAME_DAY_PATTERN = re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)")
_MONTH_PATTERN = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月")
def _as_text(value: Any, *, max_len: int | None = None) -> str:
    text = str(value or "").strip()
    return text[:max_len] if max_len is not None else text


def _valid_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _content_publication_date(content_values: Iterable[Any]) -> date | None:
    for value in content_values:
        text = _as_text(value)
        if not text:
            continue
        for pattern in _CONTENT_DATE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            parsed = _valid_date(*(int(part) for part in match.groups()))
            if parsed is not None:
                return parsed
    return None


def _filename_publication_date(filename: str) -> date | None:
    for match in _FILENAME_DAY_PATTERN.finditer(filename):
        parsed = _valid_date(2000 + int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if parsed is not None:
            return parsed
    return None


def classify_document(filename: str) -> tuple[str, str]:
    compact = _as_text(filename)
    policy = load_bookrag_retrieval_policy().document_classification
    for rule in policy.rules:
        if re.search(rule.pattern, compact, flags=re.IGNORECASE):
            return rule.series, rule.role
    return policy.fallback_series, policy.fallback_role


def build_logical_document_key(filename: str) -> str:
    stem = re.sub(r"\.[^.]+$", "", _as_text(filename))
    stem = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", stem)
    stem = re.sub(r"(?<!\d)\d{6}(?!\d)", "", stem)
    stem = re.sub(r"(?:改訂版?|更新版?|第\s*\d+\s*版|rev(?:ision)?\.?\s*\d+)", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"[\s_＊*：:「」『』【】（）()]+", " ", stem).strip()
    return stem[:255] or _as_text(filename, max_len=255)


def derive_document_metadata(
    *,
    filename: str,
    content_values: Iterable[Any] = (),
) -> dict[str, Any]:
    publication_date = _content_publication_date(content_values)
    source: str | None = "content" if publication_date else None
    status = "confirmed" if publication_date else "missing"
    if publication_date is None:
        publication_date = _filename_publication_date(filename)
        if publication_date is not None:
            source = "filename"
            status = "review"

    series, role = classify_document(filename)
    month_match = _MONTH_PATTERN.search(filename)
    precision = "day" if publication_date is not None else ("month" if month_match else None)
    return {
        "publication_date": publication_date.isoformat() if publication_date else None,
        "publication_date_source": source,
        "publication_date_precision": precision,
        "document_series": series,
        "document_role": role,
        "logical_document_key": build_logical_document_key(filename),
        "revision_no": 1,
        "metadata_status": status,
        "metadata_updated_by": None,
        "metadata_updated_at": None,
    }


def question_has_explicit_timeline(question: str) -> bool:
    """Compatibility wrapper around the structured temporal parser."""
    return parse_temporal_scope(_as_text(question)).is_explicit


def _cursor_rows(cursor: Any) -> list[dict[str, Any]]:
    if cursor is None:
        return []
    description = getattr(cursor, "description", None) or []
    column_names = [str(item[0]).lower() for item in description if item]
    fetchall = getattr(cursor, "fetchall", None)
    if not callable(fetchall):
        return []
    rows: list[dict[str, Any]] = []
    for raw_row in fetchall() or []:
        if isinstance(raw_row, dict):
            rows.append({str(key).lower(): value for key, value in raw_row.items()})
        elif column_names:
            rows.append(
                {
                    column_names[index]: value
                    for index, value in enumerate(raw_row)
                    if index < len(column_names)
                }
            )
    return rows


def ensure_document_metadata_schema(
    *,
    vector_store_name: str,
    schema_name: str | None,
    execute_sql_fn: ExecuteSqlFn | None,
) -> tuple[str, ...]:
    targets = build_bookrag_table_targets(vector_store_name)
    return migrate_bookrag_document_metadata_columns(
        schema_name=schema_name,
        table_name=targets["documents"],
        execute_sql_fn=execute_sql_fn,
    )


def fetch_document_metadata(
    *,
    vector_store_name: str,
    schema_name: str | None,
    execute_sql_fn: ExecuteSqlFn | None,
) -> list[dict[str, Any]]:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    ensure_document_metadata_schema(
        vector_store_name=vector_store_name,
        schema_name=schema_name,
        execute_sql_fn=execute_sql_fn,
    )
    table_name = build_bookrag_table_targets(vector_store_name)["documents"]
    qualified = _qualified_table_sql(schema_name, table_name)
    columns = [
        "doc_id",
        "filename",
        *(name for name, _ in BOOKRAG_DOCUMENT_METADATA_COLUMNS),
    ]
    quoted_columns = ", ".join(f'"{name}"' for name in columns)
    cursor = execute_sql_fn(
        f"SELECT {quoted_columns} FROM {qualified} "
        'ORDER BY "publication_date" DESC, "filename" ASC'
    )
    return _cursor_rows(cursor)


def _normalize_manual_metadata(values: dict[str, Any]) -> dict[str, Any]:
    publication_date = _as_text(values.get("publication_date"))
    if publication_date:
        try:
            publication_date = date.fromisoformat(publication_date).isoformat()
        except ValueError as ex:
            raise ValueError("Publication date must use YYYY-MM-DD.") from ex
    else:
        publication_date = None

    precision = _as_text(values.get("publication_date_precision")).lower() or (
        "day" if publication_date else None
    )
    series = _as_text(values.get("document_series")).lower() or "other"
    role = _as_text(values.get("document_role")).lower() or "other"
    status = _as_text(values.get("metadata_status")).lower() or (
        "confirmed" if publication_date else "missing"
    )
    if precision and precision not in BOOKRAG_PUBLICATION_DATE_PRECISIONS:
        raise ValueError(f"Unsupported publication date precision: {precision}.")
    if series not in BOOKRAG_DOCUMENT_SERIES:
        raise ValueError(f"Unsupported document series: {series}.")
    if role not in BOOKRAG_DOCUMENT_ROLES:
        raise ValueError(f"Unsupported document role: {role}.")
    if status not in BOOKRAG_METADATA_STATUSES:
        raise ValueError(f"Unsupported metadata status: {status}.")
    revision_text = _as_text(values.get("revision_no"))
    try:
        revision_no = max(1, int(revision_text or "1"))
    except ValueError as ex:
        raise ValueError("Revision number must be an integer.") from ex
    return {
        "publication_date": publication_date,
        "publication_date_source": "manual",
        "publication_date_precision": precision,
        "document_series": series,
        "document_role": role,
        "logical_document_key": _as_text(values.get("logical_document_key"), max_len=255),
        "revision_no": revision_no,
        "metadata_status": status,
    }


def validate_document_metadata_import_rows(
    rows: list[dict[str, Any]], documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve document identities and validate an entire import before writes."""
    document_ids = {str(item.get("doc_id") or "") for item in documents}
    filename_map: dict[str, list[str]] = {}
    for document in documents:
        filename_map.setdefault(str(document.get("filename") or ""), []).append(
            str(document.get("doc_id") or "")
        )
    normalized_rows = []
    seen = set()
    for row in rows:
        doc_id = str(row.get("doc_id") or "").strip()
        if not doc_id:
            filename = str(row.get("filename") or "").strip()
            matches = filename_map.get(filename, [])
            if len(matches) != 1:
                raise ValueError(f"Filename is missing or not unique: {filename!r}.")
            doc_id = matches[0]
        if doc_id not in document_ids:
            raise ValueError(f"Unknown document: {doc_id}.")
        if doc_id in seen:
            raise ValueError(f"Duplicate document in CSV: {doc_id}.")
        seen.add(doc_id)
        normalized_rows.append({**_normalize_manual_metadata(row), "doc_id": doc_id})
    return normalized_rows


def _update_document_metadata(
    *,
    qualified_documents: str,
    doc_id: str,
    values: dict[str, Any],
    username: str,
    execute_sql_fn: ExecuteSqlFn,
) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(
        sep=" ", timespec="microseconds"
    )
    complete_values = {
        **values,
        "metadata_updated_by": _as_text(username, max_len=128) or None,
        "metadata_updated_at": now,
    }
    assignments = ", ".join(
        f'"{name}"={_sql_typed_literal(complete_values.get(name), _METADATA_COLUMN_TYPES[name])}'
        for name, _ in BOOKRAG_DOCUMENT_METADATA_COLUMNS
    )
    execute_sql_fn(
        f"UPDATE {qualified_documents} SET {assignments} "
        f'WHERE "doc_id"={_sql_literal(doc_id)}'
    )


def save_document_metadata(
    *,
    vector_store_name: str,
    schema_name: str | None,
    doc_id: str,
    values: dict[str, Any],
    execute_sql_fn: ExecuteSqlFn | None,
    username: str = "",
    ensure_view: bool = True,
) -> dict[str, Any]:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    clean_doc_id = _as_text(doc_id, max_len=64)
    if not clean_doc_id:
        raise ValueError("Document ID is required.")
    rows = fetch_document_metadata(
        vector_store_name=vector_store_name,
        schema_name=schema_name,
        execute_sql_fn=execute_sql_fn,
    )
    document = next((row for row in rows if _as_text(row.get("doc_id")) == clean_doc_id), None)
    if document is None:
        raise ValueError(f"Unknown document: {clean_doc_id}.")
    normalized = _normalize_manual_metadata(values)
    if not normalized["logical_document_key"]:
        normalized["logical_document_key"] = build_logical_document_key(
            _as_text(document.get("filename"))
        )
    qualified = _qualified_table_sql(
        schema_name,
        build_bookrag_table_targets(vector_store_name)["documents"],
    )
    _update_document_metadata(
        qualified_documents=qualified,
        doc_id=clean_doc_id,
        values=normalized,
        username=username,
        execute_sql_fn=execute_sql_fn,
    )
    if ensure_view:
        ensure_bookrag_retrieval_view(
            vector_store_name=vector_store_name,
            schema_name=schema_name,
            execute_sql_fn=execute_sql_fn,
        )
    return {**normalized, "doc_id": clean_doc_id, "filename": document.get("filename")}


def backfill_document_metadata(
    *,
    vector_store_name: str,
    schema_name: str | None,
    execute_sql_fn: ExecuteSqlFn | None,
    username: str = "metadata-rule",
) -> int:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    documents = fetch_document_metadata(
        vector_store_name=vector_store_name,
        schema_name=schema_name,
        execute_sql_fn=execute_sql_fn,
    )
    targets = build_bookrag_table_targets(vector_store_name)
    qualified_documents = _qualified_table_sql(schema_name, targets["documents"])
    qualified_blocks = _qualified_table_sql(schema_name, targets["blocks"])
    cursor = execute_sql_fn(
        f'SELECT "doc_id", "text" FROM {qualified_blocks} '
        'WHERE "page_number" IS NULL OR "page_number" <= 3 '
        'ORDER BY "doc_id", "ordinal"'
    )
    content_by_doc: dict[str, list[Any]] = {}
    for row in _cursor_rows(cursor):
        content_by_doc.setdefault(_as_text(row.get("doc_id")), []).append(row.get("text"))

    updated = 0
    for document in documents:
        if _as_text(document.get("publication_date_source")).lower() == "manual":
            continue
        doc_id = _as_text(document.get("doc_id"), max_len=64)
        derived = derive_document_metadata(
            filename=_as_text(document.get("filename")),
            content_values=content_by_doc.get(doc_id, ()),
        )
        _update_document_metadata(
            qualified_documents=qualified_documents,
            doc_id=doc_id,
            values=derived,
            username=username,
            execute_sql_fn=execute_sql_fn,
        )
        updated += 1
    ensure_bookrag_retrieval_view(
        vector_store_name=vector_store_name,
        schema_name=schema_name,
        execute_sql_fn=execute_sql_fn,
    )
    return updated


def fetch_governed_document_scope(
    *,
    vector_store_name: str,
    schema_name: str | None,
    execute_sql_fn: ExecuteSqlFn | None,
    temporal_scope: TemporalScope | None = None,
    background_document_series: Iterable[str] = (),
    background_document_roles: Iterable[str] = (),
    metadata_statuses: Iterable[str] = ("confirmed",),
) -> dict[str, Any]:
    """Return effective documents and configuration-selected background candidates."""
    scope = fetch_effective_document_scope(
        vector_store_name=vector_store_name,
        schema_name=schema_name,
        execute_sql_fn=execute_sql_fn,
        temporal_scope=temporal_scope,
        metadata_statuses=metadata_statuses,
    )
    documents = list(scope.get("primary_documents") or [])
    eligible_series = {
        _as_text(value).lower()
        for value in background_document_series
        if _as_text(value)
    }
    eligible_roles = {
        _as_text(value).lower()
        for value in background_document_roles
        if _as_text(value)
    }
    periodic_documents = [
        row
        for row in documents
        if (
            _as_text(row.get("document_series")).lower() in eligible_series
            or _as_text(row.get("document_role")).lower() in eligible_roles
        )
    ]
    scope.update(
        {
            "mode": (
                "explicit_timeline"
                if (temporal_scope and temporal_scope.is_explicit)
                else "latest_related_with_conditional_background"
            ),
            "periodic_documents": periodic_documents,
            "periodic_doc_ids": [
                _as_text(row.get("doc_id"))
                for row in periodic_documents
                if _as_text(row.get("doc_id"))
            ],
            # Compatibility keys for existing callers and rendered scope text.
            "supplemental_documents": periodic_documents,
        }
    )
    return scope


def fetch_effective_document_scope(
    *,
    vector_store_name: str,
    schema_name: str | None,
    execute_sql_fn: ExecuteSqlFn | None,
    temporal_scope: TemporalScope | None = None,
    metadata_statuses: Iterable[str] = (),
) -> dict[str, Any]:
    """Return dated, effective documents after applying the structured time scope."""
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    ensure_document_metadata_schema(
        vector_store_name=vector_store_name,
        schema_name=schema_name,
        execute_sql_fn=execute_sql_fn,
    )
    view_name = ensure_bookrag_retrieval_view(
        vector_store_name=vector_store_name,
        schema_name=schema_name,
        execute_sql_fn=execute_sql_fn,
    )
    qualified_view = _qualified_table_sql(schema_name, view_name)
    effective_temporal_scope = temporal_scope or TemporalScope()
    allowed_statuses = sorted(
        {
            _as_text(value).lower()
            for value in metadata_statuses
            if _as_text(value)
        }
    )

    def status_conditions() -> list[str]:
        if not allowed_statuses:
            return []
        literals = ", ".join(_sql_literal(value) for value in allowed_statuses)
        return [f'LOWER("metadata_status") IN ({literals})']

    if effective_temporal_scope.kind == "latest_quarter":
        max_cursor = execute_sql_fn(
            f'SELECT MAX("publication_date") AS "max_publication_date" '
            f"FROM {qualified_view}"
            + (
                " WHERE " + " AND ".join(status_conditions())
                if status_conditions()
                else ""
            )
        )
        max_rows = _cursor_rows(max_cursor)
        max_text = _as_text(
            max_rows[0].get("max_publication_date") if max_rows else ""
        )
        if max_text:
            max_date = date.fromisoformat(max_text[:10])
            quarter_start_month = ((max_date.month - 1) // 3) * 3 + 1
            quarter_start = date(max_date.year, quarter_start_month, 1)
            quarter_end = date(
                max_date.year + (1 if quarter_start_month == 10 else 0),
                1 if quarter_start_month == 10 else quarter_start_month + 3,
                1,
            )
            effective_temporal_scope = TemporalScope(
                kind="latest_quarter",
                start_date=quarter_start,
                end_date_exclusive=quarter_end,
                source_text=temporal_scope.source_text if temporal_scope else "",
            )

    conditions = status_conditions()
    if effective_temporal_scope.exact_dates:
        literals = ", ".join(
            _sql_typed_literal(value.isoformat(), "DATE")
            for value in effective_temporal_scope.exact_dates
        )
        conditions.append(f'"publication_date" IN ({literals})')
    else:
        if effective_temporal_scope.start_date:
            conditions.append(
                '"publication_date">='
                + _sql_typed_literal(
                    effective_temporal_scope.start_date.isoformat(), "DATE"
                )
            )
        if effective_temporal_scope.end_date_exclusive:
            conditions.append(
                '"publication_date"<'
                + _sql_typed_literal(
                    effective_temporal_scope.end_date_exclusive.isoformat(), "DATE"
                )
            )

    where_sql = " WHERE " + " AND ".join(conditions) if conditions else ""
    cursor = execute_sql_fn(
        'SELECT DISTINCT "doc_id", "filename", "publication_date", '
        '"document_series", "document_role", "metadata_status", "latest_rank" '
        f"FROM {qualified_view}{where_sql} "
        'ORDER BY "publication_date" DESC, "latest_rank" ASC'
    )
    documents = _cursor_rows(cursor)
    return {
        "mode": (
            "explicit_timeline"
            if effective_temporal_scope.is_explicit
            else "latest_available"
        ),
        "view_name": view_name,
        "temporal_scope": effective_temporal_scope.as_dict(),
        "primary_documents": documents,
        "supplemental_documents": [],
        "periodic_documents": [],
        "periodic_doc_ids": [],
        "allowed_doc_ids": [
            _as_text(row.get("doc_id"))
            for row in documents
            if _as_text(row.get("doc_id"))
        ],
    }
