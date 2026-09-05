"""Length validation for creation fields without corrupting user input."""
from __future__ import annotations


DEFAULT_CREATE_FIELD_MAX_LENGTH = 4096


class CreateFieldValidationError(ValueError):
    pass


def create_field_max_length(name: str, *, default: int = DEFAULT_CREATE_FIELD_MAX_LENGTH) -> int:
    if name.endswith("_api_key"):
        return 8192
    if name == "document_files":
        return 65536
    if name in {"prompt", "description"}:
        return 32768
    if name in {"include_objects", "exclude_objects", "include_patterns", "exclude_patterns"}:
        return 16384
    if name.endswith("_model") or name.endswith("_model_name"):
        return 512
    if name == "vector_store_name" or name.endswith("_run_id"):
        return 128
    return default


def validate_create_field(name: str, value: str, *, default: int = DEFAULT_CREATE_FIELD_MAX_LENGTH) -> str:
    limit = create_field_max_length(name, default=default)
    if len(value) > limit:
        raise CreateFieldValidationError(f"{name} must contain at most {limit} characters.")
    return value
