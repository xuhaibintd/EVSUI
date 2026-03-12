from __future__ import annotations

DOC_PIPELINE_UI_DEFAULTS = {
    "multi_format_strategy": "",
    "multi_format_chunk_size": "",
    "multi_format_chunk_overlap": "",
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


def build_multi_format_ui_fields() -> list[dict[str, object]]:
    defaults = DOC_PIPELINE_UI_DEFAULTS
    return [
        {
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
        {
            "name": "multi_format_chunk_size",
            "label": "multi_format_chunk_size",
            "kind": "number",
            "default": str(defaults.get("multi_format_chunk_size", "")),
            "placeholder": "",
        },
        {
            "name": "multi_format_chunk_overlap",
            "label": "multi_format_chunk_overlap",
            "kind": "number",
            "default": str(defaults.get("multi_format_chunk_overlap", "")),
            "placeholder": "",
        },
        {
            "name": "multi_format_ocr_languages",
            "label": "multi_format_ocr_languages",
            "kind": "text",
            "default": str(defaults.get("multi_format_ocr_languages", "")),
            "placeholder": "",
        },
    ]


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
    return (
        f"{message} "
        f"multi format chunks saved to {summary.get('table_name')} "
        f"({summary.get('chunk_count')} rows from "
        f"{summary.get('document_count')} file(s))."
    )
