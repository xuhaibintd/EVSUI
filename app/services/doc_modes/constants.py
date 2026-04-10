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
    {"value": "multi_format", "label": "Unstructured"},
    {"value": "multi_format_bookrag", "label": "Unstructured BookRAG"},
]
DOC_PIPELINE_MODE_VALUES = {item["value"] for item in DOC_PIPELINE_OPTIONS}

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
