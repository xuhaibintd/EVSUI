from __future__ import annotations

DOC_PIPELINE_UI_DEFAULTS = {
    "multi_format_strategy": "auto",
    "multi_format_chunk_size": "600",
    "multi_format_chunk_overlap": "80",
    "multi_format_ocr_languages": "",
    "multi_format_vlm_provider": "",
    "multi_format_vlm_model": "",
    "multi_format_vlm_provider_api_key": "",
    "multi_format_hi_res_model_name": "",
    "multi_format_infer_table_structure": "true",
    "multi_format_extract_image_block_types": "auto",
    "multi_format_enable_generative_ocr": "true",
    "multi_format_enable_table_to_html": "true",
    "multi_format_enable_table_description": "false",
    "multi_format_enable_image_description": "false",
    "multi_format_generative_ocr_subtype": "openai_ocr",
    "multi_format_generative_ocr_provider_type": "openai",
    "multi_format_generative_ocr_model": "gpt-5-mini",
    "multi_format_table_to_html_subtype": "twopass_table2html",
    "multi_format_table_to_html_provider_type": "",
    "multi_format_table_to_html_model": "",
    "multi_format_table_description_subtype": "openai_table_description",
    "multi_format_table_description_provider_type": "openai",
    "multi_format_table_description_model": "gpt-5-mini",
    "multi_format_image_description_subtype": "openai_image_description",
    "multi_format_image_description_provider_type": "openai",
    "multi_format_image_description_model": "gpt-5-mini",
    "multi_format_bookrag_strategy": "auto",
    "multi_format_bookrag_ocr_languages": "",
    "multi_format_keep_tables": "",
    "multi_format_extract_images": "",
    "multi_format_bookrag_chunk_size": "1200",
    "multi_format_bookrag_chunk_overlap": "120",
    "multi_format_bookrag_new_after_n_chars": "1000",
    "multi_format_bookrag_combine_under_n_chars": "600",
    "multi_format_bookrag_multipage_sections": "true",
    "multi_format_bookrag_coordinates": "true",
    "multi_format_bookrag_extract_image_block_types": "auto",
}

DOC_PIPELINE_OPTIONS = [
    {"value": "text_core", "label": "Text PDF Only"},
    {"value": "multi_format", "label": "Multi-Format"},
    {"value": "multi_format_bookrag", "label": "Multi-Format BookRAG"},
]
DOC_PIPELINE_MODE_VALUES = {item["value"] for item in DOC_PIPELINE_OPTIONS}


def _build_multi_format_field_map() -> dict[str, dict[str, object]]:
    defaults = DOC_PIPELINE_UI_DEFAULTS
    return {
        "multi_format_strategy": {
            "name": "multi_format_strategy",
            "label": "Partition Route",
            "help": "",
            "kind": "select",
            "default": str(defaults.get("multi_format_strategy", "")),
            "options": [
                {"value": "", "label": "(select route)"},
                {"value": "auto", "label": "Auto"},
                {"value": "hi_res", "label": "High Res"},
                {"value": "vlm", "label": "VLM"},
                {"value": "fast", "label": "Fast"},
            ],
        },
        "multi_format_ocr_languages": {
            "wrapper_attrs": {"data-partition-routes": "hi_res"},
            "name": "multi_format_ocr_languages",
            "label": "OCR Languages",
            "help": "Optional language hint.",
            "kind": "select",
            "default": str(defaults.get("multi_format_ocr_languages", "")),
            "options": [
                {"value": "", "label": "(auto detect / route default)"},
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
        "multi_format_vlm_provider": {
            "wrapper_attrs": {"data-partition-routes": "auto vlm"},
            "name": "multi_format_vlm_provider",
            "label": "VLM Provider",
            "help": "Provider for Auto/VLM.",
            "kind": "select",
            "default": str(defaults.get("multi_format_vlm_provider", "")),
            "options": [
                {"value": "", "label": "(platform default)"},
                {"value": "anthropic", "label": "Anthropic"},
                {"value": "auto", "label": "Auto"},
                {"value": "bedrock", "label": "Bedrock"},
                {"value": "openai", "label": "OpenAI"},
                {"value": "vertexai", "label": "Vertex AI"},
            ],
        },
        "multi_format_vlm_model": {
            "wrapper_attrs": {"data-partition-routes": "auto vlm"},
            "name": "multi_format_vlm_model",
            "label": "VLM Model",
            "help": "Optional explicit model.",
            "kind": "text",
            "default": str(defaults.get("multi_format_vlm_model", "")),
            "placeholder": "gpt-4o / gpt-4o-mini / claude-sonnet...",
        },
        "multi_format_vlm_provider_api_key": {
            "wrapper_attrs": {"data-partition-routes": "auto vlm"},
            "name": "multi_format_vlm_provider_api_key",
            "label": "VLM Provider API Key",
            "help": "Optional non-default key.",
            "kind": "text",
            "default": str(defaults.get("multi_format_vlm_provider_api_key", "")),
            "placeholder": "optional",
        },
        "multi_format_hi_res_model_name": {
            "wrapper_attrs": {"data-partition-routes": "hi_res"},
            "name": "multi_format_hi_res_model_name",
            "label": "High Res Model",
            "help": "Optional explicit model.",
            "kind": "text",
            "default": str(defaults.get("multi_format_hi_res_model_name", "")),
            "placeholder": "optional",
        },
        "multi_format_infer_table_structure": {
            "wrapper_attrs": {"data-partition-routes": "hi_res"},
            "name": "multi_format_infer_table_structure",
            "label": "Infer Table Structure",
            "help": "Enable table structure.",
            "kind": "select",
            "default": str(defaults.get("multi_format_infer_table_structure", "true")),
            "options": [
                {"value": "true", "label": "true"},
                {"value": "false", "label": "false"},
            ],
        },
        "multi_format_extract_image_block_types": {
            "wrapper_attrs": {"data-partition-routes": "hi_res"},
            "name": "multi_format_extract_image_block_types",
            "label": "Image/Table Block Extraction",
            "help": "Extract image/table blocks.",
            "kind": "select",
            "default": str(defaults.get("multi_format_extract_image_block_types", "auto")),
            "options": [
                {"value": "auto", "label": "auto"},
                {"value": "", "label": "(off)"},
                {"value": "Image", "label": "Image"},
                {"value": "Table", "label": "Table"},
                {"value": "Image,Table", "label": "Image + Table"},
            ],
        },
        "multi_format_enable_generative_ocr": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_enable_generative_ocr",
            "label": "Generative OCR",
            "help": "Auto/High Res only.",
            "kind": "select",
            "default": str(defaults.get("multi_format_enable_generative_ocr", "true")),
            "options": [
                {"value": "true", "label": "true"},
                {"value": "false", "label": "false"},
            ],
        },
        "multi_format_enable_table_to_html": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_enable_table_to_html",
            "label": "Table to HTML",
            "help": "Auto/High Res only.",
            "kind": "select",
            "default": str(defaults.get("multi_format_enable_table_to_html", "true")),
            "options": [
                {"value": "true", "label": "true"},
                {"value": "false", "label": "false"},
            ],
        },
        "multi_format_enable_table_description": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_enable_table_description",
            "label": "Table Description",
            "help": "Auto/High Res only.",
            "kind": "select",
            "default": str(defaults.get("multi_format_enable_table_description", "false")),
            "options": [
                {"value": "true", "label": "true"},
                {"value": "false", "label": "false"},
            ],
        },
        "multi_format_enable_image_description": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_enable_image_description",
            "label": "Image Description",
            "help": "Auto/High Res only.",
            "kind": "select",
            "default": str(defaults.get("multi_format_enable_image_description", "false")),
            "options": [
                {"value": "true", "label": "true"},
                {"value": "false", "label": "false"},
            ],
        },
        "multi_format_generative_ocr_subtype": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_generative_ocr_subtype",
            "label": "Generative OCR Subtype",
            "help": "Advanced enrichment subtype.",
            "kind": "text",
            "default": str(defaults.get("multi_format_generative_ocr_subtype", "openai_ocr")),
            "placeholder": "openai_ocr",
        },
        "multi_format_generative_ocr_provider_type": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_generative_ocr_provider_type",
            "label": "Generative OCR Provider",
            "help": "Advanced enrichment provider type.",
            "kind": "text",
            "default": str(defaults.get("multi_format_generative_ocr_provider_type", "openai")),
            "placeholder": "openai",
        },
        "multi_format_generative_ocr_model": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_generative_ocr_model",
            "label": "Generative OCR Model",
            "help": "Advanced enrichment model.",
            "kind": "text",
            "default": str(defaults.get("multi_format_generative_ocr_model", "gpt-5-mini")),
            "placeholder": "gpt-5-mini",
        },
        "multi_format_table_to_html_subtype": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_table_to_html_subtype",
            "label": "Table to HTML Subtype",
            "help": "Advanced enrichment subtype.",
            "kind": "text",
            "default": str(defaults.get("multi_format_table_to_html_subtype", "twopass_table2html")),
            "placeholder": "twopass_table2html",
        },
        "multi_format_table_to_html_provider_type": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_table_to_html_provider_type",
            "label": "Table to HTML Provider",
            "help": "Advanced enrichment provider type.",
            "kind": "text",
            "default": str(defaults.get("multi_format_table_to_html_provider_type", "")),
            "placeholder": "optional",
        },
        "multi_format_table_to_html_model": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_table_to_html_model",
            "label": "Table to HTML Model",
            "help": "Advanced enrichment model.",
            "kind": "text",
            "default": str(defaults.get("multi_format_table_to_html_model", "")),
            "placeholder": "optional",
        },
        "multi_format_table_description_subtype": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_table_description_subtype",
            "label": "Table Description Subtype",
            "help": "Advanced enrichment subtype.",
            "kind": "text",
            "default": str(defaults.get("multi_format_table_description_subtype", "openai_table_description")),
            "placeholder": "openai_table_description",
        },
        "multi_format_table_description_provider_type": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_table_description_provider_type",
            "label": "Table Description Provider",
            "help": "Advanced enrichment provider type.",
            "kind": "text",
            "default": str(defaults.get("multi_format_table_description_provider_type", "openai")),
            "placeholder": "openai",
        },
        "multi_format_table_description_model": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_table_description_model",
            "label": "Table Description Model",
            "help": "Advanced enrichment model.",
            "kind": "text",
            "default": str(defaults.get("multi_format_table_description_model", "gpt-5-mini")),
            "placeholder": "gpt-5-mini",
        },
        "multi_format_image_description_subtype": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_image_description_subtype",
            "label": "Image Description Subtype",
            "help": "Advanced enrichment subtype.",
            "kind": "text",
            "default": str(defaults.get("multi_format_image_description_subtype", "openai_image_description")),
            "placeholder": "openai_image_description",
        },
        "multi_format_image_description_provider_type": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_image_description_provider_type",
            "label": "Image Description Provider",
            "help": "Advanced enrichment provider type.",
            "kind": "text",
            "default": str(defaults.get("multi_format_image_description_provider_type", "openai")),
            "placeholder": "openai",
        },
        "multi_format_image_description_model": {
            "wrapper_attrs": {"data-partition-routes": "auto hi_res"},
            "name": "multi_format_image_description_model",
            "label": "Image Description Model",
            "help": "Advanced enrichment model.",
            "kind": "text",
            "default": str(defaults.get("multi_format_image_description_model", "gpt-5-mini")),
            "placeholder": "gpt-5-mini",
        },
        "multi_format_chunk_size": {
            "name": "multi_format_chunk_size",
            "label": "Chunk Size",
            "help": "Character budget per chunk after partition and enrichments.",
            "kind": "number",
            "default": str(defaults.get("multi_format_chunk_size", "")),
            "placeholder": "",
        },
        "multi_format_chunk_overlap": {
            "name": "multi_format_chunk_overlap",
            "label": "Chunk Overlap",
            "help": "Character overlap between neighboring chunks.",
            "kind": "number",
            "default": str(defaults.get("multi_format_chunk_overlap", "")),
            "placeholder": "",
        },
        "multi_format_bookrag_strategy": {
            "name": "multi_format_bookrag_strategy",
            "label": "bookrag_strategy",
            "kind": "select",
            "default": str(defaults.get("multi_format_bookrag_strategy", "")),
            "options": [
                {"value": "", "label": "(select)"},
                {"value": "auto", "label": "auto"},
                {"value": "hi_res", "label": "hi_res"},
                {"value": "vlm", "label": "vlm"},
                {"value": "fast", "label": "fast"},
            ],
        },
        "multi_format_bookrag_ocr_languages": {
            "name": "multi_format_bookrag_ocr_languages",
            "label": "bookrag_languages",
            "kind": "select",
            "default": str(defaults.get("multi_format_bookrag_ocr_languages", "")),
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
        "multi_format_bookrag_chunk_size": {
            "name": "multi_format_bookrag_chunk_size",
            "label": "bookrag_chunk_size",
            "kind": "number",
            "default": str(defaults.get("multi_format_bookrag_chunk_size", "1200")),
            "placeholder": "",
        },
        "multi_format_bookrag_chunk_overlap": {
            "name": "multi_format_bookrag_chunk_overlap",
            "label": "bookrag_chunk_overlap",
            "kind": "number",
            "default": str(defaults.get("multi_format_bookrag_chunk_overlap", "120")),
            "placeholder": "",
        },
        "multi_format_bookrag_new_after_n_chars": {
            "name": "multi_format_bookrag_new_after_n_chars",
            "label": "bookrag_new_after_n_chars",
            "kind": "number",
            "default": str(defaults.get("multi_format_bookrag_new_after_n_chars", "1000")),
            "placeholder": "",
        },
        "multi_format_bookrag_combine_under_n_chars": {
            "name": "multi_format_bookrag_combine_under_n_chars",
            "label": "bookrag_combine_under_n_chars",
            "kind": "number",
            "default": str(defaults.get("multi_format_bookrag_combine_under_n_chars", "600")),
            "placeholder": "",
        },
        "multi_format_bookrag_multipage_sections": {
            "name": "multi_format_bookrag_multipage_sections",
            "label": "bookrag_multipage_sections",
            "kind": "select",
            "default": str(defaults.get("multi_format_bookrag_multipage_sections", "true")),
            "options": [
                {"value": "true", "label": "true"},
                {"value": "false", "label": "false"},
            ],
        },
        "multi_format_bookrag_coordinates": {
            "name": "multi_format_bookrag_coordinates",
            "label": "bookrag_coordinates",
            "kind": "select",
            "default": str(defaults.get("multi_format_bookrag_coordinates", "true")),
            "options": [
                {"value": "true", "label": "true"},
                {"value": "false", "label": "false"},
            ],
        },
        "multi_format_bookrag_extract_image_block_types": {
            "name": "multi_format_bookrag_extract_image_block_types",
            "label": "bookrag_extract_image_block_types",
            "kind": "select",
            "default": str(defaults.get("multi_format_bookrag_extract_image_block_types", "")),
            "options": [
                {"value": "", "label": "(off)"},
                {"value": "auto", "label": "auto (Image,Table)"},
                {"value": "Image", "label": "Image"},
                {"value": "Image,Table", "label": "Image,Table"},
            ],
        },
    }


def _build_multi_format_fields(*names: str) -> list[dict[str, object]]:
    field_map = _build_multi_format_field_map()
    return [dict(field_map[name]) for name in names]


def build_multi_format_ui_fields() -> list[dict[str, object]]:
    return _build_multi_format_fields(
        "multi_format_strategy",
        "multi_format_ocr_languages",
        "multi_format_vlm_provider",
        "multi_format_vlm_model",
        "multi_format_vlm_provider_api_key",
        "multi_format_hi_res_model_name",
        "multi_format_infer_table_structure",
        "multi_format_extract_image_block_types",
        "multi_format_enable_generative_ocr",
        "multi_format_enable_table_to_html",
        "multi_format_enable_table_description",
        "multi_format_enable_image_description",
        "multi_format_chunk_size",
        "multi_format_chunk_overlap",
    )


def build_multi_format_bookrag_ui_fields() -> list[dict[str, object]]:
    return _build_multi_format_fields(
        "multi_format_bookrag_strategy",
        "multi_format_bookrag_ocr_languages",
        "multi_format_bookrag_chunk_size",
        "multi_format_bookrag_chunk_overlap",
        "multi_format_bookrag_new_after_n_chars",
        "multi_format_bookrag_combine_under_n_chars",
        "multi_format_bookrag_multipage_sections",
        "multi_format_bookrag_coordinates",
        "multi_format_bookrag_extract_image_block_types",
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
