from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

_TITLE_MARKERS = {"title", "section-header", "sectionheader", "header", "headline"}
_TABLE_MARKERS = ("table",)
_IMAGE_MARKERS = ("image", "figure", "picture")
BOOKRAG_SECTION_PROFILE_DEFAULT = "jp"
_IMAGE_CAPTION_MAX_LEN = 4000
_IMAGE_CONTEXT_MAX_LEN = 32000
_IMAGE_CONTEXT_NEIGHBOR_WINDOW = 2

_JP_CHAPTER_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"^\s*\u7b2c[0-9\u4e00-\u9fff]+\u7ae0"), 1),
    (re.compile(r"^\s*\u7b2c[0-9\u4e00-\u9fff]+\u7bc0"), 2),
    (re.compile(r"^\s*\u7b2c[0-9\u4e00-\u9fff]+\u6b3e"), 3),
    (re.compile(r"^\s*\u7b2c[0-9\u4e00-\u9fff]+\u76ee"), 4),
    (re.compile(r"^\s*\u7b2c[0-9\u4e00-\u9fff]+\u6761"), 4),
]
_JP_NUMERIC_RE = re.compile(r"^\s*([0-9]+(?:[\.\uff0e][0-9]+){0,4})\s+")
_JP_ENUM_HEADING_RE = re.compile(r"^\s*[\(\uff08]\s*([0-9]+)\s*[\)\uff09]\s*(.+?)\s*$")
_JP_ALPHA_SECTION_RE = re.compile(r"^\s*([A-Za-z\uff21-\uff3a\uff41-\uff5a])[\.\uff0e\u3002]\s*(.+?)\s*$")
_JP_BRACKET_SECTION_RE = re.compile(r"^\s*\u3010[^\u3011]{1,60}\u3011\s*$")
_JP_NOTE_RE = re.compile(r"^\s*[\(\uff08]?\s*\u6ce8\s*[0-9A-Za-z\uff10-\uff19]*")
_JP_HEADER_FOOTER_TYPES = {"footer", "header", "page-header", "page-footer"}


def _as_text(value: Any, *, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    text = text.strip()
    if not text:
        return None
    if max_len is not None and len(text) > max_len:
        return text[:max_len]
    return text


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _first_nonempty_line(text: str | None) -> str | None:
    if not text:
        return None
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if line:
            return line
    return None


def _is_title_like_type(element_type: str) -> bool:
    return str(element_type or "").strip().lower() in _TITLE_MARKERS


def _has_sentence_punctuation(text: str) -> bool:
    return any(token in text for token in ("\u3002", "\u3001", "\uff0c", ",", ":", "\uff1a", ";", "\uff1b"))


def _jp_looks_like_short_enum_heading(line: str, *, title_like: bool) -> bool:
    match = _JP_ENUM_HEADING_RE.match(line)
    if not match:
        return False
    remainder = match.group(2).strip()
    if not remainder or len(remainder) > 36:
        return False
    if _JP_NOTE_RE.match(line) or _has_sentence_punctuation(remainder):
        return False
    return title_like or len(remainder) <= 18


def _jp_looks_like_alpha_heading(line: str, *, title_like: bool) -> bool:
    match = _JP_ALPHA_SECTION_RE.match(line)
    if not match:
        return False
    remainder = match.group(2).strip()
    if not remainder or len(remainder) > 36:
        return False
    if _has_sentence_punctuation(remainder):
        return False
    return title_like or len(remainder) <= 18


def _jp_infer_section_level(text: str | None, element_type: str) -> int | None:
    line = _first_nonempty_line(text) or ""
    lowered_type = str(element_type or "").strip().lower()
    title_like = _is_title_like_type(element_type)
    if not line:
        return 1 if title_like else None
    if lowered_type in _JP_HEADER_FOOTER_TYPES and not title_like:
        return None
    if _JP_NOTE_RE.match(line):
        return None
    for pattern, level in _JP_CHAPTER_PATTERNS:
        if pattern.match(line):
            return level
    if _JP_BRACKET_SECTION_RE.match(line):
        return 2 if title_like else 1
    numeric_match = _JP_NUMERIC_RE.match(line)
    if numeric_match:
        marker = numeric_match.group(1).replace("\uff0e", ".")
        remainder = line[numeric_match.end():].strip()
        if len(line) <= 80 and (title_like or (remainder and not _has_sentence_punctuation(remainder) and len(remainder) <= 36)):
            return marker.count(".") + 1
        return None
    if _jp_looks_like_alpha_heading(line, title_like=title_like):
        return 2
    if _jp_looks_like_short_enum_heading(line, title_like=title_like):
        return 4
    if title_like and len(line) <= 60 and not _has_sentence_punctuation(line):
        return 1
    return None


def _infer_section_level(text: str | None, element_type: str, *, profile: str = BOOKRAG_SECTION_PROFILE_DEFAULT) -> int | None:
    if profile == "jp":
        return _jp_infer_section_level(text, element_type)
    raise ValueError(f"Unsupported BookRAG section profile: {profile}")


def _classify_block_type(
    element_type: str,
    text: str | None,
    text_as_html: str | None,
    *,
    profile: str = BOOKRAG_SECTION_PROFILE_DEFAULT,
) -> str:
    lowered = str(element_type or "").strip().lower()
    if any(marker in lowered for marker in _TABLE_MARKERS) or text_as_html:
        return "table"
    if any(marker in lowered for marker in _IMAGE_MARKERS):
        return "image"
    first_line = _first_nonempty_line(text) or ""
    if _infer_section_level(first_line, element_type, profile=profile) is not None:
        return "section"
    return "text"


_BOOKRAG_EMBEDDING_TOKEN_LIMIT = 90
_BOOKRAG_EMBEDDING_OVERLAP_TOKENS = 12
_BOOKRAG_TOKEN_UNIT_RE = re.compile(r"\s+|[A-Za-z0-9_]+|[^\s]", re.UNICODE)


def _build_leaf_content(text: str | None, text_as_html: str | None) -> str | None:
    if text and text_as_html:
        return _as_text(f"{text}\n\n{text_as_html}", max_len=32000)
    return _as_text(text or text_as_html, max_len=32000)


def _looks_like_image_caption(text: str | None) -> bool:
    line = _first_nonempty_line(text) or ""
    if not line:
        return False
    if len(line) > 120:
        return False
    if line.startswith(("\u56f3", "Fig", "FIG", "Figure", "\u3010", "[", "(", "\uff08")):
        return True
    if _JP_BRACKET_SECTION_RE.match(line):
        return True
    return not _has_sentence_punctuation(line) or len(line) <= 40


def _build_image_context(
    drafts: list[dict[str, Any]],
    index: int,
) -> tuple[str | None, str | None]:
    current = drafts[index]
    page_number = _as_int(current.get("page_number"))
    parent_element_id = _as_text(current.get("parent_element_id"), max_len=64)
    caption: str | None = _as_text(current.get("content_text"), max_len=_IMAGE_CAPTION_MAX_LEN)
    context_parts: list[str] = []

    def maybe_add_context(text: str | None) -> None:
        normalized = _as_text(text, max_len=1000)
        if normalized and normalized not in context_parts:
            context_parts.append(normalized)

    def can_link(candidate: dict[str, Any]) -> bool:
        if candidate.get("block_type") in {"image", "table"}:
            return False
        candidate_page = _as_int(candidate.get("page_number"))
        if page_number is not None and candidate_page is not None and candidate_page != page_number:
            return False
        candidate_parent = _as_text(candidate.get("parent_element_id"), max_len=64)
        if parent_element_id and candidate_parent and candidate_parent != parent_element_id:
            return False
        return True

    for offset in range(1, _IMAGE_CONTEXT_NEIGHBOR_WINDOW + 1):
        for neighbor_index in (index - offset, index + offset):
            if neighbor_index < 0 or neighbor_index >= len(drafts):
                continue
            neighbor = drafts[neighbor_index]
            if not can_link(neighbor):
                continue
            neighbor_text = _as_text(neighbor.get("content_text"), max_len=1000)
            if not neighbor_text:
                continue
            if caption is None and _looks_like_image_caption(neighbor_text):
                caption = _as_text(neighbor_text, max_len=_IMAGE_CAPTION_MAX_LEN)
                continue
            maybe_add_context(neighbor_text)

    if current.get("section_title"):
        maybe_add_context(_as_text(current.get("section_title"), max_len=1000))
    if page_number is not None:
        maybe_add_context(f"Image on page {page_number}")

    if caption:
        context_parts = [part for part in context_parts if part != caption]
    context = _as_text("\n".join(context_parts), max_len=_IMAGE_CONTEXT_MAX_LEN)
    return caption, context


def _finalize_block_leaf_content(block: dict[str, Any]) -> str | None:
    block_type = str(block.get("block_type") or "").strip().lower()
    content_text = _as_text(block.get("content_text"), max_len=32000)
    table_html = _as_text(block.get("table_html"), max_len=32000)
    if block_type == "table":
        return _build_leaf_content(content_text, table_html)
    if block_type == "image":
        caption = _as_text(block.get("image_caption"), max_len=_IMAGE_CAPTION_MAX_LEN)
        context = _as_text(block.get("image_context"), max_len=32000)
        parts: list[str] = []
        if caption:
            parts.append(f"Image caption: {caption}")
        if context:
            parts.append(f"Context: {context}")
        if content_text and content_text not in {caption, context}:
            parts.append(content_text)
        return _as_text("\n".join(parts), max_len=32000)
    return content_text


def _estimate_token_units(unit: str) -> int:
    if not unit or unit.isspace():
        return 0
    if re.fullmatch(r"[A-Za-z0-9_]+", unit):
        return max(1, (len(unit) + 3) // 4)
    return 1


def _split_long_token_unit(unit: str, *, max_tokens: int) -> list[str]:
    if not unit:
        return []
    if max_tokens <= 0:
        return [unit]
    chunk_chars = max(1, max_tokens * 4)
    return [unit[idx:idx + chunk_chars] for idx in range(0, len(unit), chunk_chars)]


def _split_leaf_content_for_embedding(
    content: str | None,
    *,
    max_tokens: int = _BOOKRAG_EMBEDDING_TOKEN_LIMIT,
    overlap_tokens: int = _BOOKRAG_EMBEDDING_OVERLAP_TOKENS,
) -> list[str]:
    normalized = _as_text(content, max_len=32000)
    if not normalized:
        return []

    units = _BOOKRAG_TOKEN_UNIT_RE.findall(normalized)
    if not units:
        return [normalized]

    segments: list[str] = []
    current_units: list[str] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current_units, current_tokens
        piece = ''.join(current_units).strip()
        if piece:
            segments.append(piece)
        if overlap_tokens > 0 and current_units:
            carry: list[str] = []
            carry_tokens = 0
            for prior in reversed(current_units):
                prior_tokens = _estimate_token_units(prior)
                if carry and carry_tokens + prior_tokens > overlap_tokens:
                    break
                carry.append(prior)
                carry_tokens += prior_tokens
            current_units = list(reversed(carry))
            current_tokens = sum(_estimate_token_units(item) for item in current_units)
        else:
            current_units = []
            current_tokens = 0

    for unit in units:
        unit_tokens = _estimate_token_units(unit)
        if unit_tokens > max_tokens and not unit.isspace():
            if current_units:
                flush()
            for partial in _split_long_token_unit(unit, max_tokens=max_tokens):
                partial_text = partial.strip()
                if partial_text:
                    segments.append(partial_text)
            current_units = []
            current_tokens = 0
            continue
        if current_units and current_tokens + unit_tokens > max_tokens:
            flush()
        current_units.append(unit)
        current_tokens += unit_tokens

    piece = ''.join(current_units).strip()
    if piece:
        segments.append(piece)
    return segments or [normalized]


def build_bookrag_document_row(
    *,
    doc_id: str,
    vector_store_name: str,
    src: Path,
    filetype: str,
    blocks: list[dict[str, Any]],
    languages: list[str],
    created_at: str,
) -> dict[str, Any]:
    page_count = 0
    for block in blocks:
        page_number = _as_int(block.get("page_number")) or 0
        if page_number > page_count:
            page_count = page_number
    return {
        "doc_id": doc_id,
        "vector_store_name": vector_store_name,
        "source_file": str(src),
        "filename": src.name,
        "filetype": filetype,
        "filesize_bytes": int(src.stat().st_size),
        "page_count": page_count,
        "language_hint": ",".join(languages or []),
        "created_at": created_at,
    }


def elements_to_bookrag_blocks(
    *,
    doc_id: str,
    src: Path,
    content_type: str,
    raw_elements: list[dict[str, Any]],
    profile: str = BOOKRAG_SECTION_PROFILE_DEFAULT,
    persist_metadata: bool = False,
) -> list[dict[str, Any]]:
    drafts: list[dict[str, Any]] = []
    for index, element in enumerate(raw_elements, start=1):
        if not isinstance(element, dict):
            continue
        metadata = element.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        raw_text = _as_text(element.get("text"), max_len=32000)
        text_as_html = _as_text(metadata.get("text_as_html"), max_len=32000)
        element_type = _as_text(element.get("type"), max_len=50) or "Text"
        block_type = _classify_block_type(element_type, raw_text, text_as_html, profile=profile)
        image_caption = _as_text(metadata.get("bookrag_image_caption"), max_len=_IMAGE_CAPTION_MAX_LEN)
        image_context = _as_text(metadata.get("bookrag_image_context"), max_len=32000)
        text = image_caption if block_type == "image" and image_caption else raw_text
        if not text and not text_as_html and block_type != "image":
            continue
        section_title = _first_nonempty_line(text)
        level_hint = _infer_section_level(section_title, element_type, profile=profile) if block_type == "section" else None
        drafts.append(
            {
                "block_id": uuid.uuid4().hex,
                "doc_id": doc_id,
                "element_id": _as_text(element.get("element_id") or element.get("id"), max_len=64),
                "parent_element_id": _as_text(metadata.get("parent_id"), max_len=64),
                "source_type": element_type,
                "block_type": block_type,
                "page_number": _as_int(metadata.get("page_number")),
                "ordinal": index,
                "level_hint": level_hint,
                "is_section": 1 if block_type == "section" else 0,
                "section_title": _as_text(section_title, max_len=1000),
                "content_text": text,
                "table_html": text_as_html if block_type == "table" else None,
                "image_caption": image_caption if block_type == "image" else None,
                "image_context": image_context if block_type == "image" else None,
                "metadata_json": _as_text(metadata, max_len=32000) if persist_metadata else None,
            }
        )

    for idx, block in enumerate(drafts):
        if block.get("block_type") != "image":
            continue
        caption, context = _build_image_context(drafts, idx)
        if caption:
            block["image_caption"] = caption
        if context:
            block["image_context"] = context
        if not block.get("content_text"):
            block["content_text"] = _as_text(caption or context, max_len=32000)
    return drafts


def build_bookrag_nodes(document_row: dict[str, Any], blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root_node = {
        "node_id": uuid.uuid4().hex,
        "doc_id": document_row["doc_id"],
        "source_block_id": None,
        "parent_node_id": None,
        "node_type": "document",
        "level": 0,
        "ordinal": 0,
        "title": _as_text(document_row.get("filename"), max_len=1000),
        "content": None,
        "page_start": 1,
        "page_end": document_row.get("page_count") or 1,
        "path": _as_text(document_row.get("filename"), max_len=2000),
        "is_leaf": 0,
    }
    nodes: list[dict[str, Any]] = [root_node]
    section_stack: list[dict[str, Any]] = []
    last_page = 1

    for block in blocks:
        page_number = _as_int(block.get("page_number")) or last_page
        if page_number <= 0:
            page_number = last_page
        last_page = page_number
        root_node["page_end"] = max(_as_int(root_node.get("page_end")) or 1, page_number)
        for open_section in section_stack:
            open_section["page_end"] = max(_as_int(open_section.get("page_end")) or page_number, page_number)

        if int(block.get("is_section") or 0):
            level = _as_int(block.get("level_hint")) or (int(section_stack[-1].get("level") or 0) + 1 if section_stack else 1)
            while section_stack and int(section_stack[-1].get("level") or 0) >= level:
                section_stack.pop()
            parent_node = section_stack[-1] if section_stack else root_node
            title = _as_text(block.get("section_title"), max_len=1000) or f"Section {block.get('ordinal')}"
            parent_path = _as_text(parent_node.get("path"), max_len=2000) or ""
            path_text = title if not parent_path else f"{parent_path} > {title}"
            section_node = {
                "node_id": uuid.uuid4().hex,
                "doc_id": document_row["doc_id"],
                "source_block_id": block.get("block_id"),
                "parent_node_id": parent_node.get("node_id"),
                "node_type": "section",
                "level": level,
                "ordinal": block.get("ordinal"),
                "title": title,
                "content": _as_text(block.get("content_text"), max_len=32000),
                "page_start": page_number,
                "page_end": page_number,
                "path": _as_text(path_text, max_len=2000),
                "is_leaf": 0,
            }
            nodes.append(section_node)
            section_stack.append(section_node)
            continue

        parent_node = section_stack[-1] if section_stack else root_node
        title = None
        if block.get("block_type") == "table":
            title = _as_text(block.get("section_title"), max_len=1000)
        elif block.get("block_type") == "image":
            title = (
                _as_text(block.get("image_caption"), max_len=1000)
                or _as_text(block.get("section_title"), max_len=1000)
                or "Image"
            )
        leaf_segments = _split_leaf_content_for_embedding(_finalize_block_leaf_content(block))
        base_ordinal = _as_int(block.get("ordinal")) or 0
        segment_total = max(1, len(leaf_segments))
        for segment_index, leaf_content in enumerate(leaf_segments, start=1):
            leaf_title = title
            if leaf_title and segment_total > 1:
                leaf_title = _as_text(f"{leaf_title} [{segment_index}/{segment_total}]", max_len=1000)
            nodes.append(
                {
                    "node_id": uuid.uuid4().hex,
                    "doc_id": document_row["doc_id"],
                    "source_block_id": block.get("block_id"),
                    "parent_node_id": parent_node.get("node_id"),
                    "node_type": _as_text(block.get("block_type"), max_len=50) or "text",
                    "level": int(parent_node.get("level") or 0) + 1,
                    "ordinal": base_ordinal if segment_total == 1 else (base_ordinal * 10000) + segment_index,
                    "title": leaf_title,
                    "content": leaf_content,
                    "page_start": page_number,
                    "page_end": page_number,
                    "path": _as_text(parent_node.get("path"), max_len=2000),
                    "is_leaf": 1,
                }
            )

    return nodes
