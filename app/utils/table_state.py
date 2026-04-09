from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Callable

TERADATA_IDENTIFIER_MAX_LEN = 30


def normalize_header_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def vs_name_column_index(headers: list[str]) -> int:
    def _norm(value: str) -> str:
        return str(value).strip().lower().replace(" ", "").replace("-", "")

    for idx, column in enumerate(headers):
        col_key = _norm(str(column))
        if (
            col_key in {"vs_name", "vsname", "vector_store_name", "vectorstorename"}
            or ("vs" in col_key and "name" in col_key)
            or ("vector" in col_key and "name" in col_key)
        ):
            return idx
    return -1


def find_vs_row_by_name(headers: list[str], rows: list[list[str]], vs_name: str) -> list[str] | None:
    idx = vs_name_column_index(headers)
    if idx < 0:
        return None
    target = normalize_header_key(vs_name)
    if not target:
        return None
    for row in rows:
        if idx < len(row) and normalize_header_key(row[idx]) == target:
            return row
    return None


def find_list_row_for_vs(state: dict, vs_name: str) -> tuple[list[str], list[str] | None]:
    headers = list(state.get("list_columns", []) or [])
    rows = list(state.get("list_rows", []) or [])
    return headers, find_vs_row_by_name(headers, rows, vs_name)


def destroy_output_indicates_failure(raw_output: str) -> bool:
    text = str(raw_output or "").strip().lower()
    if not text or text == "none":
        return False
    if "destroy failed" in text:
        return True
    if "responsecode" in text and any(code in text for code in ("400", "401", "403", "404", "409", "500", "503")):
        return True
    if any(marker in text for marker in ("error", "exception", "traceback")):
        return True
    return False


def row_value_by_header(headers: list[str], row: list[str], key_markers: tuple[str, ...]) -> str:
    for idx, header in enumerate(headers):
        if idx >= len(row):
            continue
        normalized = normalize_header_key(header)
        if any(marker in normalized for marker in key_markers):
            return str(row[idx]).strip()
    return ""


def is_content_based_vs_row(headers: list[str], row: list[str] | None) -> bool:
    if not row:
        return False
    type_value = row_value_by_header(headers, row, ("type", "mode", "storetype", "vectorstoretype"))
    if type_value:
        low = type_value.lower()
        if "content" in low and "based" in low:
            return True
    for cell in row:
        low = str(cell).strip().lower()
        if "content" in low and "based" in low:
            return True
    return False


def base_vector_store_name_for_chunk(raw_name: str) -> str:
    name = str(raw_name or "").strip()
    if not name:
        return ""
    lowered = name.lower()
    for suffix in ("_unstructured", "_unstractured"):
        if lowered.endswith(suffix):
            trimmed = name[: -len(suffix)].strip().strip("_")
            return trimmed or name
    return name


def sanitize_teradata_identifier(raw: str, fallback: str, allow_empty: bool = False) -> str:
    candidate = re.sub(r"[^0-9A-Za-z_]", "_", str(raw or "").strip())
    candidate = re.sub(r"_+", "_", candidate).strip("_")
    if not candidate:
        return "" if allow_empty else fallback
    if candidate[0].isdigit():
        candidate = f"t_{candidate}"
    if len(candidate) <= TERADATA_IDENTIFIER_MAX_LEN:
        return candidate
    digest = hashlib.sha1(candidate.encode("utf-8")).hexdigest()[:6]
    keep = max(1, TERADATA_IDENTIFIER_MAX_LEN - len(digest) - 1)
    return f"{candidate[:keep]}_{digest}"


def chunk_table_sql_for_vs(headers: list[str], row: list[str] | None, vs_name: str, state: dict) -> tuple[str, str, str]:
    schema_from_row = row_value_by_header(headers, row or [], ("database", "schema", "targetdatabase"))
    schema_hint = schema_from_row or str(state.get("params", {}).get("username", "")).strip()
    schema_name = sanitize_teradata_identifier(schema_hint, fallback="", allow_empty=True)
    base_name = base_vector_store_name_for_chunk(vs_name) or vs_name
    table_name = sanitize_teradata_identifier(f"{base_name}_unstructured", fallback="unstructured")
    if schema_name:
        qualified_sql = f'"{schema_name}"."{table_name}"'
    else:
        qualified_sql = f'"{table_name}"'
    return schema_name, table_name, qualified_sql


def format_preview(value: Any, max_chars: int | None = 900) -> str:
    if value is None:
        return "None"
    if hasattr(value, "columns") and hasattr(value, "head") and hasattr(value, "shape"):
        try:
            total_rows = int(value.shape[0])
            if max_chars is None:
                try:
                    text = value.to_string(index=False, max_colwidth=48)
                except TypeError:
                    text = value.to_string(index=False)
                text = f"rows={total_rows}\n{text}"
            else:
                preview_rows = min(total_rows, 10)
                preview_df = value.head(preview_rows)
                try:
                    text = preview_df.to_string(index=False, max_colwidth=48)
                except TypeError:
                    text = preview_df.to_string(index=False)
                if total_rows > preview_rows:
                    text = f"rows={total_rows}\n{text}\n... ({total_rows - preview_rows} more rows)"
                else:
                    text = f"rows={total_rows}\n{text}"
        except Exception:
            text = str(value)
    elif hasattr(value, "to_string"):
        try:
            text = value.to_string(index=False)
        except Exception:
            text = str(value)
    elif isinstance(value, (dict, list, tuple)):
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            text = str(value)
    else:
        text = str(value)
    text = text.strip()
    if max_chars is not None and len(text) > max_chars:
        return f"{text[:max_chars]}... (truncated)"
    return text


def preview_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return str(value)


def split_table_line(line: str) -> list[str]:
    return [chunk for chunk in re.split(r"\s{2,}", line.strip()) if chunk]


def table_from_text_preview(text: str) -> tuple[list[str], list[list[str]]]:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return [], []

    header = split_table_line(lines[0])
    if len(header) < 2:
        return [], []

    rows: list[list[str]] = []
    for idx, line in enumerate(lines[1:], start=1):
        parts = split_table_line(line)
        if not parts:
            continue
        if re.fullmatch(r"\d+", parts[0]):
            parts = parts[1:]
        if len(parts) < len(header):
            parts = parts + [""] * (len(header) - len(parts))
        elif len(parts) > len(header):
            parts = parts[: len(header) - 1] + [" ".join(parts[len(header) - 1 :])]
        rows.append([str(idx)] + parts)
    if not rows:
        return [], []
    return ["#"] + header, rows


def table_from_result(value: Any) -> tuple[list[str], list[list[str]]]:
    candidate = value
    for attr in ("to_pandas", "to_dataframe"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                converted = fn()
                if converted is not None:
                    candidate = converted
                    break
            except Exception:
                pass

    columns: list[str] = []
    rows: list[list[str]] = []

    if hasattr(candidate, "columns"):
        try:
            columns = [str(col) for col in list(candidate.columns)]
        except Exception:
            columns = []
        if columns:
            to_dict_fn = getattr(candidate, "to_dict", None)
            if callable(to_dict_fn):
                records = None
                try:
                    records = to_dict_fn(orient="records")
                except TypeError:
                    try:
                        records = to_dict_fn()
                    except Exception:
                        records = None
                except Exception:
                    records = None
                if isinstance(records, list):
                    for idx, item in enumerate(records, start=1):
                        if isinstance(item, dict):
                            row = [str(idx)] + [preview_cell(item.get(col)) for col in columns]
                        else:
                            row = [str(idx), preview_cell(item)]
                        rows.append(row)
                    return ["#"] + columns, rows

            itertuples_fn = getattr(candidate, "itertuples", None)
            if callable(itertuples_fn):
                try:
                    for idx, item in enumerate(itertuples_fn(index=False, name=None), start=1):
                        row = [str(idx)] + [preview_cell(cell) for cell in tuple(item)]
                        rows.append(row)
                    if rows:
                        return ["#"] + columns, rows
                except Exception:
                    pass

    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        ordered_keys: list[str] = []
        for item in value:
            for key in item.keys():
                text_key = str(key)
                if text_key not in ordered_keys:
                    ordered_keys.append(text_key)
        for idx, item in enumerate(value, start=1):
            row = [str(idx)] + [preview_cell(item.get(key)) for key in ordered_keys]
            rows.append(row)
        return ["#"] + ordered_keys, rows

    if isinstance(value, dict):
        rows = [[str(idx), str(key), preview_cell(val)] for idx, (key, val) in enumerate(value.items(), start=1)]
        return ["#", "key", "value"], rows

    preview_text = format_preview(value, max_chars=None)
    headers, parsed_rows = table_from_text_preview(preview_text)
    if parsed_rows:
        return headers, parsed_rows

    if preview_text:
        return ["#", "value"], [["1", preview_text]]
    return [], []


def filter_table_rows_by_username(headers: list[str], rows: list[list[str]], username: str) -> list[list[str]]:
    needle = username.strip().lower()
    if not needle or not headers or not rows:
        return rows

    preferred_markers = ("username", "user", "owner", "creator", "created_by", "database", "schema", "permission")
    preferred_indices: list[int] = []
    for idx, column in enumerate(headers):
        if idx == 0:
            continue
        name = str(column).lower()
        if any(marker in name for marker in preferred_markers):
            preferred_indices.append(idx)

    all_indices = [idx for idx in range(1, len(headers))]
    search_orders = [preferred_indices] if preferred_indices else []
    if all_indices != preferred_indices:
        search_orders.append(all_indices)

    filtered: list[list[str]] = []
    for indices in search_orders:
        candidate: list[list[str]] = []
        for row in rows:
            for idx in indices:
                if idx < len(row) and needle in str(row[idx]).lower():
                    candidate.append(row)
                    break
        if candidate:
            filtered = candidate
            break

    reindexed: list[list[str]] = []
    for idx, row in enumerate(filtered, start=1):
        if row:
            reindexed.append([str(idx)] + row[1:])
        else:
            reindexed.append([str(idx)])
    return reindexed


def ordered_vs_name_values(headers: list[str], rows: list[list[str]]) -> list[str]:
    idx = vs_name_column_index(headers)
    if idx < 0:
        return []
    values: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if idx >= len(row):
            continue
        value = str(row[idx]).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def try_parse_datetime_cell(value: str) -> datetime | None:
    text = str(value).strip()
    if not text:
        return None

    iso_candidate = text
    if iso_candidate.endswith("Z"):
        iso_candidate = iso_candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(iso_candidate)
    except Exception:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def guess_latest_vs_name(headers: list[str], rows: list[list[str]]) -> str:
    vs_idx = vs_name_column_index(headers)
    if vs_idx < 0:
        return ""

    def _norm(value: str) -> str:
        return str(value).strip().lower().replace(" ", "").replace("-", "")

    creation_markers = ("createdat", "createtime", "creationtime", "createat", "created")
    time_markers = ("timestamp", "datetime", "time", "date")

    preferred_time_indices: list[int] = []
    fallback_time_indices: list[int] = []
    for idx, column in enumerate(headers):
        if idx == 0:
            continue
        key = _norm(column)
        if any(marker in key for marker in creation_markers):
            preferred_time_indices.append(idx)
            continue
        if any(marker in key for marker in time_markers):
            fallback_time_indices.append(idx)

    time_indices = preferred_time_indices or fallback_time_indices
    best_name = ""
    best_ts: float | None = None
    for row in rows:
        if vs_idx >= len(row):
            continue
        name = str(row[vs_idx]).strip()
        if not name:
            continue
        row_ts: float | None = None
        for time_idx in time_indices:
            if time_idx >= len(row):
                continue
            parsed = try_parse_datetime_cell(row[time_idx])
            if parsed is None:
                continue
            try:
                candidate_ts = parsed.timestamp()
            except Exception:
                continue
            if row_ts is None or candidate_ts > row_ts:
                row_ts = candidate_ts
        if row_ts is None:
            continue
        if best_ts is None or row_ts > best_ts:
            best_ts = row_ts
            best_name = name

    if best_name:
        return best_name

    ordered_names = ordered_vs_name_values(headers, rows)
    if ordered_names:
        return ordered_names[0]
    return ""


def clear_list_result(state: dict) -> None:
    state["list_preview"] = ""
    state["list_columns"] = []
    state["list_rows"] = []
    state["list_row_count"] = 0
    state["list_loaded_by_user"] = False


def clear_chat_list_result(state: dict) -> None:
    state["chat_vs_options"] = []
    state["chat_list_preview"] = ""
    state["chat_list_loaded_by_user"] = False


def clear_health_result(state: dict) -> None:
    state["health_preview"] = ""
    state["health_columns"] = []
    state["health_rows"] = []
    state["health_row_count"] = 0


def clear_destroy_result(state: dict) -> None:
    state["destroy_preview"] = ""
    state["destroy_status"] = "neutral"


def apply_list_output_to_state(state: dict, list_output: Any, sync_chat_options: bool = False) -> tuple[int, int | None, str]:
    headers, all_rows_data = table_from_result(list_output)
    username_filter = str(state.get("params", {}).get("username", "")).strip()
    rows_data = all_rows_data
    if username_filter:
        rows_data = filter_table_rows_by_username(headers, all_rows_data, username_filter)

    state["list_columns"] = headers
    state["list_rows"] = rows_data
    state["list_row_count"] = len(rows_data)
    filtered_vs_options = ordered_vs_name_values(headers, rows_data)
    if sync_chat_options:
        state["chat_vs_options"] = filtered_vs_options
    if username_filter and not rows_data:
        state["list_preview"] = f"No rows matched username '{username_filter}'."
    else:
        state["list_preview"] = format_preview(list_output, max_chars=None)

    total_rows: int | None = None
    if hasattr(list_output, "shape"):
        try:
            total_rows = int(list_output.shape[0])
        except Exception:
            total_rows = None
    return len(rows_data), total_rows, username_filter


def apply_chat_list_output_to_state(state: dict, list_output: Any) -> tuple[int, int | None, str]:
    headers, all_rows_data = table_from_result(list_output)
    username_filter = str(state.get("params", {}).get("username", "")).strip()
    rows_data = all_rows_data
    if username_filter:
        rows_data = filter_table_rows_by_username(headers, all_rows_data, username_filter)

    filtered_vs_options = ordered_vs_name_values(headers, rows_data)
    state["chat_vs_options"] = filtered_vs_options
    state["chat_list_loaded_by_user"] = True
    if username_filter and not rows_data:
        state["chat_list_preview"] = f"No rows matched username '{username_filter}'."
    else:
        state["chat_list_preview"] = format_preview(list_output, max_chars=None)

    selected = str(state.get("selected_vs_name", "")).strip()
    available_names = set(filtered_vs_options)
    if selected and selected in available_names:
        state["selected_vs_name"] = selected
    elif filtered_vs_options:
        state["selected_vs_name"] = filtered_vs_options[0]
    else:
        state["selected_vs_name"] = ""

    total_rows: int | None = None
    if hasattr(list_output, "shape"):
        try:
            total_rows = int(list_output.shape[0])
        except Exception:
            total_rows = None
    return len(rows_data), total_rows, username_filter


def build_file_meta(path_hint: str, resolve_path_hint: Callable[[str], str]) -> dict[str, str | int | bool]:
    meta: dict[str, str | int | bool] = {
        "input": path_hint,
        "resolved": "",
        "exists": False,
        "size": 0,
        "sha256": "",
    }
    if not path_hint:
        return meta
    resolved = resolve_path_hint(path_hint)
    meta["resolved"] = resolved
    if not resolved:
        return meta
    from pathlib import Path

    p = Path(resolved)
    if not p.exists() or not p.is_file():
        return meta
    payload = p.read_bytes()
    meta["exists"] = True
    meta["size"] = len(payload)
    meta["sha256"] = hashlib.sha256(payload).hexdigest()
    return meta
