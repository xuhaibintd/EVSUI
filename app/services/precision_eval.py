from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any

from pypdf import PdfReader

_ALLOWED_PDF_SUFFIXES = {".pdf"}
_ALLOWED_JSON_SUFFIXES = {".json"}
_WS_RE = re.compile(r"\s+")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _timestamp(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def _is_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = unescape(str(value))
    text = _HTML_TAG_RE.sub(" ", text)
    text = text.replace("\u3000", " ")
    text = _WS_RE.sub("", text)
    return text


def _ngrams(text: str, size: int = 5) -> Counter[str]:
    if not text:
        return Counter()
    if len(text) < size:
        return Counter([text])
    return Counter(text[idx:idx + size] for idx in range(len(text) - size + 1))


def _ngram_metrics(reference: str, hypothesis: str, size: int = 5) -> dict[str, float | int]:
    ref_grams = _ngrams(reference, size)
    hyp_grams = _ngrams(hypothesis, size)
    common = sum((ref_grams & hyp_grams).values())
    ref_total = sum(ref_grams.values())
    hyp_total = sum(hyp_grams.values())
    recall = common / ref_total if ref_total else 1.0
    precision = common / hyp_total if hyp_total else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "common": common,
        "ref_total": ref_total,
        "hyp_total": hyp_total,
    }


def _char_metrics(reference: str, hypothesis: str) -> dict[str, float | int]:
    ref_chars = Counter(reference)
    hyp_chars = Counter(hypothesis)
    common = sum((ref_chars & hyp_chars).values())
    ref_total = sum(ref_chars.values())
    hyp_total = sum(hyp_chars.values())
    recall = common / ref_total if ref_total else 1.0
    precision = common / hyp_total if hyp_total else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "common": common,
        "ref_total": ref_total,
        "hyp_total": hyp_total,
    }


def _round_metric(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    return value


def _read_json(json_path: Path) -> dict[str, Any]:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object at {json_path}.")
    return payload


def _looks_like_intermediate_payload(payload: dict[str, Any]) -> bool:
    raw_elements = payload.get("raw_elements")
    table_rows = payload.get("table_rows")
    return isinstance(raw_elements, list) and isinstance(table_rows, list)


def _build_pdf_option(path: Path, root: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "path": str(path.resolve()),
        "relative_path": _safe_relative(path, root),
        "modified_at": _timestamp(path),
        "size_bytes": path.stat().st_size,
    }


def _build_json_option(path: Path, root: Path) -> dict[str, Any] | None:
    source_file = ""
    source_exists = False
    try:
        payload = _read_json(path)
        if not _looks_like_intermediate_payload(payload):
            return None
        source_file = str(payload.get("source_file") or "").strip()
        source_exists = bool(source_file and Path(source_file).exists())
    except Exception:
        return None
    return {
        "name": path.name,
        "path": str(path.resolve()),
        "relative_path": _safe_relative(path, root),
        "modified_at": _timestamp(path),
        "size_bytes": path.stat().st_size,
        "source_file": source_file,
        "source_exists": source_exists,
    }


def list_precision_eval_files(*, document_root: Path, debug_root: Path) -> dict[str, list[dict[str, Any]]]:
    pdf_options = [
        _build_pdf_option(path, document_root)
        for path in sorted(document_root.rglob("*.pdf"), key=lambda item: item.stat().st_mtime, reverse=True)
        if path.is_file()
    ]
    json_options = [
        option
        for option in (
            _build_json_option(path, debug_root)
            for path in sorted(debug_root.rglob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
            if path.is_file()
        )
        if option is not None
    ]
    return {
        "pdf_options": pdf_options,
        "json_options": json_options,
    }


def resolve_precision_eval_path(raw_path: str, *, allowed_root: Path, expected_suffixes: set[str]) -> Path:
    raw = str(raw_path or "").strip()
    if not raw:
        raise RuntimeError("Path is required.")
    candidate = Path(raw)
    resolved = candidate.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise RuntimeError(f"File not found: {resolved}")
    if resolved.suffix.lower() not in expected_suffixes:
        raise RuntimeError(f"Unsupported file type: {resolved.name}")
    if not _is_within_root(resolved, allowed_root):
        raise RuntimeError(f"Selected file is outside the allowed root: {resolved}")
    return resolved


def _pdf_page_texts(pdf_path: Path) -> tuple[dict[int, str], dict[int, list[str]]]:
    reader = PdfReader(str(pdf_path))
    pages: dict[int, str] = {}
    lines: dict[int, list[str]] = {}
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages[page_number] = text
        lines[page_number] = [line.strip() for line in text.splitlines() if line.strip()]
    return pages, lines


def _raw_elements_per_page(raw_elements: list[Any]) -> tuple[dict[int, list[str]], Counter[str]]:
    per_page: dict[int, list[str]] = defaultdict(list)
    type_counts: Counter[str] = Counter()
    for item in raw_elements:
        if not isinstance(item, dict):
            continue
        type_name = str(item.get("type") or "").strip() or "Unknown"
        type_counts[type_name] += 1
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        page_number = int(metadata.get("page_number") or 0)
        text = str(item.get("text") or "")
        if text:
            per_page[page_number].append(text)
    return per_page, type_counts


def _row_primary_text(row: dict[str, Any]) -> str:
    block_type = str(row.get("block_type") or "").strip().lower()
    content_text = str(row.get("content_text") or "")
    table_html = str(row.get("table_html") or "")
    image_caption = str(row.get("image_caption") or "")
    image_context = str(row.get("image_context") or "")
    section_title = str(row.get("section_title") or "")

    if block_type == "table":
        return table_html or content_text or section_title
    if block_type == "image":
        return image_caption or image_context or content_text or section_title
    return content_text or section_title or table_html


def _table_rows_per_page(rows: list[Any]) -> tuple[dict[int, list[str]], Counter[str], Counter[str]]:
    per_page: dict[int, list[str]] = defaultdict(list)
    block_types: Counter[str] = Counter()
    source_types: Counter[str] = Counter()
    for item in rows:
        if not isinstance(item, dict):
            continue
        block_type = str(item.get("block_type") or "").strip() or "Unknown"
        source_type = str(item.get("source_type") or "").strip() or "Unknown"
        block_types[block_type] += 1
        source_types[source_type] += 1
        page_number = int(item.get("page_number") or 0)
        text = _row_primary_text(item)
        if text:
            per_page[page_number].append(text)
    return per_page, block_types, source_types


def _line_recall(pdf_lines: dict[int, list[str]], per_page: dict[int, list[str]]) -> tuple[int, int]:
    hits = 0
    total = 0
    for page_number, lines in pdf_lines.items():
        page_text = _normalize_text(" ".join(per_page.get(page_number, [])))
        normalized_lines = [_normalize_text(line) for line in lines]
        normalized_lines = [line for line in normalized_lines if line]
        total += len(normalized_lines)
        if page_text:
            hits += sum(1 for line in normalized_lines if line in page_text)
    return hits, total


def _element_precision(pdf_pages: dict[int, str], per_page: dict[int, list[str]]) -> tuple[int, int]:
    hits = 0
    total = 0
    for page_number, fragments in per_page.items():
        page_text = _normalize_text(pdf_pages.get(page_number) or "")
        normalized_fragments = [_normalize_text(fragment) for fragment in fragments]
        normalized_fragments = [fragment for fragment in normalized_fragments if fragment]
        total += len(normalized_fragments)
        if page_text:
            hits += sum(1 for fragment in normalized_fragments if fragment in page_text)
    return hits, total


def _compare_payload(name: str, *, pdf_pages: dict[int, str], pdf_lines: dict[int, list[str]], per_page: dict[int, list[str]]) -> dict[str, Any]:
    all_pdf = "".join(_normalize_text(pdf_pages[idx]) for idx in sorted(pdf_pages))
    all_payload = "".join(_normalize_text(" ".join(per_page.get(idx, []))) for idx in sorted(pdf_pages))
    ngram = _ngram_metrics(all_pdf, all_payload)
    chars = _char_metrics(all_pdf, all_payload)
    line_hits, line_total = _line_recall(pdf_lines, per_page)
    element_hits, element_total = _element_precision(pdf_pages, per_page)

    worst_pages: list[dict[str, Any]] = []
    for idx in sorted(pdf_pages):
        pdf_text = _normalize_text(pdf_pages[idx])
        payload_text = _normalize_text(" ".join(per_page.get(idx, [])))
        page_ngram = _ngram_metrics(pdf_text, payload_text)
        worst_pages.append(
            {
                "page": idx,
                "pdf_chars": len(pdf_text),
                "payload_chars": len(payload_text),
                "precision": page_ngram["precision"],
                "recall": page_ngram["recall"],
                "f1": page_ngram["f1"],
            }
        )

    return {
        "name": name,
        "pdf_chars": len(all_pdf),
        "payload_chars": len(all_payload),
        "ngram_precision": _round_metric(ngram["precision"]),
        "ngram_recall": _round_metric(ngram["recall"]),
        "ngram_f1": _round_metric(ngram["f1"]),
        "char_precision": _round_metric(chars["precision"]),
        "char_recall": _round_metric(chars["recall"]),
        "char_f1": _round_metric(chars["f1"]),
        "line_recall": _round_metric(line_hits / line_total) if line_total else None,
        "line_hits": line_hits,
        "line_total": line_total,
        "element_precision": _round_metric(element_hits / element_total) if element_total else None,
        "element_hits": element_hits,
        "element_total": element_total,
        "worst_pages": [
            {key: _round_metric(value) for key, value in page.items()}
            for page in sorted(worst_pages, key=lambda item: item["recall"])[:8]
        ],
    }


def build_precision_eval_report(*, pdf_path: Path, json_path: Path) -> dict[str, Any]:
    payload = _read_json(json_path)
    pdf_pages, pdf_lines = _pdf_page_texts(pdf_path)
    if not _looks_like_intermediate_payload(payload):
        raise RuntimeError(f"Selected JSON is not an Unstructured intermediate debug file: {json_path}")

    raw_elements = payload.get("raw_elements") if isinstance(payload.get("raw_elements"), list) else []
    table_rows = payload.get("table_rows") if isinstance(payload.get("table_rows"), list) else []
    raw_per_page, raw_type_counts = _raw_elements_per_page(raw_elements)
    row_per_page, block_type_counts, source_type_counts = _table_rows_per_page(table_rows)

    json_source_file = str(payload.get("source_file") or "").strip()
    json_source_path = Path(json_source_file).resolve() if json_source_file else None
    selected_pdf_resolved = pdf_path.resolve()
    source_matches_selected_pdf = bool(json_source_path and json_source_path == selected_pdf_resolved)

    return {
        "pdf_path": str(selected_pdf_resolved),
        "json_path": str(json_path.resolve()),
        "json_source_file": json_source_file,
        "source_matches_selected_pdf": source_matches_selected_pdf,
        "page_count": len(pdf_pages),
        "raw_element_count": len(raw_elements),
        "table_row_count": len(table_rows),
        "raw_type_counts": raw_type_counts.most_common(),
        "block_type_counts": block_type_counts.most_common(),
        "source_type_counts": source_type_counts.most_common(10),
        "raw_elements_metrics": _compare_payload(
            "raw_elements",
            pdf_pages=pdf_pages,
            pdf_lines=pdf_lines,
            per_page=raw_per_page,
        ),
        "table_rows_metrics": _compare_payload(
            "table_rows",
            pdf_pages=pdf_pages,
            pdf_lines=pdf_lines,
            per_page=row_per_page,
        ),
    }
