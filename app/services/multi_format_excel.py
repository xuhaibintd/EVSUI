from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any, Callable

from app.services.unstructured_runtime import EXCEL_EXTENSIONS


ElementRowBuilder = Callable[..., dict[str, Any] | None]


def is_excel_file(source: Path) -> bool:
    return source.suffix.lower() in EXCEL_EXTENSIONS


def excel_column_name(index: int) -> str:
    label = ""
    value = max(1, int(index))
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        label = chr(65 + remainder) + label
    return label or "A"


def normalize_excel_cell_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, "g")
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            return str(value.isoformat(sep=" "))
        except TypeError:
            try:
                return str(value.isoformat())
            except Exception:
                pass
    return str(value).strip()


def trim_excel_cells(values: list[str]) -> list[str]:
    trimmed = list(values)
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    return trimmed


def should_use_excel_headers(rows: list[tuple[int, list[str]]]) -> bool:
    if len(rows) < 2:
        return False
    non_empty = [value for value in rows[0][1] if value]
    if len(non_empty) < 2:
        return False
    mostly_label_like = sum(1 for value in non_empty if not any(char.isdigit() for char in value[:24]))
    return mostly_label_like >= max(1, len(non_empty) // 2)


def build_excel_headers(values: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    headers: list[str] = []
    for index, value in enumerate(values, start=1):
        candidate = re.sub(r"\s+", " ", value).strip() or f"Column {excel_column_name(index)}"
        count = seen.get(candidate, 0) + 1
        seen[candidate] = count
        headers.append(f"{candidate} ({count})" if count > 1 else candidate)
    return headers


def split_text_with_overlap(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    if max_chars <= 0 or len(normalized) <= max_chars:
        return [normalized]

    overlap_chars = max(0, min(overlap_chars, max_chars - 1))
    parts: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + max_chars)
        if end < len(normalized):
            newline_break = normalized.rfind("\n", start, end)
            space_break = normalized.rfind(" ", start, end)
            break_at = max(newline_break, space_break)
            if break_at > start + (max_chars // 2):
                end = break_at
        piece = normalized[start:end].strip()
        if piece:
            parts.append(piece)
        if end >= len(normalized):
            break
        start = max(end - overlap_chars, start + 1)
        while start < len(normalized) and normalized[start].isspace():
            start += 1
    return parts or [normalized[:max_chars].strip()]


def read_excel_sheet_rows(source: Path) -> list[tuple[str, list[tuple[int, list[str]]]]]:
    import pandas as pd

    workbook = pd.read_excel(source, sheet_name=None, header=None, dtype=object)
    sheets: list[tuple[str, list[tuple[int, list[str]]]]] = []
    for sheet_name, frame in workbook.items():
        rows: list[tuple[int, list[str]]] = []
        for row_number, row in enumerate(frame.itertuples(index=False, name=None), start=1):
            values = ["" if pd.isna(cell) else normalize_excel_cell_value(cell) for cell in row]
            values = trim_excel_cells(values)
            if any(values):
                rows.append((row_number, values))
        if rows:
            sheets.append((str(sheet_name), rows))
    return sheets


def partition_excel_chunks(
    source: Path,
    *,
    chunk_size: int,
    chunk_overlap: int,
    element_to_chunk_row: ElementRowBuilder,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    sheet_rows = read_excel_sheet_rows(source)
    raw_elements: list[dict[str, Any]] = []
    table_rows: list[dict[str, Any]] = []
    sheet_names: list[str] = []
    logical_row_count = 0
    chunk_sequence = 0

    for sheet_name, rows in sheet_rows:
        sheet_names.append(sheet_name)
        use_headers = should_use_excel_headers(rows)
        headers = build_excel_headers(rows[0][1]) if use_headers else []
        data_rows = rows[1:] if use_headers and len(rows) > 1 else rows
        for row_number, values in data_rows:
            logical_row_count += 1
            parts = [
                f"{headers[index - 1] if index - 1 < len(headers) else f'Column {excel_column_name(index)}'}: {value}"
                for index, value in enumerate(values, start=1)
                if value
            ]
            if not parts:
                continue

            full_text = f"Workbook: {source.name}\nSheet: {sheet_name}\nRow: {row_number}\n" + "\n".join(parts)
            record_id = uuid.uuid4().hex
            metadata = {
                "record_id": record_id,
                "filename": source.name,
                "file_directory": str(source.parent),
                "filetype": content_type,
                "record_locator": f"{source.name}#sheet={sheet_name}#row={row_number}",
                "sheet_name": sheet_name,
                "row_number": row_number,
                "row_kind": "excel_structured",
            }
            raw_elements.append(
                {
                    "id": record_id,
                    "element_id": record_id,
                    "type": "TableRow",
                    "text": full_text,
                    "metadata": metadata,
                }
            )

            segments = split_text_with_overlap(full_text, chunk_size, chunk_overlap)
            for segment_index, segment in enumerate(segments, start=1):
                element_metadata = dict(metadata)
                if len(segments) > 1:
                    element_metadata["segment_index"] = segment_index
                    element_metadata["segment_total"] = len(segments)
                chunk_sequence += 1
                element_id = uuid.uuid4().hex
                row = element_to_chunk_row(
                    {
                        "id": element_id,
                        "element_id": element_id,
                        "type": "TableRow",
                        "text": segment,
                        "metadata": element_metadata,
                    },
                    src=source,
                    content_type=content_type,
                    row_sequence=chunk_sequence,
                )
                if row:
                    table_rows.append(row)

    return table_rows, raw_elements, {
        "mode": "excel-structured",
        "file_name": source.name,
        "content_type": content_type,
        "sheet_names": sheet_names,
        "sheet_count": len(sheet_names),
        "logical_row_count": logical_row_count,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
    }
