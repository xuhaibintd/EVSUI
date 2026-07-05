from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.services.unstructured_runtime import (
    BOOKRAG_RAW_STAGE_DIR_DEFAULT,
    UNSTRUCTURED_DEBUG_DIR_DEFAULT,
)

MAX_INSPECT_JSON_BYTES = 50 * 1024 * 1024
MAX_LISTED_FILES_PER_SOURCE = 200

INSPECTOR_SOURCES: dict[str, tuple[str, Path]] = {
    "raw_stage": ("Raw Stage", BOOKRAG_RAW_STAGE_DIR_DEFAULT),
    "debug_output": ("Debug Output", UNSTRUCTURED_DEBUG_DIR_DEFAULT),
}


def _safe_relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")


def list_unstructured_json_files() -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for source_key, (source_label, root) in INSPECTOR_SOURCES.items():
        if not root.exists():
            continue
        candidates = sorted(
            (path for path in root.rglob("*.json") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:MAX_LISTED_FILES_PER_SOURCE]
        for path in candidates:
            stat = path.stat()
            rel_path = _safe_relative(path, root)
            files.append(
                {
                    "value": f"{source_key}:{rel_path}",
                    "source": source_key,
                    "source_label": source_label,
                    "relative_path": rel_path,
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "modified_at": stat.st_mtime,
                    "label": f"{source_label} / {rel_path}",
                }
            )
    return files


def resolve_inspector_file(selection: str) -> tuple[str, str, Path]:
    source_key, sep, rel_path = str(selection or "").partition(":")
    if not sep or source_key not in INSPECTOR_SOURCES or not rel_path.strip():
        raise RuntimeError("Select a JSON file to inspect.")
    source_label, root = INSPECTOR_SOURCES[source_key]
    root_resolved = root.resolve()
    path = (root / rel_path).resolve()
    try:
        path.relative_to(root_resolved)
    except ValueError as ex:
        raise RuntimeError("Selected JSON path is outside the allowed inspector roots.") from ex
    if not path.exists() or not path.is_file() or path.suffix.lower() != ".json":
        raise RuntimeError("Selected JSON file does not exist.")
    return source_key, source_label, path


def _shape(value: Any) -> str:
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _elements_from_payload(payload: Any) -> tuple[list[dict[str, Any]], str]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)], "top-level array"
    if isinstance(payload, dict):
        for key in ("raw_elements", "elements", "output", "data"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)], key
        list_values = [(key, value) for key, value in payload.items() if isinstance(value, list)]
        if len(list_values) == 1:
            key, value = list_values[0]
            return [item for item in value if isinstance(item, dict)], str(key)
    return [], "none"


def _metadata(element: dict[str, Any]) -> dict[str, Any]:
    metadata = element.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _text_preview(value: Any, *, max_len: int = 180) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "..."


def _json_preview(value: Any, *, max_len: int = 12000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        text = str(value)
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "\n..."


def build_unstructured_json_inspector_context(selection: str | None = None) -> dict[str, Any]:
    files = list_unstructured_json_files()
    context: dict[str, Any] = {
        "files": files,
        "selected_file": selection or "",
        "summary": None,
        "error": "",
    }
    if not selection:
        return context

    try:
        source_key, source_label, path = resolve_inspector_file(selection)
        size_bytes = path.stat().st_size
        if size_bytes > MAX_INSPECT_JSON_BYTES:
            raise RuntimeError(f"JSON file is too large for inline inspection: {size_bytes} bytes.")
        payload = json.loads(path.read_text(encoding="utf-8"))
        elements, element_source = _elements_from_payload(payload)

        top_keys = sorted(payload.keys()) if isinstance(payload, dict) else []
        type_counts = Counter(str(element.get("type") or "UNKNOWN") for element in elements)
        element_key_counts: Counter[str] = Counter()
        metadata_key_counts: Counter[str] = Counter()
        parent_link_count = 0
        category_depth_values: list[int] = []
        page_numbers: set[int] = set()
        for element in elements:
            metadata = _metadata(element)
            element_key_counts.update(str(key) for key in element.keys())
            metadata_key_counts.update(str(key) for key in metadata.keys())
            if str(metadata.get("parent_id") or "").strip():
                parent_link_count += 1
            try:
                if metadata.get("category_depth") is not None:
                    category_depth_values.append(int(metadata.get("category_depth")))
            except (TypeError, ValueError):
                pass
            try:
                if metadata.get("page_number") is not None:
                    page_numbers.add(int(metadata.get("page_number")))
            except (TypeError, ValueError):
                pass

        element_count = len(elements)
        parent_link_ratio = parent_link_count / element_count if element_count else 0
        max_category_depth = max(category_depth_values) if category_depth_values else None
        page_range_label = "none"
        if page_numbers:
            page_range_label = f"{min(page_numbers)}-{max(page_numbers)} ({len(page_numbers)} pages)"
        if parent_link_count and max_category_depth and max_category_depth > 0:
            structure_verdict = "Hierarchical"
            decomposition_signal = "Use parent_id + category_depth"
        elif element_count and page_numbers and type_counts:
            structure_verdict = "Typed flat elements"
            decomposition_signal = "Use page_number + type"
        elif element_count:
            structure_verdict = "Flat elements"
            decomposition_signal = "Use element order + type"
        else:
            structure_verdict = "No element list"
            decomposition_signal = "Fallback to raw JSON/text"

        sample_elements: list[dict[str, Any]] = []
        for index, element in enumerate(elements, start=1):
            metadata = _metadata(element)
            sample_elements.append(
                {
                    "ordinal": index,
                    "type": str(element.get("type") or ""),
                    "element_id": str(element.get("element_id") or element.get("id") or ""),
                    "page_number": metadata.get("page_number"),
                    "parent_id": str(metadata.get("parent_id") or ""),
                    "category_depth": metadata.get("category_depth"),
                    "text_preview": _text_preview(element.get("text")),
                    "json_preview": _json_preview(element, max_len=12000),
                    "json_compact": json.dumps(element, ensure_ascii=False, separators=(",", ":")),
                }
            )

        context["summary"] = {
            "source": source_key,
            "source_label": source_label,
            "path": str(path),
            "size_bytes": size_bytes,
            "top_shape": _shape(payload),
            "top_keys": top_keys,
            "element_source": element_source,
            "element_count": element_count,
            "type_counts": type_counts.most_common(),
            "element_key_counts": element_key_counts.most_common(),
            "metadata_key_counts": metadata_key_counts.most_common(),
            "has_parent_id": any("parent_id" in _metadata(element) for element in elements),
            "has_category_depth": any("category_depth" in _metadata(element) for element in elements),
            "has_text_as_html": any("text_as_html" in _metadata(element) for element in elements),
            "has_entities": any(isinstance(_metadata(element).get("entities"), dict) for element in elements),
            "has_composite_elements": any(str(element.get("type") or "") == "CompositeElement" for element in elements),
            "structure_verdict": structure_verdict,
            "decomposition_signal": decomposition_signal,
            "parent_link_count": parent_link_count,
            "parent_link_ratio_label": f"{parent_link_ratio:.0%}",
            "category_depth_count": len(category_depth_values),
            "max_category_depth": max_category_depth,
            "page_count": len(page_numbers),
            "page_range_label": page_range_label,
            "text_element_count": sum(count for name, count in type_counts.items() if "Text" in name or name == "Title"),
            "table_count": type_counts.get("Table", 0),
            "image_count": type_counts.get("Image", 0),
            "sample_elements": sample_elements,
            "payload_preview": _json_preview(payload, max_len=12000),
        }
    except Exception as ex:
        context["error"] = str(ex)
    return context
