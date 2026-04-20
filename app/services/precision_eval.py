from __future__ import annotations

import json
import math
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


def build_precision_eval_panel_context(
    *,
    document_root: Path,
    debug_root: Path,
    selected_pdf_path: str = "",
    selected_json_path: str = "",
) -> dict[str, object]:
    file_options = list_precision_eval_files(document_root=document_root, debug_root=debug_root)
    return {
        "pdf_options": file_options.get("pdf_options", []),
        "json_options": file_options.get("json_options", []),
        "selected_pdf_path": str(selected_pdf_path or "").strip(),
        "selected_json_path": str(selected_json_path or "").strip(),
    }



def build_precision_eval_prototype_context() -> dict[str, Any]:
    def _pct(value: float) -> int:
        return int(round(value * 100))

    def _display_pct(value: float) -> str:
        return f"{_pct(value)}%"

    def _tone(value: float) -> str:
        if value >= 0.9:
            return "excellent"
        if value >= 0.82:
            return "good"
        if value >= 0.74:
            return "watch"
        return "risk"

    def _line_chart(series_specs: list[tuple[str, str, list[float]]], labels: list[str]) -> dict[str, Any]:
        width = 720.0
        height = 260.0
        left = 56.0
        right = 18.0
        top = 18.0
        bottom = 36.0
        plot_width = width - left - right
        plot_height = height - top - bottom
        y_min = 0.68
        y_max = 0.95

        def _x(index: int) -> float:
            if len(labels) == 1:
                return left + plot_width / 2
            return left + (plot_width * index / (len(labels) - 1))

        def _y(value: float) -> float:
            return top + (y_max - value) / (y_max - y_min) * plot_height

        tick_values = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
        y_ticks = [{"value": _display_pct(item), "y": round(_y(item), 1)} for item in tick_values]
        x_ticks = [{"label": label, "x": round(_x(index), 1)} for index, label in enumerate(labels)]

        series: list[dict[str, Any]] = []
        for name, color, values in series_specs:
            points = []
            for index, value in enumerate(values):
                points.append({"cx": round(_x(index), 1), "cy": round(_y(value), 1), "value": _display_pct(value)})
            path_data = " ".join((f"M {point['cx']} {point['cy']}" if idx == 0 else f"L {point['cx']} {point['cy']}") for idx, point in enumerate(points))
            series.append({"name": name, "color": color, "path": path_data, "points": points})

        return {
            "viewbox": f"0 0 {int(width)} {int(height)}",
            "width": int(width),
            "height": int(height),
            "left": left,
            "right": width - right,
            "top": top,
            "bottom": height - bottom,
            "y_ticks": y_ticks,
            "x_ticks": x_ticks,
            "series": series,
        }

    def _radar_chart(metrics: list[tuple[str, float]]) -> dict[str, Any]:
        size = 320.0
        center = size / 2
        radius = 102.0
        levels = [0.25, 0.5, 0.75, 1.0]
        axes = []
        value_points = []
        for index, (label, value) in enumerate(metrics):
            angle = (-math.pi / 2) + (2 * math.pi * index / len(metrics))
            outer_x = center + radius * math.cos(angle)
            outer_y = center + radius * math.sin(angle)
            value_x = center + radius * value * math.cos(angle)
            value_y = center + radius * value * math.sin(angle)
            label_x = center + (radius + 26) * math.cos(angle)
            label_y = center + (radius + 26) * math.sin(angle)
            anchor = "middle"
            if label_x < center - 12:
                anchor = "end"
            elif label_x > center + 12:
                anchor = "start"
            axes.append(
                {
                    "label": label,
                    "outer_x": round(outer_x, 1),
                    "outer_y": round(outer_y, 1),
                    "label_x": round(label_x, 1),
                    "label_y": round(label_y, 1),
                    "anchor": anchor,
                    "value": _display_pct(value),
                }
            )
            value_points.append(f"{round(value_x, 1)},{round(value_y, 1)}")

        grid_paths = []
        for level in levels:
            polygon = []
            for index in range(len(metrics)):
                angle = (-math.pi / 2) + (2 * math.pi * index / len(metrics))
                polygon.append(f"{round(center + radius * level * math.cos(angle), 1)},{round(center + radius * level * math.sin(angle), 1)}")
            grid_paths.append({"points": " ".join(polygon), "label": _display_pct(level)})

        return {
            "viewbox": f"0 0 {int(size)} {int(size)}",
            "center": center,
            "axes": axes,
            "grid_paths": grid_paths,
            "value_polygon": " ".join(value_points),
        }

    retrieval_series = [
        ("Precision@5", "#2563eb", [0.72, 0.75, 0.77, 0.80, 0.82, 0.84]),
        ("Recall@10", "#137333", [0.81, 0.83, 0.84, 0.87, 0.89, 0.91]),
        ("nDCG@10", "#d97706", [0.74, 0.76, 0.79, 0.81, 0.84, 0.86]),
    ]
    trend_labels = [f"B0{index}" for index in range(1, 7)]
    retrieval_trend_chart = _line_chart(retrieval_series, trend_labels)

    retrieval_segments = [
        {"name": "Financial Results", "precision": 0.89, "recall": 0.94, "mrr": 0.91, "ndcg": 0.90},
        {"name": "Governance", "precision": 0.85, "recall": 0.90, "mrr": 0.87, "ndcg": 0.86},
        {"name": "Risk Disclosure", "precision": 0.80, "recall": 0.88, "mrr": 0.83, "ndcg": 0.82},
        {"name": "Dividend / IR", "precision": 0.82, "recall": 0.89, "mrr": 0.85, "ndcg": 0.84},
    ]
    for item in retrieval_segments:
        item["precision_display"] = _display_pct(item["precision"])
        item["recall_display"] = _display_pct(item["recall"])
        item["precision_percent"] = _pct(item["precision"])
        item["recall_percent"] = _pct(item["recall"])
        item["mrr_display"] = f"{item['mrr']:.2f}"
        item["ndcg_display"] = f"{item['ndcg']:.2f}"
        item["tone"] = _tone((item["precision"] + item["recall"]) / 2)

    quality_bands = [
        {"label": "Highly Relevant", "count": 58, "ratio": 0.48, "tone": "band-high"},
        {"label": "Partially Relevant", "count": 31, "ratio": 0.26, "tone": "band-mid"},
        {"label": "Irrelevant", "count": 18, "ratio": 0.15, "tone": "band-low"},
        {"label": "Missed Relevant", "count": 13, "ratio": 0.11, "tone": "band-miss"},
    ]
    for item in quality_bands:
        item["ratio_display"] = _display_pct(item["ratio"])
        item["width"] = f"{max(_pct(item['ratio']), 12)}%"

    sample_queries = [
        {
            "query": "What is the FY2026 dividend outlook?",
            "top_doc": "IR Summary FY2026 Q3",
            "precision": 1.00,
            "recall": 0.92,
            "rank": 1,
            "note": "Top hit is exact and all expected evidence appears within rank 5.",
        },
        {
            "query": "List major governance policy revisions.",
            "top_doc": "Corporate Governance Report",
            "precision": 0.80,
            "recall": 0.89,
            "rank": 2,
            "note": "One relevant governance appendix appears slightly lower in the ranked list.",
        },
        {
            "query": "Find risk-factor changes after Q2.",
            "top_doc": "Securities Report Addendum",
            "precision": 0.60,
            "recall": 0.83,
            "rank": 3,
            "note": "The first hit is relevant, but too many adjacent policy documents are mixed in.",
        },
    ]
    for item in sample_queries:
        item["precision_display"] = _display_pct(item["precision"])
        item["recall_display"] = _display_pct(item["recall"])
        item["precision_percent"] = _pct(item["precision"])
        item["recall_percent"] = _pct(item["recall"])
        item["tone"] = _tone((item["precision"] + item["recall"]) / 2)

    answer_kpis = [
        {"label": "Correctness", "display": "87%", "delta": "+2.8 pts", "description": "Rubric-judged answer correctness against a gold answer set.", "tone": "good"},
        {"label": "Groundedness", "display": "93%", "delta": "+1.9 pts", "description": "Answer statements supported by retrieved evidence spans.", "tone": "excellent"},
        {"label": "Citation Precision", "display": "89%", "delta": "+3.6 pts", "description": "Cited documents that actually support the generated answer.", "tone": "good"},
        {"label": "Completeness", "display": "81%", "delta": "+1.4 pts", "description": "Coverage of expected answer facets from the reference rubric.", "tone": "watch"},
    ]

    answer_radar_metrics = [("Correctness", 0.87), ("Groundedness", 0.93), ("Citation", 0.89), ("Completeness", 0.81), ("Consistency", 0.85)]
    answer_radar = _radar_chart(answer_radar_metrics)
    answer_dimensions = []
    dimension_notes = {
        "Correctness": "Matches the expected answer intent and key facts.",
        "Groundedness": "Claims are explicitly supported by retrieved evidence.",
        "Citation": "Cited sources actually back the attached claim.",
        "Completeness": "Covers the expected answer facets from the rubric.",
        "Consistency": "Avoids contradictions across the final response.",
    }
    for label, value in answer_radar_metrics:
        answer_dimensions.append(
            {
                "label": label,
                "display": _display_pct(value),
                "percent": _pct(value),
                "tone": _tone(value),
                "note": dimension_notes.get(label, ""),
            }
        )

    answer_outcomes = [
        {"label": "Pass", "count": 74, "ratio": 0.62, "tone": "band-high"},
        {"label": "Minor Issues", "count": 28, "ratio": 0.23, "tone": "band-mid"},
        {"label": "Major Issues", "count": 12, "ratio": 0.10, "tone": "band-miss"},
        {"label": "Unsupported", "count": 6, "ratio": 0.05, "tone": "band-low"},
    ]
    for item in answer_outcomes:
        item["ratio_display"] = _display_pct(item["ratio"])
        item["width"] = f"{max(_pct(item['ratio']), 10)}%"

    answer_heatmap_rows = [
        ("Dividend Outlook", {"correctness": 0.91, "groundedness": 0.95, "citation": 0.93, "completeness": 0.88}),
        ("Governance Changes", {"correctness": 0.88, "groundedness": 0.92, "citation": 0.90, "completeness": 0.84}),
        ("Risk Factors", {"correctness": 0.79, "groundedness": 0.89, "citation": 0.84, "completeness": 0.76}),
        ("Segment Performance", {"correctness": 0.86, "groundedness": 0.94, "citation": 0.87, "completeness": 0.80}),
    ]
    answer_heatmap = []
    for label, metrics in answer_heatmap_rows:
        cells = []
        for metric_name, metric_value in metrics.items():
            cells.append({"metric": metric_name.title(), "display": _display_pct(metric_value), "tone": _tone(metric_value)})
        answer_heatmap.append({"label": label, "cells": cells})

    sample_answers = [
        {"question": "Summarize the announced dividend policy.", "verdict": "Pass", "tone": "excellent", "note": "All claims map to the cited IR summary and no unsupported wording appears."},
        {"question": "Explain the latest governance revision.", "verdict": "Minor Issue", "tone": "watch", "note": "The answer is correct overall, but one citation points to an older governance appendix."},
        {"question": "Describe newly disclosed risk factors.", "verdict": "Major Issue", "tone": "risk", "note": "The answer merges two adjacent disclosures and omits one required evidence span."},
    ]

    return {
        "summary": {
            "title": "Precision Evaluation Prototype",
            "subtitle": "TREC-style retrieval evaluation plus rubric-based RAG answer validation, shown with synthetic benchmark data.",
            "sample_size": "120 test queries",
            "judgments": "960 graded retrieval judgments",
            "answer_set": "120 rubric-scored answers",
        },
        "retrieval": {
            "kpis": [
                {"label": "Precision@5", "display": "84%", "delta": "+3.1 pts", "tone": "good", "description": "Share of top-5 retrieved documents judged relevant."},
                {"label": "Recall@10", "display": "91%", "delta": "+2.4 pts", "tone": "excellent", "description": "Relevant documents recovered within the first 10 ranks."},
                {"label": "MRR", "display": "0.88", "delta": "+0.05", "tone": "good", "description": "Mean reciprocal rank of the first relevant result."},
                {"label": "nDCG@10", "display": "0.86", "delta": "+0.04", "tone": "good", "description": "Ranking quality with graded relevance weighting."},
            ],
            "trend_chart": retrieval_trend_chart,
            "quality_bands": quality_bands,
            "segments": retrieval_segments,
            "sample_queries": sample_queries,
            "methodology": [
                "TREC-style offline evaluation with pre-judged query-document pairs.",
                "Three-level relevance labels: highly relevant, partially relevant, irrelevant.",
                "Primary metrics: Precision@5, Recall@10, MRR, and nDCG@10.",
                "Use this view to judge whether the right documents are retrieved, not whether the final answer is perfect.",
            ],
        },
        "answer_quality": {
            "kpis": answer_kpis,
            "radar": answer_radar,
            "dimensions": answer_dimensions,
            "outcomes": answer_outcomes,
            "heatmap": answer_heatmap,
            "sample_answers": sample_answers,
            "methodology": [
                "Pointwise rubric evaluation on correctness, groundedness, citation precision, completeness, and consistency.",
                "Answer claims are checked against the retrieved evidence set, not only against model fluency.",
                "Citation precision measures whether the cited source truly supports the claim it is attached to.",
                "Use this view to judge whether retrieval is translated into a reliable final response.",
            ],
        },
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


def _row_block_type(row: dict[str, Any]) -> str:
    type_name = str(row.get("type") or "").strip().lower()
    text = str(row.get("text") or "")
    text_as_html = str(row.get("text_as_html") or "")
    if text_as_html or "table" in type_name:
        return "table"
    if any(token in type_name for token in ("image", "figure", "picture")):
        return "image"
    if type_name in {"title", "section-header", "sectionheader", "header", "headline"} and text:
        return "section"
    return "text"


def _row_primary_text(row: dict[str, Any]) -> str:
    block_type = _row_block_type(row)
    text = str(row.get("text") or "")
    text_as_html = str(row.get("text_as_html") or "")
    image_caption = str(row.get("image_caption") or "")
    image_context = str(row.get("image_context") or "")

    if block_type == "table":
        return text_as_html or text
    if block_type == "image":
        return image_caption or image_context or text
    return text or text_as_html


def _table_rows_per_page(rows: list[Any]) -> tuple[dict[int, list[str]], Counter[str], Counter[str]]:
    per_page: dict[int, list[str]] = defaultdict(list)
    block_types: Counter[str] = Counter()
    types: Counter[str] = Counter()
    for item in rows:
        if not isinstance(item, dict):
            continue
        block_type = _row_block_type(item)
        type = str(item.get("type") or "").strip() or "Unknown"
        block_types[block_type] += 1
        types[type] += 1
        page_number = int(item.get("page_number") or 0)
        text = _row_primary_text(item)
        if text:
            per_page[page_number].append(text)
    return per_page, block_types, types


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
    row_per_page, block_type_counts, type_counts = _table_rows_per_page(table_rows)

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
        "type_counts": type_counts.most_common(10),
        "source_type_counts": type_counts.most_common(10),
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
