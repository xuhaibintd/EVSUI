from __future__ import annotations

import csv
import json
import os
import re
import time
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
    BOOKRAG_NODE_COLUMNS,
    BOOKRAG_RAW_COLUMNS,
)
from app.services.teradata_sql import (
    ExecuteSqlFn,
    _qualified_table_sql,
    _sanitize_teradata_text,
)



BOOKRAG_CSV_FASTLOAD_MIN_ROWS_DEFAULT = 100000

BOOKRAG_TABLE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "documents": BOOKRAG_DOCUMENT_COLUMNS,
    "raw": BOOKRAG_RAW_COLUMNS,
    "blocks": BOOKRAG_BLOCK_COLUMNS,
    "nodes": BOOKRAG_NODE_COLUMNS,
    "entities": BOOKRAG_ENTITY_COLUMNS,
    "entity_links": BOOKRAG_ENTITY_LINK_COLUMNS,
    "entity_relations": BOOKRAG_ENTITY_RELATION_COLUMNS,
    "chunks": BOOKRAG_CHUNK_COLUMNS,
}


def _resolve_csv_fastload_min_rows() -> int:
    raw_value = str(
        os.getenv(
            "BOOKRAG_CSV_FASTLOAD_MIN_ROWS",
            str(BOOKRAG_CSV_FASTLOAD_MIN_ROWS_DEFAULT),
        )
        or ""
    ).strip()
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return BOOKRAG_CSV_FASTLOAD_MIN_ROWS_DEFAULT




def _record_elapsed(stats: dict[str, Any] | None, key: str, started_at: float) -> None:
    if stats is None:
        return
    elapsed = max(0.0, time.perf_counter() - started_at)
    stats[key] = round(float(stats.get(key, 0.0) or 0.0) + elapsed, 6)


def _initialize_insert_stats(
    stats: dict[str, Any] | None,
    *,
    table_name: str,
    row_count: int,
    add_input_rows: bool,
) -> None:
    if stats is None:
        return
    stats["insert_mode"] = "native_csv"
    stats["table_name"] = table_name
    if add_input_rows:
        stats["input_rows"] = int(stats.get("input_rows", 0) or 0) + row_count
    else:
        stats.setdefault("input_rows", row_count)
    stats.setdefault("csv_files", [])
    stats.setdefault("csv_write_seconds", 0.0)
    stats.setdefault("csv_flag_characters_replaced", 0)
    stats.setdefault("csv_unsupported_characters_removed", 0)
    stats.setdefault("csv_truncated_characters", 0)
    stats.setdefault("csv_bytes", 0)
    stats.setdefault("native_csv_calls", 0)
    stats.setdefault("native_csv_rows", 0)
    stats.setdefault("native_csv_batch_calls", 0)
    stats.setdefault("native_csv_fastload_calls", 0)
    stats.setdefault("native_csv_load_seconds", 0.0)
    stats.setdefault("insert_total_seconds", 0.0)


def _replace_flag_emoji(text: str) -> tuple[str, int]:
    """Replace regional-indicator flag pairs with searchable ASCII labels."""
    output: list[str] = []
    replaced = 0
    index = 0
    while index < len(text):
        first = ord(text[index])
        if 0x1F1E6 <= first <= 0x1F1FF and index + 1 < len(text):
            second = ord(text[index + 1])
            if 0x1F1E6 <= second <= 0x1F1FF:
                country_code = chr(ord("A") + first - 0x1F1E6) + chr(ord("A") + second - 0x1F1E6)
                output.append(f"[{country_code}]")
                replaced += 2
                index += 2
                continue
        output.append(text[index])
        index += 1
    return "".join(output), replaced


def _csv_safe_value(value: Any) -> tuple[str, int, int]:
    if value is None:
        return "", 0, 0
    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    with_flags, flag_characters = _replace_flag_emoji(text)
    normalized = _sanitize_teradata_text(with_flags)
    removed_characters = max(0, len(with_flags) - len(normalized))
    return normalized, flag_characters, removed_characters


def _column_text_limit(column_type: str) -> int | None:
    match = re.search(r"\b(?:VAR)?CHAR\((\d+)\)", str(column_type), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _write_rows_csv(
    csv_stage_dir: Path | None,
    table_name: str,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    stats: dict[str, Any] | None = None,
) -> str | None:
    if csv_stage_dir is None or not rows:
        return None
    csv_stage_dir.mkdir(parents=True, exist_ok=True)
    path = csv_stage_dir / f"{table_name}.csv"
    if path.exists():
        for index in range(2, 100000):
            candidate = csv_stage_dir / f"{table_name}_{index}.csv"
            if not candidate.exists():
                path = candidate
                break
    column_names = [name for name, _ in columns]
    flag_characters = 0
    unsupported_characters = 0
    truncated_characters = 0
    started_at = time.perf_counter()
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=column_names)
        writer.writeheader()
        for row in rows:
            csv_row: dict[str, str] = {}
            for name, column_type in columns:
                normalized, replaced_flags, removed_unsupported = _csv_safe_value(row.get(name))
                text_limit = _column_text_limit(column_type)
                if text_limit is not None and len(normalized) > text_limit:
                    truncated_characters += len(normalized) - text_limit
                    normalized = normalized[:text_limit]
                csv_row[name] = normalized
                flag_characters += replaced_flags
                unsupported_characters += removed_unsupported
            writer.writerow(csv_row)
    if stats is not None:
        _record_elapsed(stats, "csv_write_seconds", started_at)
        stats["csv_flag_characters_replaced"] = int(stats.get("csv_flag_characters_replaced", 0) or 0) + flag_characters
        stats["csv_unsupported_characters_removed"] = int(stats.get("csv_unsupported_characters_removed", 0) or 0) + unsupported_characters
        stats["csv_truncated_characters"] = int(stats.get("csv_truncated_characters", 0) or 0) + truncated_characters
        stats["csv_bytes"] = int(stats.get("csv_bytes", 0) or 0) + path.stat().st_size
    return str(path)


def _csv_header(csv_path: str) -> list[str]:
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle), None)
    if not header:
        raise RuntimeError(f"BookRAG CSV has no header: {csv_path}")
    return [str(name) for name in header]


def _load_csv_to_teradata(
    schema_name: str | None,
    table_name: str,
    csv_path: str,
    row_count: int,
    stats: dict[str, Any] | None = None,
) -> int:
    """Load one complete CSV with native Teradata driver protocols."""
    use_fastload = row_count >= _resolve_csv_fastload_min_rows()
    resolved_path = str(Path(csv_path).resolve())
    if any(character in resolved_path for character in "\r\n{}"):
        raise RuntimeError(f"Unsupported character in BookRAG CSV path: {resolved_path!r}")

    load_started = time.perf_counter()
    try:
        if use_fastload:
            from teradataml import read_csv

            result = read_csv(
                filepath=resolved_path,
                table_name=table_name,
                schema_name=schema_name,
                if_exists="append",
                use_fastload=True,
                catch_errors_warnings=True,
            )
            if isinstance(result, tuple) and len(result) > 1:
                details = result[1]
                errors = details.get("errors_dataframe") if isinstance(details, dict) else None
                if errors is not None and not errors.empty:
                    raise RuntimeError(f"Teradata FastLoadCSV rejected {len(errors.index)} CSV row(s).")
        else:
            from teradataml import get_connection

            qualified_table = _qualified_table_sql(schema_name, table_name)
            placeholders = ", ".join("?" for _ in range(len(_csv_header(csv_path))))
            statement = f"{{fn teradata_read_csv({resolved_path})}}INSERT INTO {qualified_table} VALUES ({placeholders})"
            driver_connection = get_connection().connection.driver_connection
            cursor = driver_connection.cursor()
            try:
                cursor.execute(statement)
            finally:
                cursor.close()
    finally:
        _record_elapsed(stats, "native_csv_load_seconds", load_started)

    if stats is not None:
        stats["native_csv_calls"] = int(stats.get("native_csv_calls", 0) or 0) + 1
        stats["native_csv_rows"] = int(stats.get("native_csv_rows", 0) or 0) + row_count
        counter = "native_csv_fastload_calls" if use_fastload else "native_csv_batch_calls"
        stats[counter] = int(stats.get(counter, 0) or 0) + 1
    return row_count


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
    page_count: int | None,
    language_hint: str | None,
    created_at: str | None,
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
        "page_count": _as_int(page_count),
        "language_hint": _as_text(language_hint, max_len=200),
        "created_at": _as_text(created_at, max_len=50),
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


def _insert_rows(
    schema_name: str | None,
    table_name: str,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, Any] | None = None,
    prepared_csv_path: str | None = None,
) -> int:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    if not rows:
        return 0
    if csv_stage_dir is None and prepared_csv_path is None:
        raise RuntimeError("BookRAG native CSV loading requires csv_stage_dir.")

    insert_started = time.perf_counter()
    _initialize_insert_stats(
        stats,
        table_name=table_name,
        row_count=len(rows),
        add_input_rows=prepared_csv_path is None,
    )

    try:
        csv_path = prepared_csv_path
        if csv_path is None:
            csv_path = _write_rows_csv(
                csv_stage_dir,
                table_name,
                rows,
                columns,
                stats=stats,
            )
        if not csv_path:
            raise RuntimeError(f"BookRAG CSV generation produced no file for {table_name}.")
        if stats is not None and csv_path not in stats["csv_files"]:
            stats["csv_files"].append(csv_path)
        return _load_csv_to_teradata(
            schema_name,
            table_name,
            csv_path,
            len(rows),
            stats=stats,
        )
    except Exception as ex:
        if stats is not None:
            stats["native_csv_last_error"] = _sanitize_teradata_text(str(ex))[:2000]
        raise
    finally:
        _record_elapsed(stats, "insert_total_seconds", insert_started)


def prepare_bookrag_table_csv(
    *,
    table_key: str,
    table_targets: dict[str, str],
    rows: list[dict[str, Any]],
    csv_stage_dir: Path,
    stats: dict[str, Any] | None = None,
) -> str | None:
    """Generate one existing BookRAG table CSV without loading it."""
    if not rows:
        return None
    try:
        columns = BOOKRAG_TABLE_COLUMNS[table_key]
        table_name = table_targets[table_key]
    except KeyError as ex:
        raise RuntimeError(f"Unsupported BookRAG CSV table key: {table_key}") from ex

    _initialize_insert_stats(
        stats,
        table_name=table_name,
        row_count=len(rows),
        add_input_rows=True,
    )
    csv_path = _write_rows_csv(
        csv_stage_dir,
        table_name,
        rows,
        columns,
        stats=stats,
    )
    if not csv_path:
        raise RuntimeError(f"BookRAG CSV generation produced no file for {table_name}.")
    if stats is not None:
        if csv_path not in stats["csv_files"]:
            stats["csv_files"].append(csv_path)
        stats["insert_total_seconds"] = round(float(stats.get("csv_write_seconds", 0.0) or 0.0), 6)
    return csv_path


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
    stats: dict[str, Any] | None = None,
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
    stats: dict[str, Any] | None = None,
) -> int:
    inserted = 0
    datasets = (
        ("documents", document_rows, BOOKRAG_DOCUMENT_COLUMNS),
        ("nodes", nodes, BOOKRAG_NODE_COLUMNS),
        ("entities", entities, BOOKRAG_ENTITY_COLUMNS),
        ("entity_links", entity_links, BOOKRAG_ENTITY_LINK_COLUMNS),
        ("entity_relations", entity_relations, BOOKRAG_ENTITY_RELATION_COLUMNS),
        ("blocks", blocks, BOOKRAG_BLOCK_COLUMNS),
    )
    for table_key, rows, columns in datasets:
        inserted += _insert_rows(
            schema_name,
            table_targets[table_key],
            rows,
            columns,
            execute_sql_fn,
            csv_stage_dir=csv_stage_dir,
            stats=stats,
        )
    return inserted


def persist_bookrag_blocks(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    blocks: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, Any] | None = None,
    prepared_csv_path: str | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["blocks"],
        blocks,
        BOOKRAG_BLOCK_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
        prepared_csv_path=prepared_csv_path,
    )


def persist_bookrag_nodes(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    nodes: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, Any] | None = None,
    prepared_csv_path: str | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["nodes"],
        nodes,
        BOOKRAG_NODE_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
        prepared_csv_path=prepared_csv_path,
    )


def persist_bookrag_entities(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    entities: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, Any] | None = None,
    prepared_csv_path: str | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["entities"],
        entities,
        BOOKRAG_ENTITY_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
        prepared_csv_path=prepared_csv_path,
    )


def persist_bookrag_entity_links(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    entity_links: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, Any] | None = None,
    prepared_csv_path: str | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["entity_links"],
        entity_links,
        BOOKRAG_ENTITY_LINK_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
        prepared_csv_path=prepared_csv_path,
    )


def persist_bookrag_entity_relations(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    entity_relations: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, Any] | None = None,
    prepared_csv_path: str | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["entity_relations"],
        entity_relations,
        BOOKRAG_ENTITY_RELATION_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
        prepared_csv_path=prepared_csv_path,
    )


def persist_bookrag_documents(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    rows: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, Any] | None = None,
    prepared_csv_path: str | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["documents"],
        rows,
        BOOKRAG_DOCUMENT_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
        prepared_csv_path=prepared_csv_path,
    )


def persist_bookrag_raw_rows(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    rows: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, Any] | None = None,
    prepared_csv_path: str | None = None,
) -> int:
    return _insert_rows(
        schema_name,
        table_targets["raw"],
        rows,
        BOOKRAG_RAW_COLUMNS,
        execute_sql_fn,
        csv_stage_dir=csv_stage_dir,
        stats=stats,
        prepared_csv_path=prepared_csv_path,
    )


def persist_bookrag_chunks(
    *,
    schema_name: str | None,
    table_targets: dict[str, str],
    rows: list[dict[str, Any]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, Any] | None = None,
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
