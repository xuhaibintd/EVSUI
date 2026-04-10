from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

UNSTRUCTURED_CONFIG_FILE_DEFAULT = Path(__file__).resolve().parents[1] / "config" / "unstructured.json"
UNSTRUCTURED_WORKFLOW_API_URL_DEFAULT = "https://platform.unstructuredapp.io/api/v1"
UNSTRUCTURED_WORKFLOW_POLL_SECONDS_DEFAULT = 900
UNSTRUCTURED_WORKFLOW_POLL_INTERVAL_DEFAULT = 2
UNSTRUCTURED_TERADATA_FLUSH_WAIT_SECONDS_DEFAULT = 20
UNSTRUCTURED_TERADATA_FLUSH_WAIT_INTERVAL_DEFAULT = 2
UNSTRUCTURED_DEBUG_DIR_DEFAULT = Path(__file__).resolve().parents[2] / "uploads" / "multi_format_stage"
BOOKRAG_RAW_STAGE_DIR_DEFAULT = Path(__file__).resolve().parents[2] / "uploads" / "bookrag_raw_stage"
BOOKRAG_PDF_IMAGE_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
    ".webp",
}
UNSTRUCTURED_FAST_UNSAFE_IMAGE_EXTENSIONS = BOOKRAG_PDF_IMAGE_EXTENSIONS - {".pdf"}
EXCEL_OPENXML_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm"}
EXCEL_LEGACY_EXTENSIONS = {".xls"}
EXCEL_EXTENSIONS = EXCEL_OPENXML_EXTENSIONS | EXCEL_LEGACY_EXTENSIONS


def _to_bounded_int(raw: Any, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        value = int(str(raw).strip())
    except Exception:
        return default
    if value < minimum:
        return default
    if maximum is not None and value > maximum:
        return maximum
    return value


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_langs(raw: str) -> list[str]:
    return [chunk.strip() for chunk in str(raw or "").replace("\n", ",").split(",") if chunk.strip()]


def _resolve_partition_strategy(raw: str) -> str:
    value = str(raw or "auto").strip().lower()
    if value == "fast":
        return "fast"
    if value in {"hi_res", "layout"}:
        return "hi_res"
    if value == "vlm":
        return "vlm"
    if value == "ocr_only":
        return "ocr_only"
    return "auto"


def _load_unstructured_runtime_settings() -> dict[str, Any]:
    config_path = UNSTRUCTURED_CONFIG_FILE_DEFAULT
    config: dict[str, Any] = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise RuntimeError("must be a JSON object")
        except Exception as ex:
            raise RuntimeError(f"Invalid Unstructured config at {config_path}: {ex}") from ex
    return config


def _load_unstructured_runtime_config() -> tuple[str, str]:
    config = _load_unstructured_runtime_settings()

    api_key = str(
        config.get("api_key")
        or config.get("key_id")
        or config.get("UNSTRUCTURED_API_KEY")
        or config.get("UNSTRUCTURED_API_KEY_AUTH")
        or ""
    ).strip()
    api_url = str(
        config.get("api_url")
        or config.get("UNSTRUCTURED_API_URL")
        or config.get("UNSTRUCTURED_PLATFORM_URL")
        or UNSTRUCTURED_WORKFLOW_API_URL_DEFAULT
    ).strip()

    if not api_key:
        raise RuntimeError(
            f"Unstructured API key missing. Set key_id/api_key in {UNSTRUCTURED_CONFIG_FILE_DEFAULT}."
        )
    if not api_url:
        api_url = UNSTRUCTURED_WORKFLOW_API_URL_DEFAULT
    return api_key, api_url


def _resolve_bookrag_workflow_poll_config() -> tuple[int, int]:
    runtime = _load_unstructured_runtime_settings()
    timeout_seconds = _to_bounded_int(
        runtime.get("bookrag_workflow_poll_seconds")
        or runtime.get("workflow_poll_seconds")
        or os.getenv("BOOKRAG_WORKFLOW_POLL_SECONDS")
        or os.getenv("UNSTRUCTURED_WORKFLOW_POLL_SECONDS"),
        default=UNSTRUCTURED_WORKFLOW_POLL_SECONDS_DEFAULT,
        minimum=10,
        maximum=3600,
    )
    poll_interval_seconds = _to_bounded_int(
        runtime.get("bookrag_workflow_poll_interval_seconds")
        or runtime.get("workflow_poll_interval_seconds")
        or os.getenv("BOOKRAG_WORKFLOW_POLL_INTERVAL_SECONDS")
        or os.getenv("UNSTRUCTURED_WORKFLOW_POLL_INTERVAL_SECONDS"),
        default=UNSTRUCTURED_WORKFLOW_POLL_INTERVAL_DEFAULT,
        minimum=1,
        maximum=60,
    )
    return timeout_seconds, min(timeout_seconds, max(1, poll_interval_seconds))


def _resolve_multi_format_workflow_poll_config() -> tuple[int, int]:
    runtime = _load_unstructured_runtime_settings()
    timeout_seconds = _to_bounded_int(
        runtime.get("multi_format_workflow_poll_seconds")
        or runtime.get("workflow_poll_seconds")
        or os.getenv("MULTI_FORMAT_WORKFLOW_POLL_SECONDS")
        or os.getenv("UNSTRUCTURED_WORKFLOW_POLL_SECONDS"),
        default=UNSTRUCTURED_WORKFLOW_POLL_SECONDS_DEFAULT,
        minimum=10,
        maximum=3600,
    )
    poll_interval_seconds = _to_bounded_int(
        runtime.get("multi_format_workflow_poll_interval_seconds")
        or runtime.get("workflow_poll_interval_seconds")
        or os.getenv("MULTI_FORMAT_WORKFLOW_POLL_INTERVAL_SECONDS")
        or os.getenv("UNSTRUCTURED_WORKFLOW_POLL_INTERVAL_SECONDS"),
        default=UNSTRUCTURED_WORKFLOW_POLL_INTERVAL_DEFAULT,
        minimum=1,
        maximum=60,
    )
    return timeout_seconds, min(timeout_seconds, max(1, poll_interval_seconds))
