from __future__ import annotations

DOC_PIPELINE_UI_DEFAULTS = {
    "multi_format_strategy": "auto",
    "multi_format_chunk_size": "600",
    "multi_format_chunk_overlap": "80",
    "multi_format_ocr_languages": "",
    "multi_format_keep_tables": "",
    "multi_format_extract_images": "",
}

DOC_PIPELINE_OPTIONS = [
    {"value": "text_core", "label": "Text"},
    {"value": "multi_format", "label": "Multi-Format"},
    {"value": "multi_format_bookrag", "label": "Multi-Format BookRAG"},
]
DOC_PIPELINE_MODE_VALUES = {item["value"] for item in DOC_PIPELINE_OPTIONS}


def _build_multi_format_field_map() -> dict[str, dict[str, object]]:
    defaults = DOC_PIPELINE_UI_DEFAULTS
    return {
        "multi_format_strategy": {
            "name": "multi_format_strategy",
            "label": "multi_format_strategy",
            "kind": "select",
            "default": str(defaults.get("multi_format_strategy", "")),
            "options": [
                {"value": "", "label": "(select)"},
                {"value": "auto", "label": "auto"},
                {"value": "layout", "label": "layout"},
                {"value": "fast", "label": "fast"},
            ],
        },
        "multi_format_chunk_size": {
            "name": "multi_format_chunk_size",
            "label": "multi_format_chunk_size",
            "kind": "number",
            "default": str(defaults.get("multi_format_chunk_size", "")),
            "placeholder": "",
        },
        "multi_format_chunk_overlap": {
            "name": "multi_format_chunk_overlap",
            "label": "multi_format_chunk_overlap",
            "kind": "number",
            "default": str(defaults.get("multi_format_chunk_overlap", "")),
            "placeholder": "",
        },
        "multi_format_ocr_languages": {
            "name": "multi_format_ocr_languages",
            "label": "multi_format_languages",
            "kind": "select",
            "default": str(defaults.get("multi_format_ocr_languages", "")),
            "options": [
                {"value": "", "label": "(auto detect)"},
                {"value": "jpn", "label": "Japanese"},
                {"value": "eng", "label": "English"},
                {"value": "jpn,eng", "label": "Japanese + English"},
                {"value": "chi_sim", "label": "Chinese (Simplified)"},
                {"value": "chi_sim,eng", "label": "Chinese (Simplified) + English"},
                {"value": "chi_tra", "label": "Chinese (Traditional)"},
                {"value": "chi_tra,eng", "label": "Chinese (Traditional) + English"},
                {"value": "kor", "label": "Korean"},
                {"value": "kor,eng", "label": "Korean + English"},
            ],
        },
    }


def _build_multi_format_fields(*names: str) -> list[dict[str, object]]:
    field_map = _build_multi_format_field_map()
    return [dict(field_map[name]) for name in names]


def build_multi_format_ui_fields() -> list[dict[str, object]]:
    return _build_multi_format_fields(
        "multi_format_strategy",
        "multi_format_chunk_size",
        "multi_format_chunk_overlap",
        "multi_format_ocr_languages",
    )


def build_multi_format_bookrag_ui_fields() -> list[dict[str, object]]:
    return _build_multi_format_fields(
        "multi_format_strategy",
        "multi_format_ocr_languages",
    )


def normalize_doc_pipeline_mode(value: str) -> str:
    mode = str(value or "text_core").strip().lower() or "text_core"
    if mode not in DOC_PIPELINE_MODE_VALUES:
        return "text_core"
    return mode


def collect_doc_pipeline_ui_values(form, *, field_max_len: int) -> dict[str, str]:
    values: dict[str, str] = {}
    for ui_field, default_value in DOC_PIPELINE_UI_DEFAULTS.items():
        ui_raw = str(form.get(ui_field, default_value)).strip()
        values[ui_field] = ui_raw[:field_max_len]
    return values


def append_multi_format_summary(message: str, summary: dict | None) -> str:
    if not summary:
        return message

    message = (
        f"{message} "
        f"multi format chunks saved to {summary.get('table_name')} "
        f"({summary.get('chunk_count')} rows from "
        f"{summary.get('document_count')} file(s))."
    )

    processing_mode_label = str(summary.get('processing_mode_label') or '').strip()
    if processing_mode_label:
        message += f" processing_mode={processing_mode_label}."

    strategy_label = str(
        summary.get('effective_partition_strategy_label')
        or summary.get('effective_partition_strategy')
        or ''
    ).strip()
    if strategy_label:
        message += f" strategy={strategy_label}."

    languages_label = str(summary.get('effective_ocr_languages_label') or '').strip()
    if not languages_label:
        effective_languages = summary.get('effective_ocr_languages') or []
        if isinstance(effective_languages, (list, tuple)):
            languages_label = ",".join(str(item).strip() for item in effective_languages if str(item).strip())
    if languages_label:
        message += f" ocr_languages={languages_label}."

    excel_structured_files = summary.get('excel_structured_files') or []
    if excel_structured_files:
        preview = ", ".join(excel_structured_files[:2])
        if len(excel_structured_files) > 2:
            preview += f" +{len(excel_structured_files) - 2} more"
        message += f" excel-structured applied to {preview}."

    scan_fallback_files = summary.get('scan_ocr_fallback_files') or []
    if scan_fallback_files:
        preview = ", ".join(scan_fallback_files[:2])
        if len(scan_fallback_files) > 2:
            preview += f" +{len(scan_fallback_files) - 2} more"
        message += f" scan-ocr fallback applied to {preview}."

    return message
