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

_JP_CHAPTER_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"^\s*第[0-9一-鿿]+章"), 1),
    (re.compile(r"^\s*第[0-9一-鿿]+節"), 2),
    (re.compile(r"^\s*第[0-9一-鿿]+款"), 3),
    (re.compile(r"^\s*第[0-9一-鿿]+目"), 4),
    (re.compile(r"^\s*第[0-9一-鿿]+条"), 4),
]
_JP_NUMERIC_RE = re.compile(r"^\s*([0-9]+(?:[\.．][0-9]+){0,4})\s+")
_JP_ENUM_HEADING_RE = re.compile(r"^\s*[\(（]\s*([0-9]+)\s*[\)）]\s*(.+?)\s*$")
_JP_ALPHA_SECTION_RE = re.compile(r"^\s*([A-Za-zＡ-Ｚａ-ｚ])[\.．。]\s*(.+?)\s*$")
_JP_BRACKET_SECTION_RE = re.compile(r"^\s*【[^】]{1,60}】\s*$")
_JP_NOTE_RE = re.compile(r"^\s*[\(（]?\s*注\s*[0-9A-Za-z０-９]*")
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
    return any(token in text for token in ("。", "、", "，", ",", ":", "：", ";", "；"))


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
        marker = numeric_match.group(1).replace("．", ".")
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


def _build_leaf_content(text: str | None, text_as_html: str | None) -> str | None:
    if text and text_as_html:
        return _as_text(f"{text}\n\n{text_as_html}", max_len=32000)
    return _as_text(text or text_as_html, max_len=32000)


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
    blocks: list[dict[str, Any]] = []
    for index, element in enumerate(raw_elements, start=1):
        if not isinstance(element, dict):
            continue
        metadata = element.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        text = _as_text(element.get("text"), max_len=32000)
        text_as_html = _as_text(metadata.get("text_as_html"), max_len=32000)
        element_type = _as_text(element.get("type"), max_len=50) or "Text"
        block_type = _classify_block_type(element_type, text, text_as_html, profile=profile)
        if not text and not text_as_html and block_type != "image":
            continue
        section_title = _first_nonempty_line(text)
        level_hint = _infer_section_level(section_title, element_type, profile=profile) if block_type == "section" else None
        blocks.append(
            {
                "block_id": uuid.uuid4().hex,
                "doc_id": doc_id,
                "element_id": _as_text(element.get("element_id") or element.get("id"), max_len=64),
                "parent_block_id": _as_text(metadata.get("parent_id"), max_len=64),
                "block_type": block_type,
                "page_number": _as_int(metadata.get("page_number")),
                "ordinal": index,
                "level_hint": level_hint,
                "is_section": 1 if block_type == "section" else 0,
                "section_title": _as_text(section_title, max_len=1000),
                "text": text,
                "text_as_html": text_as_html,
                "orig_elements": _as_text(metadata.get("orig_elements"), max_len=32000) if persist_metadata else None,
                "metadata_json": _as_text(metadata, max_len=32000) if persist_metadata else None,
            }
        )
    return blocks


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
                "content": _as_text(block.get("text"), max_len=32000),
                "page_start": page_number,
                "page_end": page_number,
                "path": _as_text(path_text, max_len=2000),
                "is_leaf": 0,
            }
            nodes.append(section_node)
            section_stack.append(section_node)
            continue

        parent_node = section_stack[-1] if section_stack else root_node
        title = _as_text(block.get("section_title"), max_len=1000) if block.get("block_type") in {"table", "image"} else None
        nodes.append(
            {
                "node_id": uuid.uuid4().hex,
                "doc_id": document_row["doc_id"],
                "source_block_id": block.get("block_id"),
                "parent_node_id": parent_node.get("node_id"),
                "node_type": _as_text(block.get("block_type"), max_len=50) or "text",
                "level": int(parent_node.get("level") or 0) + 1,
                "ordinal": block.get("ordinal"),
                "title": title,
                "content": _build_leaf_content(block.get("text"), block.get("text_as_html")),
                "page_start": page_number,
                "page_end": page_number,
                "path": _as_text(parent_node.get("path"), max_len=2000),
                "is_leaf": 1,
            }
        )

    return nodes
