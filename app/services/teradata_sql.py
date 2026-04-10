from __future__ import annotations

import re
from typing import Any, Callable

ExecuteSqlFn = Callable[[str], Any]


def _qualified_table_sql(schema_name: str | None, table_name: str) -> str:
    if schema_name:
        return f'"{schema_name}"."{table_name}"'
    return f'"{table_name}"'


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _column_cast_type(column_type: str) -> str:
    return re.sub(r"\s+NOT\s+NULL\s*$", "", column_type, flags=re.IGNORECASE).strip()


def _sql_typed_literal(value: Any, column_type: str) -> str:
    return f"CAST({_sql_literal(value)} AS {_column_cast_type(column_type)})"


def _cursor_first_scalar(cursor) -> str | int | None:
    if cursor is None:
        return None
    fetchone = getattr(cursor, "fetchone", None)
    if callable(fetchone):
        try:
            row = fetchone()
        except Exception:
            row = None
        if isinstance(row, dict):
            for value in row.values():
                return value
            return None
        if isinstance(row, (list, tuple)) and row:
            return row[0]
        if row is not None:
            try:
                return row[0]
            except Exception:
                pass
        if row is not None:
            return row

    fetchall = getattr(cursor, "fetchall", None)
    if callable(fetchall):
        try:
            rows = fetchall()
        except Exception:
            rows = []
        if not rows:
            return None
        first = rows[0]
        if isinstance(first, dict):
            for value in first.values():
                return value
            return None
        if isinstance(first, (list, tuple)) and first:
            return first[0]
        try:
            return first[0]
        except Exception:
            pass
        return first
    return None


def _teradata_table_exists(qualified_table_sql: str, execute_sql_fn: ExecuteSqlFn | None) -> bool:
    if execute_sql_fn is None:
        raise RuntimeError("teradataml.execute_sql is unavailable.")
    try:
        execute_sql_fn(f"SELECT TOP 1 1 FROM {qualified_table_sql}")
        return True
    except Exception as ex:
        msg = str(ex).lower()
        if "3807" in msg or "does not exist" in msg or "not found" in msg:
            return False
        raise


def _count_teradata_rows(schema_name: str | None, table_name: str, execute_sql_fn: ExecuteSqlFn | None) -> int | None:
    if execute_sql_fn is None:
        return None
    qualified_table = _qualified_table_sql(schema_name, table_name)
    try:
        cursor = execute_sql_fn(f"SELECT COUNT(*) FROM {qualified_table}")
    except Exception:
        return None
    scalar = _cursor_first_scalar(cursor)
    if scalar is None:
        return None
    try:
        return int(scalar)
    except Exception:
        return None
