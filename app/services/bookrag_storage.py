from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
import json
import re
import uuid
from pathlib import Path
from typing import Any

from app.services.bookrag_schema import (
    BOOKRAG_BLOCK_COLUMNS,
    BOOKRAG_CHUNK_COLUMNS,
    BOOKRAG_DOCUMENT_COLUMNS,
    BOOKRAG_ENTITY_COLUMNS,
    BOOKRAG_ENTITY_LINK_COLUMNS,
    BOOKRAG_ENTITY_RELATION_COLUMNS,
    BOOKRAG_INSERT_BATCH_MAX_ROWS,
    BOOKRAG_INSERT_BATCH_MAX_SQL_CHARS,
    BOOKRAG_NODE_COLUMNS,
    BOOKRAG_RAW_COLUMNS,
)
from app.services.teradata_sql import (
    ExecuteSqlFn,
    _qualified_table_sql,
    _sanitize_teradata_text,
    _sql_literal,
    _sql_typed_literal,
)



def _fastload_rows(
    schema_name: str | None,
    table_name: str,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
) -> int:
    from teradataml import fastload

    frame = _rows_to_pandas_frame(rows, columns)
    fastload(
        frame,
        table_name=table_name,
        schema_name=schema_name,
        if_exists="append",
        index=False,
    )
    return len(rows)


def _rows_to_pandas_frame(rows: list[dict[str, Any]], columns: list[tuple[str, str]]):
    import pandas as pd

    column_names = [name for name, _ in columns]
    frame = pd.DataFrame([{name: row.get(name) for name in column_names} for row in rows], columns=column_names)
    for name, column_type in columns:
        normalized = column_type.upper()
        if "BYTEINT" in normalized:
            frame[name] = pd.array(frame[name], dtype="Int8")
        elif "INTEGER" in normalized:
            frame[name] = pd.array(frame[name], dtype="Int64")
    return frame


def _csv_safe_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _write_rows_csv(
    csv_stage_dir: Path | None,
    table_name: str,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
) -> str | None:
    if csv_stage_dir is None or not rows:
        return None
    csv_stage_dir.mkdir(parents=True, exist_ok=True)
    path = csv_stage_dir / f"{table_name}.csv"
    column_names = [name for name, _ in columns]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=column_names)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: _csv_safe_value(row.get(name)) for name in column_names})
    return str(path)


def _copy_rows_to_sql(
    schema_name: str | None,
    table_name: str,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
) -> int:
    from teradataml import copy_to_sql

    frame = _rows_to_pandas_frame(rows, columns)
    copy_to_sql(
        frame,
        table_name=table_name,
        schema_name=schema_name,
        if_exists="append",
        index=False,
        chunksize=min(max(len(rows), 1), 16383),
        match_column_order=True,
    )
    return len(rows)


def _single_insert_sql(
    qualified_table: str,
    column_names: list[str],
    row: dict[str, Any],
) -> str:
    quoted_cols = ", ".join(f'"{name}"' for name in column_names)
    values_sql = ", ".join(_sql_literal(row.get(col)) for col in column_names)
    return f"INSERT INTO {qualified_table} ({quoted_cols}) VALUES ({values_sql})"


def _batch_insert_sql(
    qualified_table: str,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
) -> str:
    quoted_cols = ", ".join(f'"{name}"' for name, _ in columns)
    select_sql: list[str] = []
    for row in rows:
        typed_values = ", ".join(_sql_typed_literal(row.get(name), column_type) for name, column_type in columns)
        select_sql.append(f"SELECT {typed_values}")
    return f"INSERT INTO {qualified_table} ({quoted_cols})\n" + "\nUNION ALL\n".join(select_sql)


def _iter_insert_batches(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    *,
    max_rows: int = BOOKRAG_INSERT_BATCH_MAX_ROWS,
    max_sql_chars: int = BOOKRAG_INSERT_BATCH_MAX_SQL_CHARS,
) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    current_batch: list[dict[str, Any]] = []
    current_size = 0
    per_row_overhead = len("SELECT ") + len("\nUNION ALL\n")

    for row in rows:
        row_sql_size = per_row_overhead
        for name, column_type in columns:
            row_sql_size += len(_sql_typed_literal(row.get(name), column_type)) + 2
        if current_batch and (len(current_batch) >= max_rows or current_size + row_sql_size > max_sql_chars):
            batches.append(current_batch)
            current_batch = []
            current_size = 0
        current_batch.append(row)
        current_size += row_sql_size

    if current_batch:
        batches.append(current_batch)
    return batches


def _metadata_dict(element: dict[str, Any]) -> dict[str, Any]:
    metadata = element.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _as_text(value: Any, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    text = _sanitize_teradata_text(str(value)).strip()
    if not text:
        return None
    if max_len is not None and len(text) > max_len:
        return text[:max_len]
    return text


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _type_name_from_dict(element: dict[str, Any]) -> str | None:
    return _as_text(element.get("type"), max_len=64)


def _element_id_from_dict(element: dict[str, Any]) -> str | None:
    return _as_text(element.get("element_id"), max_len=128)


def _stage_safe_stem(filename: str) -> str:
    stem = Path(str(filename or "document")).stem
    cleaned = re.sub(r"[^0-9A-Za-z._-]", "_", stem).strip("._")
    return cleaned or "document"


def write_bookrag_raw_stage_file(
    stage_dir: Path,
    filename: str,
    doc_id: str,
    payload: Any,
) -> Path:
    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_path = stage_dir / f"{_stage_safe_stem(filename)}_{doc_id}.json"
    with stage_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return stage_path


def load_bookrag_raw_stage_file(stage_path: Path) -> list[dict[str, Any]]:
    raw_text = stage_path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw_text)
    except Exception:
        elements: list[dict[str, Any]] = []
        for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception as ex:
                raise RuntimeError(f"Invalid BookRAG raw stage JSON at {stage_path}:{line_number}: {ex}") from ex
            if isinstance(item, dict):
                elements.append(item)
        return elements

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("elements", "output", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        list_values = [value for value in payload.values() if isinstance(value, list)]
        if len(list_values) == 1:
            return [item for item in list_values[0] if isinstance(item, dict)]
    raise RuntimeError(f"Unsupported BookRAG raw stage JSON format: {stage_path}")


def build_bookrag_document_row(
    *,
    doc_id: str,
    vector_store_name: str,
    workflow_id: str | None,
    workflow_name: str | None,
    job_id: str | None,
    processing_profile: str | None,
    filename: str,
    source_file: str,
    filetype: str | None,
    filesize_bytes: int | None,
) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "vector_store_name": _as_text(vector_store_name, max_len=255),
        "workflow_id": _as_text(workflow_id, max_len=64),
        "workflow_name": _as_text(workflow_name, max_len=255),
        "job_id": _as_text(job_id, max_len=64),
        "processing_profile": _as_text(processing_profile, max_len=100),
        "source_file": _as_text(source_file, max_len=2000),
        "filename": _as_text(filename, max_len=255),
        "filetype": _as_text(filetype, max_len=100),
        "filesize_bytes": filesize_bytes,
        "page_count": None,
        "language_hint": None,
        "created_at": None,
    }



def build_bookrag_raw_rows(
    *,
    doc_id: str,
    elements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ordinal_raw, element in enumerate(elements, start=1):
        if not isinstance(element, dict):
            continue
        metadata = _metadata_dict(element)
        rows.append(
            {
                "id": f"{doc_id}_{ordinal_raw}",
                "element_id": _element_id_from_dict(element),
                "ordinal_raw": ordinal_raw,
                "parent_id": _as_text(metadata.get("parent_id"), max_len=128),
                "type": _type_name_from_dict(element),
                "page_number": _as_int(metadata.get("page_number")),
                "category_depth": _as_int(metadata.get("category_depth")),
                "text": _as_text(element.get("text"), max_len=32000),
                "text_as_html": _as_text(metadata.get("text_as_html"), max_len=32000),
                "image_caption": _as_text(metadata.get("bookrag_image_caption"), max_len=4000),
                "image_context": _as_text(metadata.get("bookrag_image_context"), max_len=32000),
                "doc_id": doc_id,
            }
        )
    return rows


def _raw_row_to_element_dict(raw_row: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    parent_id = _as_text(raw_row.get("parent_id"), max_len=128)
    if parent_id:
        metadata["parent_id"] = parent_id
    page_number = _as_int(raw_row.get("page_number"))
    if page_number is not None:
        metadata["page_number"] = page_number
    category_depth = _as_int(raw_row.get("category_depth"))
    if category_depth is not None:
        metadata["category_depth"] = category_depth
    text_as_html = _as_text(raw_row.get("text_as_html"), max_len=32000)
    if text_as_html:
        metadata["text_as_html"] = text_as_html
    image_caption = _as_text(raw_row.get("image_caption"), max_len=4000)
    if image_caption:
        metadata["bookrag_image_caption"] = image_caption
    image_context = _as_text(raw_row.get("image_context"), max_len=32000)
    if image_context:
        metadata["bookrag_image_context"] = image_context

    element: dict[str, Any] = {}
    type_name = _as_text(raw_row.get("type"), max_len=64)
    if type_name:
        element["type"] = type_name
    element_id = _as_text(raw_row.get("element_id"), max_len=128)
    if element_id:
        element["element_id"] = element_id
    text_value = _as_text(raw_row.get("text"), max_len=32000)
    element["text"] = text_value or ""
    if metadata:
        element["metadata"] = metadata
    return element


def build_bookrag_chunk_rows_from_raw_rows(
    *,
    doc_id: str,
    filename: str,
    raw_rows: list[dict[str, Any]],
    max_characters: int,
    overlap: int,
    new_after_n_chars: int,
    combine_text_under_n_chars: int,
    multipage_sections: bool,
) -> list[dict[str, Any]]:
    sorted_rows = sorted(raw_rows, key=lambda row: (_as_int(row.get("ordinal_raw")) or 0,))
    raw_elements = [_raw_row_to_element_dict(row) for row in sorted_rows]
    return build_bookrag_chunk_rows_from_raw_elements(
        doc_id=doc_id,
        filename=filename,
        raw_elements=raw_elements,
        max_characters=max_characters,
        overlap=overlap,
        new_after_n_chars=new_after_n_chars,
        combine_text_under_n_chars=combine_text_under_n_chars,
        multipage_sections=multipage_sections,
    )


def _build_title_context_map(raw_elements: list[dict[str, Any]]) -> dict[str, dict[str, str | None]]:
    title_stack: list[str] = []
    context_map: dict[str, dict[str, str | None]] = {}
    for element in raw_elements:
        if not isinstance(element, dict):
            continue
        metadata = _metadata_dict(element)
        element_id = _element_id_from_dict(element)
        element_type = _type_name_from_dict(element)
        if element_type == "Title":
            title_text = _as_text(element.get("text"), max_len=1000)
            if title_text:
                depth = _as_int(metadata.get("category_depth"))
                if depth is None or depth < 1:
                    depth = len(title_stack) + 1 if title_stack else 1
                title_stack = title_stack[: max(depth - 1, 0)]
                title_stack.append(title_text)
        section_title = title_stack[-1] if title_stack else None
        title_path = " > ".join(title_stack) if title_stack else None
        if element_id:
            context_map[element_id] = {
                "section_title": section_title,
                "title_path": title_path,
            }
    return context_map


def _chunk_source_dicts(chunk: Any) -> list[dict[str, Any]]:
    metadata = getattr(chunk, "metadata", None)
    orig_elements = getattr(metadata, "orig_elements", None) if metadata is not None else None
    source_elements = list(orig_elements) if orig_elements else [chunk]
    source_dicts: list[dict[str, Any]] = []
    for element in source_elements:
        if hasattr(element, "to_dict"):
            element_dict = element.to_dict()
            if isinstance(element_dict, dict):
                source_dicts.append(element_dict)
    return source_dicts


def build_bookrag_chunk_rows_from_raw_elements(
    *,
    doc_id: str,
    filename: str,
    raw_elements: list[dict[str, Any]],
    max_characters: int,
    overlap: int,
    new_after_n_chars: int,
    combine_text_under_n_chars: int,
    multipage_sections: bool,
) -> list[dict[str, Any]]:
    from unstructured.chunking.title import chunk_by_title
    from unstructured.staging.base import elements_from_dicts

    title_context_map = _build_title_context_map(raw_elements)
    chunk_elements = chunk_by_title(
        elements_from_dicts(raw_elements),
        include_orig_elements=True,
        max_characters=max_characters,
        overlap=overlap,
        overlap_all=False,
        new_after_n_chars=new_after_n_chars,
        combine_text_under_n_chars=combine_text_under_n_chars,
        multipage_sections=multipage_sections,
    )

    rows: list[dict[str, Any]] = []
    last_section_title: str | None = None
    last_title_path: str | None = None
    for ordinal, chunk in enumerate(chunk_elements, start=1):
        if not hasattr(chunk, "to_dict"):
            continue
        chunk_dict = chunk.to_dict()
        chunk_text = _as_text(chunk_dict.get("text"), max_len=32000)
        source_dicts = _chunk_source_dicts(chunk)
        source_element_ids: list[str] = []
        source_types: set[str] = set()
        page_numbers: list[int] = []
        title_candidates: list[str] = []
        table_html: str | None = None

        for source in source_dicts:
            source_id = _element_id_from_dict(source)
            if source_id:
                source_element_ids.append(source_id)
                title_context = title_context_map.get(source_id) or {}
                if title_context.get("title_path"):
                    last_title_path = title_context.get("title_path")
                    last_section_title = title_context.get("section_title") or last_title_path
            source_type = _type_name_from_dict(source)
            if source_type:
                source_types.add(source_type)
                if source_type == "Title":
                    title_text = _as_text(source.get("text"), max_len=1000)
                    if title_text:
                        title_candidates.append(title_text)
            metadata = _metadata_dict(source)
            page_number = _as_int(metadata.get("page_number"))
            if page_number is not None:
                page_numbers.append(page_number)
            html_value = _as_text(metadata.get("text_as_html"), max_len=32000)
            if html_value and table_html is None:
                table_html = html_value

        section_title = title_candidates[0] if title_candidates else last_section_title
        title_path = last_title_path
        if title_candidates:
            title_path = " > ".join(title_candidates)
            last_title_path = title_path
            last_section_title = section_title

        if title_path and chunk_text and not chunk_text.startswith(title_path):
            text_for_embedding = _as_text(f"{title_path}\n\n{chunk_text}", max_len=32000)
        else:
            text_for_embedding = chunk_text

        chunk_type = "text"
        if "Table" in source_types:
            chunk_type = "table"
        elif "Image" in source_types:
            chunk_type = "image"

        image_caption = None
        image_context = None
        if chunk_type == "image":
            image_caption = section_title
            image_context = chunk_text

        rows.append(
            {
                "chunk_id": uuid.uuid4().hex,
                "doc_id": doc_id,
                "filename": filename,
                "ordinal": ordinal,
                "chunk_type": chunk_type,
                "page_start": min(page_numbers) if page_numbers else None,
                "page_end": max(page_numbers) if page_numbers else None,
                "section_title": _as_text(section_title, max_len=2000),
                "title_path": _as_text(title_path, max_len=4000),
                "source_element_ids": _as_text(json.dumps(source_element_ids, ensure_ascii=False), max_len=32000),
                "text": chunk_text,
                "text_for_embedding": text_for_embedding,
                "text_as_html": table_html,
                "table_html": table_html,
                "image_caption": _as_text(image_caption, max_len=4000),
                "image_context": _as_text(image_context, max_len=32000),
            }
        )
    return rows


def _supports_fastload(columns: list[tuple[str, str]]) -> bool:
    for _, column_type in columns:
        normalized = column_type.upper()
        if "CLOB" in normalized or "BLOB" in normalized:
            return False
    return True


def _record_csv_future_result(csv_future, stats: dict[str, int] | None) -> None:
    csv_file = None
    try:
        csv_file = csv_future.result()
    except Exception:
        if stats is not None:
            stats["csv_write_failures"] += 1
    if stats is not None and csv_file and csv_file not in stats["csv_files"]:
        stats["csv_files"].append(csv_file)


def _insert_rows(
    schema_name: str | None,
    table_name: str,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, int] | None = None,
    csv_executor: ThreadPoolExecutor | None = None,
    pending_csv_futures: list[Any] | None = None,
) -> int:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    if not rows:
        return 0
    qualified_table = _qualified_table_sql(schema_name, table_name)
    column_names = [name for name, _ in columns]
    inserted = 0
    active_csv_executor = csv_executor
    owned_csv_executor = False
    csv_future = None

    if stats is not None:
        stats.setdefault("fastload_calls", 0)
        stats.setdefault("fastload_rows", 0)
        stats.setdefault("fastload_fallbacks", 0)
        stats.setdefault("fastload_skipped", 0)
        stats.setdefault("copy_to_sql_calls", 0)
        stats.setdefault("copy_to_sql_rows", 0)
        stats.setdefault("copy_to_sql_fallbacks", 0)
        stats.setdefault("single_row_statements", 0)
        stats.setdefault("batch_statements", 0)
        stats.setdefault("batch_rows", 0)
        stats.setdefault("fallback_rows", 0)
        stats.setdefault("fallback_batches", 0)
        stats.setdefault("csv_files", [])
        stats.setdefault("csv_write_failures", 0)
        stats.setdefault("csv_parallel_calls", 0)

    if csv_stage_dir is not None:
        if active_csv_executor is None:
            active_csv_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bookrag-csv")
            owned_csv_executor = True
        csv_future = active_csv_executor.submit(_write_rows_csv, csv_stage_dir, table_name, rows, columns)
        if stats is not None:
            stats["csv_parallel_calls"] += 1

    try:
        if _supports_fastload(columns):
            try:
                inserted += _fastload_rows(schema_name, table_name, rows, columns)
                if stats is not None:
                    stats["fastload_calls"] += 1
                    stats["fastload_rows"] += len(rows)
            except Exception:
                if stats is not None:
                    stats["fastload_fallbacks"] += 1
        elif stats is not None:
            stats["fastload_skipped"] += 1

        if inserted == 0 and len(rows) > 1:
            try:
                inserted += _copy_rows_to_sql(schema_name, table_name, rows, columns)
                if stats is not None:
                    stats["copy_to_sql_calls"] += 1
                    stats["copy_to_sql_rows"] += len(rows)
            except Exception:
                if stats is not None:
                    stats["copy_to_sql_fallbacks"] += 1

        if inserted == 0:
            for batch in _iter_insert_batches(rows, columns):
                if len(batch) == 1:
                    execute_sql_fn(_single_insert_sql(qualified_table, column_names, batch[0]))
                    inserted += 1
                    if stats is not None:
                        stats["single_row_statements"] += 1
                    continue
                try:
                    execute_sql_fn(_batch_insert_sql(qualified_table, batch, columns))
                    inserted += len(batch)
                    if stats is not None:
                        stats["batch_statements"] += 1
                        stats["batch_rows"] += len(batch)
                except Exception:
                    if stats is not None:
                        stats["fallback_batches"] += 1
                        stats["fallback_rows"] += len(batch)
                    for row in batch:
                        execute_sql_fn(_single_insert_sql(qualified_table, column_names, row))
                        inserted += 1
                        if stats is not None:
                            stats["single_row_statements"] += 1
    finally:
        if csv_future is not None:
            if pending_csv_futures is not None and not owned_csv_executor:
                pending_csv_futures.append(csv_future)
            else:
                try:
                    _record_csv_future_result(csv_future, stats)
                finally:
                    if owned_csv_executor and active_csv_executor is not None:
                        active_csv_executor.shutdown(wait=False)
    return inserted


def persist_bookrag_tree(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    document_row: dict[str, Any],
    blocks: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    entity_links: list[dict[str, Any]],
    entity_relations: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, int] | None = None,
) -> int:
    return persist_bookrag_dataset(
        schema_name=schema_name,
        table_targets=table_targets,
        document_rows=[document_row],
        blocks=blocks,
        nodes=nodes,
        entities=entities,
        entity_links=entity_links,
        entity_relations=entity_relations,
        execute_sql_fn=execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
    )


def persist_bookrag_dataset(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    document_rows: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    entity_links: list[dict[str, Any]],
    entity_relations: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, int] | None = None,
) -> int:
    inserted = 0
    csv_executor: ThreadPoolExecutor | None = None
    pending_csv_futures: list[Any] = []
    if csv_stage_dir is not None:
        csv_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bookrag-csv")
    try:
        inserted += _insert_rows(
            schema_name,
            table_targets["documents"],
            document_rows,
            BOOKRAG_DOCUMENT_COLUMNS,
            execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=stats,
            csv_executor=csv_executor,
            pending_csv_futures=pending_csv_futures,
        )
        inserted += _insert_rows(
            schema_name,
            table_targets["nodes"],
            nodes,
            BOOKRAG_NODE_COLUMNS,
            execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=stats,
            csv_executor=csv_executor,
            pending_csv_futures=pending_csv_futures,
        )
        inserted += _insert_rows(
            schema_name,
            table_targets["entities"],
            entities,
            BOOKRAG_ENTITY_COLUMNS,
            execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=stats,
            csv_executor=csv_executor,
            pending_csv_futures=pending_csv_futures,
        )
        inserted += _insert_rows(
            schema_name,
            table_targets["entity_links"],
            entity_links,
            BOOKRAG_ENTITY_LINK_COLUMNS,
            execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=stats,
            csv_executor=csv_executor,
            pending_csv_futures=pending_csv_futures,
        )
        inserted += _insert_rows(
            schema_name,
            table_targets["entity_relations"],
            entity_relations,
            BOOKRAG_ENTITY_RELATION_COLUMNS,
            execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=stats,
            csv_executor=csv_executor,
            pending_csv_futures=pending_csv_futures,
        )
        inserted += _insert_rows(
            schema_name,
            table_targets["blocks"],
            blocks,
            BOOKRAG_BLOCK_COLUMNS,
            execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=stats,
            csv_executor=csv_executor,
            pending_csv_futures=pending_csv_futures,
        )
    finally:
        for csv_future in pending_csv_futures:
            _record_csv_future_result(csv_future, stats)
        if csv_executor is not None:
            csv_executor.shutdown(wait=False)
    return inserted


def persist_bookrag_blocks(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    blocks: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, int] | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["blocks"],
        blocks,
        BOOKRAG_BLOCK_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
    )


def persist_bookrag_nodes(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    nodes: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, int] | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["nodes"],
        nodes,
        BOOKRAG_NODE_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
    )


def persist_bookrag_entities(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    entities: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, int] | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["entities"],
        entities,
        BOOKRAG_ENTITY_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
    )


def persist_bookrag_entity_links(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    entity_links: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, int] | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["entity_links"],
        entity_links,
        BOOKRAG_ENTITY_LINK_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
    )


def persist_bookrag_entity_relations(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    entity_relations: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, int] | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["entity_relations"],
        entity_relations,
        BOOKRAG_ENTITY_RELATION_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
    )


def persist_bookrag_documents(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    rows: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, int] | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["documents"],
        rows,
        BOOKRAG_DOCUMENT_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
    )


def persist_bookrag_raw_rows(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    rows: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, int] | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["raw"],
        rows,
        BOOKRAG_RAW_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
    )


def persist_bookrag_chunks(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    rows: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, int] | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["chunks"],
        rows,
        BOOKRAG_CHUNK_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
    )
