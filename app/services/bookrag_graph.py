from __future__ import annotations

import re
import uuid
from typing import Any

from app.services.bookrag_tree import _as_int, _as_text, _has_sentence_punctuation

_JP_ENTITY_TOKEN_RE = re.compile(
    "[A-Za-z0-9\u4E00-\u9FFF\u3041-\u3096\u30A1-\u30FA\u30FC\uFF0F\u30FB\uFF08\uFF09()\-\s]{2,80}?"
    "(?:\u4FDD\u967A|\u88DC\u511F|\u7279\u7D04|\u6761\u9805|\u65B9\u5F0F|\u7269\u4EF6|\u640D\u5BB3|\u4FA1\u984D|\u8A55\u4FA1|\u57FA\u6E96|\u5BFE\u8C61)"
)
_JP_ENTITY_STOPWORDS = {
    "\u4F01\u696D\u8CA1\u7523\u5305\u62EC\u4FDD\u967A\u306E\u6982\u8981",
    "\u4F01\u696D\u8CA1\u7523\u5305\u62EC\u4FDD\u967A\u306E\u7279\u5FB4",
    "\u4FDD\u967A\u306E\u5BFE\u8C61\u306E\u7BC4\u56F2",
    "\u4FDD\u967A\u306E\u5BFE\u8C61\u306E\u4FA1\u984D",
    "\u4FDD\u967A\u91D1\u984D\u306E\u8A2D\u5B9A",
    "\u7279\u7D04\u306E\u4E00\u89A7",
    "\u5168\u7269\u4EF6\u4ED8\u4FDD\u65B9\u5F0F\u306E\u30E1\u30EA\u30C3\u30C8",
    "\u6982\u8981",
    "\u7279\u5FB4",
    "\u5F15\u53D7\u898F\u5B9A",
    "\u30E1\u30EA\u30C3\u30C8",
    "\u30C7\u30E1\u30EA\u30C3\u30C8",
    "\u6CE8\u610F",
    "\u6CE8",
}
_JP_ENTITY_TYPE_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("\u4FDD\u967A", "product"),
    ("\u88DC\u511F", "benefit"),
    ("\u7279\u7D04", "endorsement"),
    ("\u6761\u9805", "clause"),
    ("\u65B9\u5F0F", "method"),
    ("\u7269\u4EF6", "property_type"),
    ("\u640D\u5BB3", "loss_type"),
    ("\u4FA1\u984D", "valuation"),
    ("\u8A55\u4FA1", "valuation"),
    ("\u57FA\u6E96", "valuation"),
    ("\u5BFE\u8C61", "coverage"),
)


def _normalize_entity_name(text: str | None) -> str | None:
    if not text:
        return None
    value = str(text).strip()
    value = re.sub("^\s*[0-9\uFF10-\uFF19]+(?:[\.\uFF0E][0-9\uFF10-\uFF19]+)*\s*", "", value)
    value = re.sub("^\s*[\(\uFF08]\s*[0-9\uFF10-\uFF19A-Za-z\uFF21-\uFF3A\uFF41-\uFF5A]+\s*[\)\uFF09]\s*", "", value)
    value = re.sub("^\s*[A-Za-z\uFF21-\uFF3A\uFF41-\uFF5A][\.\uFF0E\u3002]\s*", "", value)
    value = value.strip(" []\u3010\u3011<>\uFF1C\uFF1E()\uFF08\uFF09")
    value = re.sub("\s+", " ", value).strip()
    return value or None


def _classify_entity_type(name: str) -> str:
    for suffix, entity_type in _JP_ENTITY_TYPE_SUFFIXES:
        if name.endswith(suffix):
            return entity_type
    return "section_topic"


def _extract_section_topic_entity(title: str | None) -> str | None:
    raw = str(title or "").strip()
    if not raw:
        return None
    if raw.startswith(("\u7B2C", "\u3010", "\uFF08", "(", "\u6CE8", "\uFF1C", "<")):
        return None
    cleaned = _normalize_entity_name(raw)
    if not cleaned or len(cleaned) < 2 or len(cleaned) > 30:
        return None
    if cleaned in _JP_ENTITY_STOPWORDS:
        return None
    if cleaned[0].isdigit() or _has_sentence_punctuation(cleaned):
        return None
    if not cleaned.endswith(tuple(suffix for suffix, _ in _JP_ENTITY_TYPE_SUFFIXES)):
        return None
    return cleaned


def _extract_jp_entities(text: str | None) -> list[tuple[str, str]]:
    if not text:
        return []
    matches: list[tuple[str, str]] = []
    seen: set[str] = set()
    scrubbed = re.sub(r"<[^>]+>", " ", str(text))
    for raw_match in _JP_ENTITY_TOKEN_RE.finditer(scrubbed):
        candidate = _normalize_entity_name(raw_match.group(0))
        if not candidate or len(candidate) < 2 or len(candidate) > 40:
            continue
        if candidate in _JP_ENTITY_STOPWORDS or candidate[0].isdigit():
            continue
        if candidate.count(" ") > 3:
            continue
        canonical = candidate.replace(" ", "")
        if canonical in seen:
            continue
        seen.add(canonical)
        matches.append((candidate, _classify_entity_type(candidate)))
    return matches


def _nearest_section_node(node: dict[str, Any], node_map: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    current = node
    while current is not None:
        if current.get("node_type") == "section":
            return current
        parent_id = current.get("parent_node_id")
        if not parent_id:
            return None
        current = node_map.get(parent_id)
    return None


def build_bookrag_entities(
    document_row: dict[str, Any],
    nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    doc_id = _as_text(document_row.get("doc_id"), max_len=64)
    if not doc_id:
        return [], []

    node_map = {str(node.get("node_id")): node for node in nodes if node.get("node_id")}
    entity_index: dict[str, dict[str, Any]] = {}
    entity_links: list[dict[str, Any]] = []
    seen_links: set[tuple[str, str]] = set()

    def register_entity(name: str, entity_type: str, node: dict[str, Any], mention_text: str | None) -> None:
        canonical_name = _normalize_entity_name(name)
        if not canonical_name:
            return
        canonical_key = canonical_name.replace(" ", "")
        entity = entity_index.get(canonical_key)
        if entity is None:
            entity = {
                "entity_id": uuid.uuid4().hex,
                "doc_id": doc_id,
                "entity_name": _as_text(canonical_name, max_len=500),
                "canonical_name": _as_text(canonical_key, max_len=500),
                "entity_type": _as_text(entity_type, max_len=50) or "section_topic",
                "mention_count": 0,
            }
            entity_index[canonical_key] = entity

        node_id = _as_text(node.get("node_id"), max_len=64)
        if not node_id:
            return
        link_key = (entity["entity_id"], node_id)
        if link_key in seen_links:
            return
        seen_links.add(link_key)
        entity["mention_count"] = int(entity.get("mention_count") or 0) + 1

        section_node = _nearest_section_node(node, node_map)
        entity_links.append(
            {
                "link_id": uuid.uuid4().hex,
                "entity_id": entity["entity_id"],
                "doc_id": doc_id,
                "node_id": node_id,
                "section_node_id": _as_text(section_node.get("node_id"), max_len=64) if section_node else None,
                "page_start": _as_int(node.get("page_start")),
                "page_end": _as_int(node.get("page_end")),
                "mention_text": _as_text(mention_text, max_len=1000) or _as_text(canonical_name, max_len=1000),
            }
        )

    for node in nodes:
        node_type = str(node.get("node_type") or "").strip().lower()
        title = _as_text(node.get("title"), max_len=1000)
        content = _as_text(node.get("content"), max_len=32000)

        if node_type == "section":
            section_entity = _extract_section_topic_entity(title)
            if section_entity:
                register_entity(section_entity, _classify_entity_type(section_entity), node, title)

        for entity_name, entity_type in _extract_jp_entities(title):
            register_entity(entity_name, entity_type, node, title)
        for entity_name, entity_type in _extract_jp_entities(content):
            register_entity(entity_name, entity_type, node, content)

    entities = sorted(entity_index.values(), key=lambda row: (str(row.get("entity_type") or ""), str(row.get("canonical_name") or "")))
    entity_links.sort(key=lambda row: (str(row.get("entity_id") or ""), _as_int(row.get("page_start")) or 0, str(row.get("node_id") or "")))
    return entities, entity_links
