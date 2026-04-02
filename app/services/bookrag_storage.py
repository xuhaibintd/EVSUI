from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from app.services.bookrag_schema import (
    BOOKRAG_BLOCK_COLUMNS,
    BOOKRAG_DOCUMENT_COLUMNS,
    BOOKRAG_ENTITY_COLUMNS,
    BOOKRAG_ENTITY_LINK_COLUMNS,
    BOOKRAG_INSERT_BATCH_MAX_ROWS,
    BOOKRAG_INSERT_BATCH_MAX_SQL_CHARS,
    BOOKRAG_NODE_COLUMNS,
    ExecuteSqlFn,
    _qualified_table_sql,
    _sql_literal,
    _sql_typed_literal,
)


def _csv_stage_path(csv_stage_dir: Path, table_name: str) -> Path:
    return csv_stage_dir / f"{table_name}.csv"


def _write_rows_to_csv(
    csv_stage_dir: Path,
    table_name: str,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
) -> Path:
    csv_stage_dir.mkdir(parents=True, exist_ok=True)
    csv_path = _csv_stage_path(csv_stage_dir, table_name)
    column_names = [name for name, _ in columns]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=column_names, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: "" if row.get(name) is None else row.get(name) for name in column_names})
    return csv_path


def _load_rows_from_csv(csv_path: Path, schema_name: str | None, table_name: str) -> None:
    from teradataml import read_csv

    read_csv(
        filepath=str(csv_path),
        table_name=table_name,
        schema_name=schema_name,
        if_exists="append",
        use_fastload=True,
    )


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


def _insert_rows(
    schema_name: str | None,
    table_name: str,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, int] | None = None,
) -> int:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    if not rows:
        return 0
    qualified_table = _qualified_table_sql(schema_name, table_name)
    column_names = [name for name, _ in columns]
    inserted = 0

    if stats is not None:
        stats.setdefault("read_csv_calls", 0)
        stats.setdefault("read_csv_rows", 0)
        stats.setdefault("read_csv_fallbacks", 0)
        stats.setdefault("copy_to_sql_calls", 0)
        stats.setdefault("copy_to_sql_rows", 0)
        stats.setdefault("copy_to_sql_fallbacks", 0)
        stats.setdefault("single_row_statements", 0)
        stats.setdefault("batch_statements", 0)
        stats.setdefault("batch_rows", 0)
        stats.setdefault("fallback_rows", 0)
        stats.setdefault("fallback_batches", 0)

    if csv_stage_dir is not None:
        try:
            csv_path = _write_rows_to_csv(csv_stage_dir, table_name, rows, columns)
            _load_rows_from_csv(csv_path, schema_name, table_name)
            inserted += len(rows)
            if stats is not None:
                stats["read_csv_calls"] += 1
                stats["read_csv_rows"] += len(rows)
            return inserted
        except Exception:
            if stats is not None:
                stats["read_csv_fallbacks"] += 1

    if len(rows) > 1:
        try:
            inserted += _copy_rows_to_sql(schema_name, table_name, rows, columns)
            if stats is not None:
                stats["copy_to_sql_calls"] += 1
                stats["copy_to_sql_rows"] += len(rows)
            return inserted
        except Exception:
            if stats is not None:
                stats["copy_to_sql_fallbacks"] += 1

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
    execute_sql_fn: ExecuteSqlFn | None,
    csv_stage_dir: Path | None = None,
    stats: dict[str, int] | None = None,
) -> int:
    inserted = 0
    inserted += _insert_rows(schema_name, table_targets["documents"], document_rows, BOOKRAG_DOCUMENT_COLUMNS, execute_sql_fn, csv_stage_dir=csv_stage_dir, stats=stats)
    inserted += _insert_rows(schema_name, table_targets["nodes"], nodes, BOOKRAG_NODE_COLUMNS, execute_sql_fn, csv_stage_dir=csv_stage_dir, stats=stats)
    inserted += _insert_rows(schema_name, table_targets["entities"], entities, BOOKRAG_ENTITY_COLUMNS, execute_sql_fn, csv_stage_dir=csv_stage_dir, stats=stats)
    inserted += _insert_rows(schema_name, table_targets["entity_links"], entity_links, BOOKRAG_ENTITY_LINK_COLUMNS, execute_sql_fn, csv_stage_dir=csv_stage_dir, stats=stats)
    inserted += _insert_rows(schema_name, table_targets["blocks"], blocks, BOOKRAG_BLOCK_COLUMNS, execute_sql_fn, csv_stage_dir=csv_stage_dir, stats=stats)
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
