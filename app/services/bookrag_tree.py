from __future__ import annotations

import json
import re
import hashlib
import uuid
from pathlib import Path
from typing import Any

_TITLE_MARKERS = {"title", "section-header", "sectionheader", "headline"}
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
_JP_NUMERIC_RE = re.compile(r"^\s*([0-9\uff10-\uff19]+(?:[\.\uff0e][0-9\uff10-\uff19]+){0,4})(?:[\.\uff0e\u3002]\s*|\s+)(.+?)\s*$")
_JP_ENUM_HEADING_RE = re.compile(r"^\s*[\(\uff08]\s*([0-9]+)\s*[\)\uff09]\s*(.+?)\s*$")
_JP_ALPHA_SECTION_RE = re.compile(r"^\s*([A-Za-z\uff21-\uff3a\uff41-\uff5a])[\.\uff0e\u3002]\s*(.+?)\s*$")
_JP_BRACKET_SECTION_RE = re.compile(r"^\s*\u3010[^\u3011]{1,60}\u3011\s*$")
_JP_NOTE_RE = re.compile(r"^\s*[\(\uff08]?\s*\u6ce8\s*[0-9A-Za-z\uff10-\uff19]*")
_MAJOR_SECTION_FAMILIES = {"chapter", "numeric"}
_GROUP_SECTION_FAMILIES = {"bracket"}
_ENUM_SECTION_FAMILIES = {"enum"}
_JP_HEADER_FOOTER_TYPES = {"footer", "header", "page-header", "page-footer"}
_TABLE_HTML_RE = re.compile(r"<\s*table\b", re.IGNORECASE)
_HEADING_TAG_RE = re.compile(r"<\s*h([1-6])\b", re.IGNORECASE)
_FULLWIDTH_NUMERIC_TRANS = str.maketrans("\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19\uff0e", "0123456789.")


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


def _normalized_numeric_marker(marker: str | None) -> str:
    return str(marker or "").translate(_FULLWIDTH_NUMERIC_TRANS)


def _is_header_footer_type(element_type: str) -> bool:
    return str(element_type or "").strip().lower() in _JP_HEADER_FOOTER_TYPES


def _extract_heading_html_level(text_as_html: str | None) -> int | None:
    html_text = _as_text(text_as_html, max_len=32000)
    if not html_text:
        return None
    match = _HEADING_TAG_RE.search(html_text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _jp_looks_like_short_enum_heading(line: str, *, title_like: bool) -> bool:
    match = _JP_ENUM_HEADING_RE.match(line)
    if not match:
        return False
    remainder = match.group(2).strip()
    if not remainder or len(remainder) > (120 if title_like else 36):
        return False
    if _JP_NOTE_RE.match(line) or _has_sentence_punctuation(remainder):
        return False
    return title_like or len(remainder) <= 18


def _jp_looks_like_alpha_heading(line: str, *, title_like: bool) -> bool:
    match = _JP_ALPHA_SECTION_RE.match(line)
    if not match:
        return False
    remainder = match.group(2).strip()
    if not remainder or len(remainder) > (120 if title_like else 36):
        return False
    if _has_sentence_punctuation(remainder):
        return False
    return title_like or len(remainder) <= 18


def _jp_section_family(text: str | None, element_type: str, *, heading_level: int | None = None) -> str | None:
    line = _first_nonempty_line(text) or ""
    lowered_type = str(element_type or "").strip().lower()
    title_like = _is_title_like_type(element_type)
    if not line:
        if heading_level is not None or title_like:
            return "generic"
        return None
    if lowered_type in _JP_HEADER_FOOTER_TYPES and not title_like:
        return None
    if _JP_NOTE_RE.match(line):
        return None
    if any(pattern.match(line) for pattern, _ in _JP_CHAPTER_PATTERNS):
        return "chapter"
    if _JP_NUMERIC_RE.match(line):
        return "numeric"
    if _jp_looks_like_short_enum_heading(line, title_like=title_like) or _jp_looks_like_alpha_heading(line, title_like=title_like):
        return "enum"
    if _JP_BRACKET_SECTION_RE.match(line):
        return "bracket"
    if heading_level is not None or title_like:
        return "generic"
    return None


def _jp_pattern_section_level(text: str | None, element_type: str, *, heading_level: int | None = None) -> int | None:
    line = _first_nonempty_line(text) or ""
    family = _jp_section_family(line, element_type, heading_level=heading_level)
    if family == "chapter":
        for pattern, level in _JP_CHAPTER_PATTERNS:
            if pattern.match(line):
                return level
        return 1
    if family == "numeric":
        numeric_match = _JP_NUMERIC_RE.match(line)
        if not numeric_match:
            return 2
        marker = _normalized_numeric_marker(numeric_match.group(1))
        return marker.count(".") + 2
    if family == "enum":
        return 3
    if family == "bracket":
        return 3
    return None


def _jp_infer_section_level(text: str | None, element_type: str, *, heading_level: int | None = None) -> int | None:
    line = _first_nonempty_line(text) or ""
    lowered_type = str(element_type or "").strip().lower()
    title_like = _is_title_like_type(element_type)
    if not line:
        if heading_level is not None:
            return 2 if heading_level >= 3 else 1
        return 1 if title_like else None
    if lowered_type in _JP_HEADER_FOOTER_TYPES and not title_like:
        return None
    if _JP_NOTE_RE.match(line):
        return None
    for pattern, level in _JP_CHAPTER_PATTERNS:
        if pattern.match(line):
            return level
    numeric_match = _JP_NUMERIC_RE.match(line)
    if numeric_match:
        marker = numeric_match.group(1).replace("\uff0e", ".")
        remainder = numeric_match.group(2).strip()
        if len(line) <= 80 and (title_like or (remainder and not _has_sentence_punctuation(remainder) and len(remainder) <= 36)):
            return marker.count(".") + 1
        return None
    if _jp_looks_like_short_enum_heading(line, title_like=title_like):
        return 2
    if _jp_looks_like_alpha_heading(line, title_like=title_like):
        return 2
    if _JP_BRACKET_SECTION_RE.match(line):
        return 2
    if heading_level is not None:
        return 2 if heading_level >= 3 else 1
    if title_like and len(line) <= 60 and not _has_sentence_punctuation(line):
        return 1
    return None


def _infer_section_level(text: str | None, element_type: str, *, profile: str = BOOKRAG_SECTION_PROFILE_DEFAULT, heading_level: int | None = None) -> int | None:
    if profile == "jp":
        return _jp_infer_section_level(text, element_type, heading_level=heading_level)
    raise ValueError(f"Unsupported BookRAG section profile: {profile}")


def _classify_block_type(
    element_type: str,
    text: str | None,
    text_as_html: str | None,
    *,
    profile: str = BOOKRAG_SECTION_PROFILE_DEFAULT,
) -> str:
    lowered = str(element_type or "").strip().lower()
    html_text = _as_text(text_as_html, max_len=32000)
    if any(marker in lowered for marker in _TABLE_MARKERS) or (html_text and _TABLE_HTML_RE.search(html_text)):
        return "table"
    if any(marker in lowered for marker in _IMAGE_MARKERS):
        return "image"
    heading_level = _extract_heading_html_level(html_text)
    if _is_title_like_type(element_type) or heading_level is not None:
        return "section"
    first_line = _first_nonempty_line(text) or ""
    if _infer_section_level(first_line, element_type, profile=profile, heading_level=heading_level) is not None:
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


def _block_element_id(block: dict[str, Any]) -> str | None:
    return _as_text(block.get("element_id"), max_len=64)


def _block_section_title(block: dict[str, Any]) -> str | None:
    return _first_nonempty_line(_as_text(block.get("text"), max_len=1000))


def _block_kind(block: dict[str, Any]) -> str:
    return _classify_block_type(
        _as_text(block.get("type"), max_len=50) or "Text",
        _as_text(block.get("text"), max_len=32000),
        _as_text(block.get("text_as_html"), max_len=32000),
    )


def _block_section_family(block: dict[str, Any]) -> str | None:
    if _block_kind(block) != "section":
        return None
    return _jp_section_family(
        _as_text(block.get("text"), max_len=1000),
        _as_text(block.get("type"), max_len=50) or "Text",
        heading_level=_as_int(block.get("heading_level")),
    )


def _block_section_level(block: dict[str, Any]) -> int | None:
    if _block_kind(block) != "section":
        return None
    heading_level = _as_int(block.get("heading_level"))
    pattern_level = _jp_pattern_section_level(
        _as_text(block.get("text"), max_len=1000),
        _as_text(block.get("type"), max_len=50) or "Text",
        heading_level=heading_level,
    )
    if pattern_level is not None:
        return pattern_level
    if heading_level is not None and heading_level > 0:
        return heading_level
    inferred_level = _infer_section_level(
        _as_text(block.get("text"), max_len=1000),
        _as_text(block.get("type"), max_len=50) or "Text",
        heading_level=heading_level,
    )
    if inferred_level is not None:
        return inferred_level
    category_depth = _as_int(block.get("category_depth"))
    if category_depth is not None and category_depth > 0:
        return category_depth
    return None


def _block_depth_hint(block: dict[str, Any]) -> int | None:
    category_depth = _as_int(block.get("category_depth"))
    if category_depth is None or category_depth < 1:
        return None
    return category_depth


def _stable_fallback_block_id(doc_id: str | None, ordinal: int | None, text: str | None) -> str:
    base = "|".join(
        [
            str(doc_id or ""),
            str(ordinal or 0),
            str(text or ""),
        ]
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:32]


def _build_image_context(
    drafts: list[dict[str, Any]],
    index: int,
) -> tuple[str | None, str | None]:
    current = drafts[index]
    page_number = _as_int(current.get("page_number"))
    parent_id = _as_text(current.get("parent_id"), max_len=64)
    caption: str | None = _as_text(current.get("text"), max_len=_IMAGE_CAPTION_MAX_LEN)
    context_parts: list[str] = []

    def maybe_add_context(text: str | None) -> None:
        normalized = _as_text(text, max_len=1000)
        if normalized and normalized not in context_parts:
            context_parts.append(normalized)

    def can_link(candidate: dict[str, Any]) -> bool:
        if _block_kind(candidate) in {"image", "table"}:
            return False
        candidate_page = _as_int(candidate.get("page_number"))
        if page_number is not None and candidate_page is not None and candidate_page != page_number:
            return False
        candidate_parent = _as_text(candidate.get("parent_id"), max_len=64)
        if parent_id and candidate_parent and candidate_parent != parent_id:
            return False
        return True

    for offset in range(1, _IMAGE_CONTEXT_NEIGHBOR_WINDOW + 1):
        for neighbor_index in (index - offset, index + offset):
            if neighbor_index < 0 or neighbor_index >= len(drafts):
                continue
            neighbor = drafts[neighbor_index]
            if not can_link(neighbor):
                continue
            neighbor_text = _as_text(neighbor.get("text"), max_len=1000)
            if not neighbor_text:
                continue
            if caption is None and _looks_like_image_caption(neighbor_text):
                caption = _as_text(neighbor_text, max_len=_IMAGE_CAPTION_MAX_LEN)
                continue
            maybe_add_context(neighbor_text)

    section_title = _block_section_title(current)
    if section_title:
        maybe_add_context(section_title)
    if page_number is not None:
        maybe_add_context(f"Image on page {page_number}")

    if caption:
        context_parts = [part for part in context_parts if part != caption]
    context = _as_text("\n".join(context_parts), max_len=_IMAGE_CONTEXT_MAX_LEN)
    return caption, context


def _finalize_block_leaf_content(block: dict[str, Any]) -> str | None:
    block_type = _block_kind(block)
    text = _as_text(block.get("text"), max_len=32000)
    text_as_html = _as_text(block.get("text_as_html"), max_len=32000)
    if block_type == "table":
        return _build_leaf_content(text, text_as_html)
    if block_type == "image":
        caption = _as_text(block.get("image_caption"), max_len=_IMAGE_CAPTION_MAX_LEN)
        context = _as_text(block.get("image_context"), max_len=32000)
        parts: list[str] = []
        if caption:
            parts.append(f"Image caption: {caption}")
        if context:
            parts.append(f"Context: {context}")
        if text and text not in {caption, context}:
            parts.append(text)
        return _as_text("\n".join(parts), max_len=32000)
    return text


def _build_leaf_title(title: str | None, *, segment_index: int, segment_total: int, max_len: int = 1000) -> str | None:
    normalized = _as_text(title)
    if not normalized:
        return None
    if segment_total <= 1:
        return _as_text(normalized, max_len=max_len)
    suffix = f" [{segment_index}/{segment_total}]"
    if len(normalized) + len(suffix) <= max_len:
        return f"{normalized}{suffix}"
    keep = max_len - len(suffix)
    if keep <= 0:
        return suffix[-max_len:]
    return f"{normalized[:keep].rstrip()}{suffix}"


def _looks_like_attachment_heading(text: str | None) -> bool:
    line = _first_nonempty_line(text) or ""
    return "\u6dfb\u4ed8\u8cc7\u6599" in line or "\u76ee\u6b21" in line


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
    _ = persist_metadata
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
        heading_level = _extract_heading_html_level(text_as_html)
        if _is_header_footer_type(element_type) and not _is_title_like_type(element_type) and heading_level is None:
            continue
        text = image_caption if block_type == "image" and image_caption else raw_text
        if not text and not text_as_html and block_type != "image":
            continue
        drafts.append(
            {
                "doc_id": doc_id,
                "element_id": _as_text(element.get("element_id") or element.get("id"), max_len=64),
                "parent_id": _as_text(metadata.get("parent_id"), max_len=64),
                "category_depth": _as_int(metadata.get("category_depth")),
                "heading_level": heading_level,
                "page_number": _as_int(metadata.get("page_number")),
                "ordinal": index,
                "text": text,
                "type": element_type,
                "text_as_html": text_as_html if block_type == "table" else None,
                "image_caption": image_caption if block_type == "image" else None,
                "image_context": image_context if block_type == "image" else None,
            }
        )

    for idx, block in enumerate(drafts):
        if _block_kind(block) != "image":
            continue
        caption, context = _build_image_context(drafts, idx)
        if caption:
            block["image_caption"] = caption
        if context:
            block["image_context"] = context
        if not block.get("text"):
            block["text"] = _as_text(caption or context, max_len=32000)
    return drafts


def _stack_last_matching(section_stack: list[dict[str, Any]], families: set[str]) -> dict[str, Any] | None:
    for node in reversed(section_stack):
        if str(node.get("_section_family") or "") in families:
            return node
    return None


def _pop_until_node(section_stack: list[dict[str, Any]], anchor: dict[str, Any] | None) -> None:
    if anchor is None:
        section_stack.clear()
        return
    while section_stack and section_stack[-1].get("node_id") != anchor.get("node_id"):
        section_stack.pop()


def _resolve_parent_by_level(
    root_node: dict[str, Any],
    section_stack: list[dict[str, Any]],
    level: int,
) -> tuple[dict[str, Any], int]:
    while section_stack and int(section_stack[-1].get("level") or 0) >= level:
        section_stack.pop()
    parent_node = section_stack[-1] if section_stack else root_node
    return parent_node, level


def _resolve_section_parent(
    root_node: dict[str, Any],
    section_stack: list[dict[str, Any]],
    *,
    family: str,
    level: int,
    category_depth: int | None = None,
    title: str | None = None,
) -> tuple[dict[str, Any], int]:
    if family in _MAJOR_SECTION_FAMILIES:
        while section_stack and (
            str(section_stack[-1].get("_section_family") or "") not in _MAJOR_SECTION_FAMILIES
            or int(section_stack[-1].get("level") or 0) >= level
        ):
            section_stack.pop()
        parent_node = section_stack[-1] if section_stack else root_node
        return parent_node, level

    if family in _ENUM_SECTION_FAMILIES:
        major_anchor = _stack_last_matching(section_stack, _MAJOR_SECTION_FAMILIES)
        if major_anchor is not None:
            _pop_until_node(section_stack, major_anchor)
            return major_anchor, int(major_anchor.get("level") or 0) + 1

    if family == "generic" and category_depth is not None and category_depth == level:
        return _resolve_parent_by_level(root_node, section_stack, category_depth)

    if family in _GROUP_SECTION_FAMILIES and category_depth is not None and _looks_like_attachment_heading(title):
        return _resolve_parent_by_level(root_node, section_stack, category_depth)

    if family in _GROUP_SECTION_FAMILIES:
        major_anchor = _stack_last_matching(section_stack, _MAJOR_SECTION_FAMILIES)
        if major_anchor is not None:
            _pop_until_node(section_stack, major_anchor)
            return major_anchor, int(major_anchor.get("level") or 0) + 1

    if family == "generic":
        enum_anchor = _stack_last_matching(section_stack, _ENUM_SECTION_FAMILIES)
        if enum_anchor is not None:
            _pop_until_node(section_stack, enum_anchor)
            return enum_anchor, int(enum_anchor.get("level") or 0) + 1

    while section_stack and int(section_stack[-1].get("level") or 0) >= level:
        section_stack.pop()
    parent_node = section_stack[-1] if section_stack else root_node
    return parent_node, level


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

        if _block_kind(block) == "section":
            family = _block_section_family(block) or "generic"
            base_level = _block_section_level(block) or (int(section_stack[-1].get("level") or 0) + 1 if section_stack else 1)
            title = _block_section_title(block) or f"Section {block.get('ordinal')}"
            parent_node, level = _resolve_section_parent(
                root_node,
                section_stack,
                family=family,
                level=base_level,
                category_depth=_block_depth_hint(block),
                title=title,
            )
            parent_path = _as_text(parent_node.get("path"), max_len=2000) or ""
            path_text = title if not parent_path else f"{parent_path} > {title}"
            section_node = {
                "node_id": _block_element_id(block) or _stable_fallback_block_id(document_row.get("doc_id"), _as_int(block.get("ordinal")), block.get("text")),
                "doc_id": document_row["doc_id"],
                "source_block_id": _block_element_id(block),
                "parent_node_id": parent_node.get("node_id"),
                "node_type": "section",
                "level": level,
                "ordinal": block.get("ordinal"),
                "title": title,
                "content": _as_text(block.get("text"), max_len=32000),
                "page_start": page_number,
                "page_end": page_number,
                "path": _as_text(path_text, max_len=2000),
                "is_leaf": 0,
                "_section_family": family,
            }
            nodes.append(section_node)
            section_stack.append(section_node)
            continue

        parent_node = section_stack[-1] if section_stack else root_node
        title = None
        block_kind = _block_kind(block)
        if block_kind == "table":
            title = _block_section_title(block)
        elif block_kind == "image":
            title = (
                _as_text(block.get("image_caption"), max_len=1000)
                or _block_section_title(block)
                or "Image"
            )
        leaf_segments = _split_leaf_content_for_embedding(_finalize_block_leaf_content(block))
        base_ordinal = _as_int(block.get("ordinal")) or 0
        segment_total = max(1, len(leaf_segments))
        for segment_index, leaf_content in enumerate(leaf_segments, start=1):
            leaf_title = _build_leaf_title(title, segment_index=segment_index, segment_total=segment_total)
            nodes.append(
                {
                    "node_id": (_block_element_id(block) or _stable_fallback_block_id(document_row.get("doc_id"), base_ordinal, leaf_content)) if segment_total == 1 else f"{_block_element_id(block) or _stable_fallback_block_id(document_row.get('doc_id'), base_ordinal, leaf_content)}_{segment_index}",
                    "doc_id": document_row["doc_id"],
                    "source_block_id": _block_element_id(block),
                    "parent_node_id": parent_node.get("node_id"),
                    "node_type": block_kind or "text",
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
