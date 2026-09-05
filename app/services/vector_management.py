from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Callable


RESOURCE_COLUMNS = ["Name", "Description", "Type", "Status", "Database", "Owner"]
SESSION_COLUMNS = ["API", "Username", "Session ID", "Status", "Connected at"]

_RESOURCE_ALIASES = {
    "name": ("vsname", "vectorstorename", "collectionname", "name"),
    "type": ("storetype", "collectiontype", "type"),
    "description": (
        "description",
        "vsdescription",
        "vectorstoredescription",
        "collectiondescription",
        "purpose",
        "comment",
        "note",
    ),
    "status": ("vsstatus", "collectionstatus", "status", "state"),
    "owner": ("username", "owner", "creator", "createdby", "user"),
    "database": ("databasename", "targetdatabase", "database", "schema"),
}
_SESSION_ALIASES = {
    "username": ("username", "user", "databaseuser", "dbuser"),
    "session_id": ("sessionid", "session", "id"),
    "status": ("status", "state"),
    "connected_at": ("connectedat", "createdat", "starttime", "logontime", "timestamp"),
}
_CONTAINER_KEYS = (
    "collection_list",
    "collections",
    "vector_stores",
    "vectorstores",
    "vs_list",
    "session_details",
    "sessions",
    "data",
    "items",
    "results",
)


def sdk_version() -> str:
    try:
        return version("teradatagenai")
    except PackageNotFoundError:
        return "Not installed"


def empty_management_state() -> dict[str, Any]:
    return {
        "management_loaded": False,
        "management_checked_at": "",
        "management_health": "Not checked",
        "management_health_detail": "",
        "management_sdk_version": sdk_version(),
        "management_warnings": [],
        "resource_columns": list(RESOURCE_COLUMNS),
        "resource_rows": [],
        "resource_records": [],
        "selected_resource_kind": "",
        "selected_resource_name": "",
        "selected_resource_type": "",
        "resource_detail_columns": [],
        "resource_detail_rows": [],
        "resource_detail_preview": "",
        "resource_status_columns": [],
        "resource_status_rows": [],
        "resource_status_preview": "",
        "resource_file_columns": [],
        "resource_file_rows": [],
        "resource_file_preview": "",
        "resource_permission_columns": [],
        "resource_permission_rows": [],
        "resource_permission_preview": "",
        "sessions_loaded": False,
        "sessions_checked_at": "",
        "session_columns": list(SESSION_COLUMNS),
        "session_rows": [],
        "session_preview": "",
    }


def clear_selected_resource(state: dict[str, Any]) -> None:
    state.update(
        {
            "selected_resource_kind": "",
            "selected_resource_name": "",
            "selected_resource_type": "",
            "resource_detail_columns": [],
            "resource_detail_rows": [],
            "resource_detail_preview": "",
            "resource_status_columns": [],
            "resource_status_rows": [],
            "resource_status_preview": "",
            "resource_file_columns": [],
            "resource_file_rows": [],
            "resource_file_preview": "",
            "resource_permission_columns": [],
            "resource_permission_rows": [],
            "resource_permission_preview": "",
        }
    )


def clear_management_results(state: dict[str, Any]) -> None:
    preserved_version = str(state.get("management_sdk_version") or sdk_version())
    state.update(empty_management_state())
    state["management_sdk_version"] = preserved_version


def remove_resource(state: dict[str, Any], *, kind: str, name: str) -> None:
    records = [
        item
        for item in state.get("resource_records") or []
        if not (item.get("kind") == kind and item.get("name") == name)
    ]
    state["resource_records"] = records
    state["resource_rows"] = [
        [
            item["name"],
            item.get("description") or "",
            item.get("type") or "",
            item.get("status") or "",
            item.get("database") or "",
            item.get("owner") or "",
        ]
        for item in records
    ]
    clear_selected_resource(state)


def _key(value: Any) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def _string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_string(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{key}={_string(item)}" for key, item in value.items())
    return str(value)


def _records(value: Any) -> list[dict[str, Any]]:
    candidate = value
    for attribute in ("to_pandas", "to_dataframe"):
        converter = getattr(candidate, attribute, None)
        if callable(converter):
            try:
                converted = converter()
            except Exception:
                continue
            if converted is not None:
                candidate = converted
                break

    to_dict = getattr(candidate, "to_dict", None)
    if callable(to_dict):
        try:
            converted = to_dict(orient="records")
        except TypeError:
            converted = None
        except Exception:
            converted = None
        if isinstance(converted, list) and all(isinstance(item, dict) for item in converted):
            return list(converted)

    if isinstance(candidate, (list, tuple)):
        return [dict(item) for item in candidate if isinstance(item, dict)]
    if isinstance(candidate, dict):
        normalized = {_key(key): key for key in candidate}
        for container in _CONTAINER_KEYS:
            original_key = normalized.get(_key(container))
            if original_key is None:
                continue
            nested = _records(candidate[original_key])
            if nested:
                return nested
            if candidate[original_key] == []:
                return []
        if any(alias in normalized for aliases in _RESOURCE_ALIASES.values() for alias in aliases):
            return [dict(candidate)]

    for attribute in _CONTAINER_KEYS:
        nested = getattr(candidate, attribute, None)
        if nested is not None:
            records = _records(nested)
            if records or nested == []:
                return records
    return []


def _field(record: dict[str, Any], aliases: tuple[str, ...]) -> str:
    normalized = {_key(key): value for key, value in record.items()}
    for alias in aliases:
        value = normalized.get(alias)
        if value is not None and str(value).strip():
            return _string(value).strip()
    return ""


def _invoke_json(function: Callable[..., Any], **kwargs: Any) -> Any:
    try:
        return function(return_type="json", **kwargs)
    except TypeError as ex:
        if "return_type" not in str(ex):
            raise
        return function(**kwargs)


def _manager(manager_class: Any, auth_data: Any) -> Any:
    if manager_class is None:
        return None
    try:
        return manager_class(auth_data=auth_data)
    except TypeError:
        try:
            return manager_class()
        except TypeError:
            return manager_class


def _resource_rows(value: Any, *, kind: str) -> list[dict[str, str]]:
    api = "Collection" if kind == "v2" else "Vector store"
    rows: list[dict[str, str]] = []
    for record in _records(value):
        name = _field(record, _RESOURCE_ALIASES["name"])
        if not name:
            continue
        rows.append(
            {
                "kind": kind,
                "api": api,
                "name": name,
                "description": _field(record, _RESOURCE_ALIASES["description"]),
                "type": _field(record, _RESOURCE_ALIASES["type"]),
                "status": _field(record, _RESOURCE_ALIASES["status"]),
                "owner": _field(record, _RESOURCE_ALIASES["owner"]),
                "database": _field(record, _RESOURCE_ALIASES["database"]),
            }
        )
    return rows


def _connection_resource_rows(
    resources: list[dict[str, str]],
    *,
    username: str,
) -> list[dict[str, str]]:
    """Keep resources whose ownership metadata matches the active DB profile.

    An administrative SDK token can list resources for many database users.  Those
    resources must not leak into a connection-scoped UI.  The EVS APIs expose the
    association as either owner or target database, depending on API generation.
    """
    expected = _key(username)
    if not expected:
        return []
    matched: list[dict[str, str]] = []
    for item in resources:
        owner = _key(item.get("owner"))
        database = _key(item.get("database"))
        if expected in {owner, database}:
            matched.append(item)
    return matched


def _description_from_details(value: Any) -> str:
    records = _records(value)
    if records:
        return _field(records[0], _RESOURCE_ALIASES["description"])
    if isinstance(value, dict):
        return _field(value, _RESOURCE_ALIASES["description"])
    return ""


def _load_resource_description(
    item: dict[str, str],
    *,
    auth_data: Any,
    vector_store_class: Any,
    collection_class: Any,
) -> str:
    resource_class = collection_class if item["kind"] == "v2" else vector_store_class
    if resource_class is None:
        raise RuntimeError(f"The {item['kind']} detail endpoint is unavailable.")
    resource = _instantiate(resource_class, item["name"], auth_data)
    return _description_from_details(_call_section(resource, "get_details"))


def _hydrate_resource_descriptions(
    resources: list[dict[str, str]],
    *,
    state: dict[str, Any],
    auth_data: Any,
    vector_store_class: Any,
    collection_class: Any,
    connection_username: str,
) -> list[str]:
    """Fill descriptions omitted by list APIs without slowing row selection."""
    cache = state.setdefault("_resource_description_cache", {})
    pending: list[dict[str, str]] = []
    prefix = _key(connection_username)
    for item in resources:
        cache_key = f"{prefix}:{item['kind']}:{item['name'].casefold()}"
        item["_description_cache_key"] = cache_key
        description = str(item.get("description") or "").strip()
        if description:
            cache[cache_key] = description
            continue
        cached = str(cache.get(cache_key) or "").strip()
        if cached:
            item["description"] = cached
        else:
            pending.append(item)

    failures: list[str] = []
    if pending:
        worker_count = min(4, len(pending))
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="evs-description") as executor:
            futures = {
                executor.submit(
                    _load_resource_description,
                    item,
                    auth_data=auth_data,
                    vector_store_class=vector_store_class,
                    collection_class=collection_class,
                ): item
                for item in pending
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    description = str(future.result() or "").strip()
                except Exception:
                    item["description"] = ""
                    failures.append(item["name"])
                    continue
                if description:
                    item["description"] = description
                    cache[item["_description_cache_key"]] = description
                else:
                    item["description"] = ""

    for item in resources:
        item.pop("_description_cache_key", None)
    return failures


def select_resource(state: dict[str, Any], *, kind: str, name: str) -> bool:
    """Select an already listed resource without invoking the Teradata SDK."""
    selected = next(
        (
            item
            for item in state.get("resource_records") or []
            if item.get("kind") == kind and item.get("name") == name
        ),
        None,
    )
    clear_selected_resource(state)
    if selected is None:
        return False
    state["selected_resource_kind"] = kind
    state["selected_resource_name"] = name
    state["selected_resource_type"] = str(selected.get("type") or "")
    state["selected_vs_name"] = name
    return True


def _health_text(value: Any) -> str:
    records = _records(value)
    if records:
        status = _field(records[0], ("status", "health", "state", "message"))
        if status:
            return status
    if isinstance(value, dict):
        for key, item in value.items():
            if _key(key) in {"status", "health", "state", "message"}:
                return _string(item).strip()
    return _string(value).strip()


def refresh_management(
    state: dict[str, Any],
    *,
    auth_data: Any,
    vs_manager_class: Any,
    collection_manager_class: Any,
    connection_username: str,
    table_from_result: Callable[[Any], tuple[list[str], list[list[str]]]],
    format_preview: Callable[..., str],
    now: Callable[[], str],
    vector_store_class: Any = None,
    collection_class: Any = None,
) -> None:
    warnings: list[str] = []
    resources: list[dict[str, str]] = []
    health_parts: list[str] = []

    legacy_manager = _manager(vs_manager_class, auth_data)
    if legacy_manager is not None:
        try:
            health_output = _invoke_json(getattr(legacy_manager, "health"))
            headers, rows = table_from_result(health_output)
            state["health_columns"] = headers
            state["health_rows"] = rows
            state["health_row_count"] = len(rows)
            state["health_preview"] = format_preview(health_output, max_chars=None)
            health_parts.append(_health_text(health_output) or "available")
        except Exception as ex:
            state["health_columns"] = []
            state["health_rows"] = []
            state["health_row_count"] = 0
            state["health_preview"] = f"Error: {ex}"
            warnings.append(f"Vector store health check: {ex}")
        try:
            list_output = _invoke_json(getattr(legacy_manager, "list"))
            headers, rows = table_from_result(list_output)
            state["list_columns"] = headers
            state["list_rows"] = rows
            state["list_row_count"] = len(rows)
            state["list_preview"] = format_preview(list_output, max_chars=None)
            state["list_loaded_by_user"] = True
            resources.extend(_resource_rows(list_output, kind="v1"))
        except Exception as ex:
            state["list_columns"] = []
            state["list_rows"] = []
            state["list_row_count"] = 0
            state["list_preview"] = f"Error: {ex}"
            state["list_loaded_by_user"] = True
            warnings.append(f"Vector store inventory: {ex}")
    else:
        warnings.append("The vector store inventory endpoint is unavailable.")

    collection_manager = _manager(collection_manager_class, auth_data)
    if collection_manager is not None:
        try:
            health_output = _invoke_json(getattr(collection_manager, "health"))
            health_parts.append(_health_text(health_output) or "available")
        except Exception as ex:
            warnings.append(f"Collection health check: {ex}")
        try:
            list_output = _invoke_json(
                getattr(collection_manager, "list"), page=1, page_size=100, authorized=True
            )
            resources.extend(_resource_rows(list_output, kind="v2"))
        except Exception as ex:
            warnings.append(f"Collection inventory: {ex}")
    else:
        warnings.append("The collection inventory endpoint is unavailable.")

    resources = _connection_resource_rows(resources, username=connection_username)
    deduplicated: dict[str, dict[str, str]] = {}
    for item in resources:
        # A name can be reported by more than one SDK surface.  Present it once;
        # prefer the current Collection record when both are available.
        key = item["name"].casefold()
        existing = deduplicated.get(key)
        if existing is None or item["kind"] == "v2":
            deduplicated[key] = item
    resources = sorted(deduplicated.values(), key=lambda item: item["name"].casefold())
    description_failures = _hydrate_resource_descriptions(
        resources,
        state=state,
        auth_data=auth_data,
        vector_store_class=vector_store_class,
        collection_class=collection_class,
        connection_username=connection_username,
    )
    if description_failures:
        names = ", ".join(description_failures[:5])
        suffix = "…" if len(description_failures) > 5 else ""
        warnings.append(
            f"Descriptions could not be loaded for {len(description_failures)} resource(s): {names}{suffix}"
        )
    state["resource_columns"] = list(RESOURCE_COLUMNS)
    state["resource_records"] = resources
    state["resource_rows"] = [
        [
            item["name"],
            item["description"],
            item["type"],
            item["status"],
            item["database"],
            item["owner"],
        ]
        for item in resources
    ]
    state["management_loaded"] = True
    state["management_checked_at"] = now()
    state["management_sdk_version"] = sdk_version()
    state["management_warnings"] = warnings
    state["management_health"] = "Healthy" if health_parts else "Unavailable"
    state["management_health_detail"] = "Service available" if health_parts else "No health endpoint responded."

    selected_kind = str(state.get("selected_resource_kind") or "").strip()
    selected_name = str(state.get("selected_resource_name") or "").strip()
    if selected_name and not any(
        item["kind"] == selected_kind and item["name"] == selected_name for item in resources
    ):
        clear_selected_resource(state)


def _result_section(
    value: Any,
    *,
    table_from_result: Callable[[Any], tuple[list[str], list[list[str]]]],
    format_preview: Callable[..., str],
) -> tuple[list[str], list[list[str]], str]:
    columns, rows = table_from_result(value)
    return columns, rows, format_preview(value, max_chars=None)


def _instantiate(resource_class: Any, name: str, auth_data: Any) -> Any:
    try:
        return resource_class(name=name, auth_data=auth_data)
    except TypeError:
        try:
            return resource_class(name, auth_data=auth_data)
        except TypeError:
            return resource_class(name)


def _call_section(resource: Any, method_name: str, *, kwargs: dict[str, Any] | None = None) -> Any:
    method = getattr(resource, method_name, None)
    if not callable(method):
        raise RuntimeError(f"{type(resource).__name__}.{method_name}() is unavailable.")
    kwargs = dict(kwargs or {})
    try:
        return method(return_type="json", **kwargs)
    except TypeError as ex:
        if "return_type" not in str(ex):
            raise
        return method(**kwargs)


def load_resource_details(
    state: dict[str, Any],
    *,
    kind: str,
    name: str,
    role: str,
    auth_data: Any,
    vector_store_class: Any,
    collection_class: Any,
    ingestor_class: Any,
    collection_type_class: Any,
    table_from_result: Callable[[Any], tuple[list[str], list[list[str]]]],
    format_preview: Callable[..., str],
) -> None:
    clear_selected_resource(state)
    state["selected_resource_kind"] = kind
    state["selected_resource_name"] = name
    state["selected_vs_name"] = name
    warnings = list(state.get("management_warnings") or [])

    resource_class = collection_class if kind == "v2" else vector_store_class
    if resource_class is None:
        state["resource_detail_preview"] = "The selected resource endpoint is unavailable."
        return

    selected_record = next(
        (
            item
            for item in state.get("resource_records") or []
            if item.get("kind") == kind and item.get("name") == name
        ),
        {},
    )
    resource_type = str(selected_record.get("type") or "").strip()
    state["selected_resource_type"] = resource_type

    try:
        resource = _instantiate(resource_class, name, auth_data)
    except Exception as ex:
        state["resource_detail_preview"] = f"Unable to initialize resource: {ex}"
        return

    for method_name, prefix in (("get_details", "resource_detail"), ("status", "resource_status")):
        try:
            kwargs = {"elaborate": True} if method_name == "get_details" and kind == "v2" else {}
            value = _call_section(resource, method_name, kwargs=kwargs)
            columns, rows, preview = _result_section(
                value, table_from_result=table_from_result, format_preview=format_preview
            )
            state[f"{prefix}_columns"] = columns
            state[f"{prefix}_rows"] = rows
            state[f"{prefix}_preview"] = preview
        except Exception as ex:
            state[f"{prefix}_preview"] = f"Unable to load: {ex}"

    if role == "admin":
        try:
            value = _call_section(resource, "list_user_permissions", kwargs={"page": 1, "page_size": 100} if kind == "v2" else {})
            columns, rows, preview = _result_section(
                value, table_from_result=table_from_result, format_preview=format_preview
            )
            state["resource_permission_columns"] = columns
            state["resource_permission_rows"] = rows
            state["resource_permission_preview"] = preview
        except Exception as ex:
            state["resource_permission_preview"] = f"Unable to load: {ex}"

    if kind == "v2" and resource_type.upper().replace("_", "-").startswith("FILE-"):
        if ingestor_class is None or collection_type_class is None:
            state["resource_file_preview"] = "File monitoring is unavailable in the installed SDK."
        else:
            enum_name = resource_type.upper().replace("-", "_")
            collection_type = getattr(collection_type_class, enum_name, None)
            if collection_type is None:
                state["resource_file_preview"] = f"Unsupported file collection type: {resource_type}"
            else:
                try:
                    ingestor = ingestor_class(name=name, type=collection_type, auth_data=auth_data)
                    try:
                        value = _call_section(
                            ingestor, "get_file_metadata", kwargs={"page": 1, "page_size": 100}
                        )
                    except Exception:
                        value = _call_section(
                            ingestor, "get_file_store", kwargs={"page": 1, "page_size": 100}
                        )
                    columns, rows, preview = _result_section(
                        value, table_from_result=table_from_result, format_preview=format_preview
                    )
                    state["resource_file_columns"] = columns
                    state["resource_file_rows"] = rows
                    state["resource_file_preview"] = preview
                except Exception as ex:
                    state["resource_file_preview"] = f"Unable to load: {ex}"

    state["management_warnings"] = warnings


def _session_rows(value: Any, *, api: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in _records(value):
        username = _field(record, _SESSION_ALIASES["username"])
        session_id = _field(record, _SESSION_ALIASES["session_id"])
        if not username and not session_id:
            continue
        rows.append(
            {
                "api": api,
                "username": username or "—",
                "session_id": session_id or "—",
                "status": _field(record, _SESSION_ALIASES["status"]) or "Active",
                "connected_at": _field(record, _SESSION_ALIASES["connected_at"]) or "—",
            }
        )
    return rows


def load_sessions(
    state: dict[str, Any],
    *,
    auth_data: Any,
    vs_manager_class: Any,
    collection_manager_class: Any,
    format_preview: Callable[..., str],
    now: Callable[[], str],
) -> None:
    manager = _manager(collection_manager_class, auth_data)
    api = "Collection"
    uses_collection_api = True
    if manager is None:
        manager = _manager(vs_manager_class, auth_data)
        api = "Vector store"
        uses_collection_api = False
    if manager is None or not callable(getattr(manager, "list_sessions", None)):
        raise RuntimeError("Session management is unavailable in the installed SDK.")
    kwargs = {"page": 1, "page_size": 100} if uses_collection_api else {}
    value = _invoke_json(getattr(manager, "list_sessions"), **kwargs)
    records = _session_rows(value, api=api)
    state["session_columns"] = list(SESSION_COLUMNS)
    state["session_rows"] = [
        [item["api"], item["username"], item["session_id"], item["status"], item["connected_at"]]
        for item in records
    ]
    state["session_preview"] = format_preview(value, max_chars=None)
    state["sessions_loaded"] = True
    state["sessions_checked_at"] = now()


def disconnect_sessions(*, usernames: list[str], auth_data: Any, collection_manager_class: Any) -> None:
    cleaned = sorted({str(username or "").strip() for username in usernames if str(username or "").strip()})
    if not cleaned:
        raise ValueError("Select at least one username to disconnect.")
    manager = _manager(collection_manager_class, auth_data)
    if manager is None or not callable(getattr(manager, "disconnect", None)):
        raise RuntimeError("Session disconnect is unavailable in the installed SDK.")
    manager.disconnect(user_names=cleaned)
