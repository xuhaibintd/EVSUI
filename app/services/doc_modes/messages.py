from __future__ import annotations


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
