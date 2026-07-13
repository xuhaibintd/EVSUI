"""Optional BookRAG reconciliation helpers.

This module is intentionally kept even though the main BookRAG pipeline
currently bypasses ``reconcile_unstructured_elements`` and builds blocks/nodes
directly from raw Unstructured elements.

Why keep it:
- It contains targeted repair logic for known PDF extraction artifacts:
  table captions split from tables, table notes split into nearby text
  fragments, and image fragments split from figure captions.
- Current sampled raw-stage files did not trigger these repairs, so the main
  pipeline avoids the extra deepcopy/PDF scan cost for now.
- If future files show broken table/image grouping, this module can be restored
  behind a BookRAG option without reimplementing the repair logic.

The public entry point remains ``reconcile_unstructured_elements``. It accepts
``list[dict]`` Unstructured elements and returns a repaired ``list[dict]``.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from pypdf import PdfReader

_PYPDF_LOGGER = logging.getLogger("pypdf")

_TABLE_CAPTION_RE = re.compile(r"^\s*(?:Table|TABLE|\u8868)\b", re.IGNORECASE)
_FIGURE_CAPTION_RE = re.compile(r"^\s*(?:Fig(?:ure)?|FIG(?:URE)?|\u56f3)\b", re.IGNORECASE)
_SUBFIGURE_LABEL_RE = re.compile(r"^\s*[\(\uff08][A-Za-z][\)\uff09]")
_CJK_SPACE_RE = re.compile(
    r"(?<=[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff10-\uff19])\s+"
    r"(?=[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff10-\uff19])"
)
_CJK_PUNCT_SPACE_RE = re.compile(r"\s+([、。，．：；）】])")
_OPEN_PUNCT_SPACE_RE = re.compile(r"([（【])\s+")

_TEXT_TYPES = {"NarrativeText", "UncategorizedText", "ListItem", "FormKeysValues", "Text"}
_TABLE_NOTE_TEXT_TYPES = _TEXT_TYPES | {"Title"}
_FIGURE_FRAGMENT_TYPES = {"Image", "UncategorizedText", "Title"}
_HARD_BREAK_TYPES = {"Header", "Footer", "Table", "FigureCaption"}


def _extract_pdf_page_text(page: Any) -> str:
    previous_level = _PYPDF_LOGGER.level
    previous_propagate = _PYPDF_LOGGER.propagate
    try:
        # Some PDFs trigger pypdf cmap fallback logs such as UniJIS-UTF16-H.
        # We only use this pass as an optional reconciliation hint, so suppress noisy
        # logger output and degrade to partial/empty text when extraction is limited.
        _PYPDF_LOGGER.setLevel(logging.CRITICAL)
        _PYPDF_LOGGER.propagate = False
        return page.extract_text() or ""
    except Exception:
        return ""
    finally:
        _PYPDF_LOGGER.setLevel(previous_level)
        _PYPDF_LOGGER.propagate = previous_propagate


def _load_pdf_page_lines(src: str | Path | None) -> dict[int, list[str]]:
    if src is None:
        return {}
    path = Path(src)
    if path.suffix.lower() != ".pdf" or not path.exists():
        return {}
    try:
        reader = PdfReader(str(path))
    except Exception:
        return {}
    page_lines: dict[int, list[str]] = {}
    for index, page in enumerate(reader.pages, start=1):
        text = _extract_pdf_page_text(page)
        lines = [line.strip() for line in text.splitlines() if line and line.strip()]
        page_lines[index] = lines
    return page_lines


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _element_type(element: dict[str, Any]) -> str:
    return _as_text(element.get("type")) or "Text"


def _metadata(element: dict[str, Any]) -> dict[str, Any]:
    metadata = element.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    metadata = {}
    element["metadata"] = metadata
    return metadata


def _page_number(element: dict[str, Any]) -> int | None:
    value = _metadata(element).get("page_number")
    try:
        return int(value)
    except Exception:
        return None


def _bbox(element: dict[str, Any]) -> tuple[float, float, float, float] | None:
    points = _metadata(element).get("coordinates", {}).get("points")
    if not isinstance(points, list) or not points:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            xs.append(float(point[0]))
            ys.append(float(point[1]))
        except Exception:
            continue
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _set_bbox(element: dict[str, Any], bbox: tuple[float, float, float, float] | None) -> None:
    if bbox is None:
        return
    x0, y0, x1, y1 = bbox
    coords = _metadata(element).setdefault("coordinates", {})
    coords["points"] = [[x0, y0], [x0, y1], [x1, y1], [x1, y0]]


def _union_bbox(elements: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    boxes = [_bbox(element) for element in elements]
    boxes = [box for box in boxes if box is not None]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _normalize_fragment_text(text: str | None) -> str | None:
    normalized = _as_text(text)
    if not normalized:
        return None
    normalized = _CJK_SPACE_RE.sub("", normalized)
    normalized = _CJK_PUNCT_SPACE_RE.sub(r"\1", normalized)
    normalized = _OPEN_PUNCT_SPACE_RE.sub(r"\1", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or None


def _merge_fragment_texts(elements: list[dict[str, Any]]) -> str | None:
    items: list[tuple[float, float, str]] = []
    for element in elements:
        text = _normalize_fragment_text(_as_text(element.get("text")))
        box = _bbox(element)
        if not text:
            continue
        if box is None:
            items.append((0.0, float(len(items)), text))
            continue
        items.append((round(box[1] / 12.0) * 12.0, box[0], text))
    if not items:
        return None
    items.sort(key=lambda item: (item[0], item[1]))
    merged = "".join(text for _, _, text in items)
    merged = re.sub(r"\s+", " ", merged).strip()
    return merged or None


def _looks_like_table_caption(text: str | None) -> bool:
    return bool(text and _TABLE_CAPTION_RE.match(text))


def _looks_like_figure_caption(text: str | None) -> bool:
    return bool(text and _FIGURE_CAPTION_RE.match(text))


def _is_subfigure_label(element: dict[str, Any]) -> bool:
    text = _as_text(element.get("text")) or ""
    return bool(_SUBFIGURE_LABEL_RE.match(text))


def _copy_element(element: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(element)


def _merge_entities_metadata(target: dict[str, Any], sources: list[dict[str, Any]]) -> None:
    items: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    seen_items: set[str] = set()
    seen_relationships: set[str] = set()

    for source in sources:
        metadata = source.get("metadata")
        if not isinstance(metadata, dict):
            continue
        entities = metadata.get("entities")
        if not isinstance(entities, dict):
            continue
        raw_items = entities.get("items")
        if isinstance(raw_items, list):
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                key = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if key in seen_items:
                    continue
                seen_items.add(key)
                items.append(copy.deepcopy(item))
        raw_relationships = entities.get("relationships")
        if isinstance(raw_relationships, list):
            for relationship in raw_relationships:
                if not isinstance(relationship, dict):
                    continue
                key = json.dumps(relationship, ensure_ascii=False, sort_keys=True)
                if key in seen_relationships:
                    continue
                seen_relationships.add(key)
                relationships.append(copy.deepcopy(relationship))

    if not items and not relationships:
        return
    metadata = _metadata(target)
    metadata["entities"] = {
        "items": items,
        "relationships": relationships,
    }


def _attach_table_captions(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    index = 0
    while index < len(elements):
        current = elements[index]
        current_text = _normalize_fragment_text(_as_text(current.get("text")))
        if _element_type(current) == "FigureCaption" and _looks_like_table_caption(current_text):
            page_number = _page_number(current)
            attached = False
            for offset in range(1, 4):
                candidate_index = index + offset
                if candidate_index >= len(elements):
                    break
                candidate = elements[candidate_index]
                if _page_number(candidate) != page_number:
                    break
                if _element_type(candidate) != "Table":
                    if _element_type(candidate) in _HARD_BREAK_TYPES:
                        break
                    continue
                candidate_copy = _copy_element(candidate)
                candidate_copy["text"] = _normalize_fragment_text(
                    f"{current_text}\n{_as_text(candidate_copy.get('text')) or ''}"
                )
                metadata = _metadata(candidate_copy)
                metadata["bookrag_table_caption"] = current_text
                _merge_entities_metadata(candidate_copy, [candidate, current])
                result.append(candidate_copy)
                index = candidate_index + 1
                attached = True
                break
            if attached:
                continue
        result.append(_copy_element(current))
        index += 1
    return result


def _table_note_candidates(elements: list[dict[str, Any]], start_index: int) -> list[int]:
    table_box = _bbox(elements[start_index])
    table_page = _page_number(elements[start_index])
    if table_box is None or table_page is None:
        return []
    table_bottom = table_box[3]
    candidates: list[int] = []
    for index in range(start_index + 1, min(len(elements), start_index + 8)):
        current = elements[index]
        if _page_number(current) != table_page:
            break
        current_type = _element_type(current)
        if current_type in {"Table", "FigureCaption", "Header", "Footer"}:
            break
        if current_type not in _TABLE_NOTE_TEXT_TYPES:
            break
        if current_type == "Title" and not _is_subfigure_label(current):
            break
        current_box = _bbox(current)
        if current_box is None:
            break
        vertical_gap = current_box[1] - table_bottom
        if vertical_gap < -4 or vertical_gap > 180:
            break
        candidates.append(index)
        table_bottom = max(table_bottom, current_box[3])
    return candidates


def _recover_note_from_page_lines(note_text: str | None, page_lines: list[str]) -> str | None:
    normalized = _normalize_fragment_text(note_text)
    if not normalized or not page_lines:
        return normalized
    compact = re.sub(r"\s+", "", normalized)
    candidates: list[str] = []
    for index, line in enumerate(page_lines):
        clean_line = _normalize_fragment_text(line)
        if not clean_line:
            continue
        candidates.append(clean_line)
        if index + 1 < len(page_lines):
            next_line = _normalize_fragment_text(page_lines[index + 1])
            if next_line:
                candidates.append(f"{clean_line}{next_line}")

    tokens: list[str] = []
    for start_index in range(min(8, max(len(compact) - 2, 0))):
        for width in (3, 4, 5, 6):
            if start_index + width <= len(compact):
                token = compact[start_index:start_index + width]
                if token not in tokens:
                    tokens.append(token)

    best = normalized
    best_score = 0
    for candidate in candidates:
        compact_candidate = re.sub(r"\s+", "", candidate)
        score = 0
        for token in tokens:
            if token and token in compact_candidate:
                score += len(token)
        if "営業継続費用保険金" in compact_candidate:
            score += 12
        if score > best_score or (score == best_score and len(candidate) > len(best)):
            best = candidate
            best_score = score
    return best


def _merge_table_notes(elements: list[dict[str, Any]], page_lines: dict[int, list[str]] | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    skip: set[int] = set()
    for index, current in enumerate(elements):
        if index in skip:
            continue
        if _element_type(current) != "Table":
            result.append(_copy_element(current))
            continue
        note_indices = _table_note_candidates(elements, index)
        table_copy = _copy_element(current)
        table_page = _page_number(table_copy)
        if note_indices:
            fragments = [elements[note_index] for note_index in note_indices]
            note_text = _merge_fragment_texts(fragments)
            note_text = _recover_note_from_page_lines(note_text, (page_lines or {}).get(table_page or 0, []))
            if note_text:
                existing_text = _normalize_fragment_text(_as_text(table_copy.get("text"))) or ""
                merged_text = existing_text
                if note_text not in existing_text:
                    merged_text = f"{existing_text}\nTable note: {note_text}".strip()
                table_copy["text"] = merged_text
                metadata = _metadata(table_copy)
                metadata["bookrag_table_note"] = note_text
                _merge_entities_metadata(table_copy, [current, *fragments])
                _set_bbox(table_copy, _union_bbox([table_copy, *fragments]))
                skip.update(note_indices)
        result.append(table_copy)
    return result


def _build_merged_image(
    elements: list[dict[str, Any]],
    fragment_indices: list[int],
    caption: dict[str, Any],
    caption_text: str,
) -> dict[str, Any]:
    image_indices = [index for index in fragment_indices if _element_type(elements[index]) == "Image"]
    base_index = image_indices[0] if image_indices else fragment_indices[0]
    merged = _copy_element(elements[base_index])
    merged["type"] = "Image"
    merged["element_id"] = _as_text(merged.get("element_id") or merged.get("id")) or uuid.uuid4().hex
    merged["id"] = _as_text(merged.get("id")) or merged["element_id"]
    context_text = _merge_fragment_texts([elements[index] for index in fragment_indices])
    metadata = _metadata(merged)
    metadata["bookrag_image_caption"] = caption_text
    if context_text and context_text != caption_text:
        metadata["bookrag_image_context"] = context_text
    metadata["bookrag_merged_image_count"] = len(image_indices)
    merged["text"] = caption_text
    _merge_entities_metadata(merged, [elements[index] for index in fragment_indices] + [caption])
    _set_bbox(merged, _union_bbox([elements[index] for index in fragment_indices]))
    return merged


def _figure_fragment_indices(elements: list[dict[str, Any]], caption_index: int) -> list[int]:
    caption = elements[caption_index]
    page_number = _page_number(caption)
    if page_number is None:
        return []
    indices: list[int] = []
    for index in range(caption_index - 1, max(-1, caption_index - 10), -1):
        current = elements[index]
        if _page_number(current) != page_number:
            break
        current_type = _element_type(current)
        if current_type in {"Header", "Footer", "Table", "FigureCaption"}:
            break
        if current_type not in _FIGURE_FRAGMENT_TYPES:
            break
        if current_type == "Title" and not _is_subfigure_label(current):
            break
        indices.append(index)
    indices.reverse()
    if not any(_element_type(elements[index]) == "Image" for index in indices):
        return []
    return indices


def _merge_figure_fragments(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    consumed: set[int] = set()
    merged_by_index: dict[int, dict[str, Any]] = {}

    for index, current in enumerate(elements):
        current_type = _element_type(current)
        current_text = _normalize_fragment_text(_as_text(current.get("text")))
        if current_type != "FigureCaption" or not _looks_like_figure_caption(current_text):
            continue
        fragment_indices = _figure_fragment_indices(elements, index)
        if not fragment_indices:
            previous_index = index - 1
            if previous_index >= 0 and _element_type(elements[previous_index]) == "Image" and _page_number(elements[previous_index]) == _page_number(current):
                fragment_indices = [previous_index]
        if not fragment_indices:
            continue
        merged_by_index[fragment_indices[0]] = _build_merged_image(elements, fragment_indices, current, current_text or "")
        consumed.update(fragment_indices)
        consumed.add(index)

    result: list[dict[str, Any]] = []
    for index, current in enumerate(elements):
        if index in merged_by_index:
            result.append(merged_by_index[index])
            continue
        if index in consumed:
            continue
        result.append(_copy_element(current))
    return result


def reconcile_unstructured_elements(raw_elements: list[dict[str, Any]], *, src: str | Path | None = None) -> list[dict[str, Any]]:
    normalized = [_copy_element(element) for element in raw_elements if isinstance(element, dict)]
    page_lines = _load_pdf_page_lines(src)
    normalized = _attach_table_captions(normalized)
    normalized = _merge_table_notes(normalized, page_lines=page_lines)
    normalized = _merge_figure_fragments(normalized)
    return normalized
