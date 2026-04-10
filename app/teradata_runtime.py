from __future__ import annotations

try:
    from teradataml import create_context, remove_context
except Exception as ex:  # pragma: no cover - dependency/runtime specific.
    create_context = None
    remove_context = None
    _teradataml_core_error = str(ex)
else:
    _teradataml_core_error = ""

try:
    from teradataml import execute_sql
except Exception:
    execute_sql = None

try:
    from teradatagenai import VSManager, set_auth_token
except Exception as ex:  # pragma: no cover - dependency/runtime specific.
    VSManager = None
    set_auth_token = None
    _teradatagenai_error = str(ex)
else:
    _teradatagenai_error = ""

TERADATA_IMPORT_ERROR = " | ".join(
    part for part in (_teradataml_core_error, _teradatagenai_error) if part
)

try:
    from teradatagenai import VectorStore
except Exception:
    VectorStore = None
