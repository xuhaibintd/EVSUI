from __future__ import annotations

import re
import uuid
from typing import Any

from app.services.bookrag_tree import _as_int, _as_text, _has_sentence_punctuation

_RELATION_DATE_RE = re.compile(
    r"(?:^|\b)(?:[12][0-9]{3}[-/][01]?[0-9][-/][0-3]?[0-9]"
    r"|[12][0-9]{3}\u5e74[0-9]{1,2}\u6708(?:[0-9]{1,2}\u65e5)?"
    r"|[12][0-9]{3}\u5e74\u5ea6"
    r"|[12][0-9]{3}\u5e74[0-9]{1,2}\u6708\u671f(?:\u7b2c[0-9]+\u56db\u534a\u671f)?"
    r"|\u7b2c[0-9]+\u56db\u534a\u671f(?:\u9023\u7d50\u7d2f\u8a08\u671f\u9593)?)"
)
_RELATION_MONEY_RE = re.compile(
    r"(?:\u00a5|\uffe5|\$|[0-9][0-9,]*(?:\.[0-9]+)?\s*(?:\u5186|\u5343\u5186|\u767e\u4e07\u5186|\u5104\u5186|million|billion))",
    re.IGNORECASE,
)


def _strip_balanced_outer_wrappers(value: str) -> str:
    pairs = (("\u3010", "\u3011"), ("\uff1c", "\uff1e"), ("<", ">"), ("[", "]"), ("(", ")"), ("\uff08", "\uff09"))
    updated = value.strip()
    changed = True
    while changed and updated:
        changed = False
        for left, right in pairs:
            if updated.startswith(left) and updated.endswith(right):
                inner = updated[len(left):-len(right)].strip()
                if inner:
                    updated = inner
                    changed = True
                    break
    return updated


def _normalize_entity_name(text: str | None) -> str | None:
    if not text:
        return None
    value = str(text).strip()
    value = re.sub(r"^\s*[0-9\uff10-\uff19]+(?:[\.\uff0e][0-9\uff10-\uff19]+)*(?:[\.\uff0e\u3002]\s*|\s+)(?=\D)", "", value)
    value = re.sub(r"^\s*[\(\uff08]\s*[0-9\uff10-\uff19A-Za-z\uff21-\uff3a\uff41-\uff5a]+\s*[\)\uff09]\s*", "", value)
    value = re.sub(r"^\s*[A-Za-z\uff21-\uff3a\uff41-\uff5a][\.\uff0e\u3002]\s*", "", value)
    value = _strip_balanced_outer_wrappers(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


_JP_ENTITY_TOKEN_RE = re.compile(
    r"[A-Za-z0-9\u4e00-\u9fff\u3041-\u3096\u30a1-\u30fa\u30fc\uff0f\u30fb\uff08\uff09()\-\s]{2,80}?"
    r"(?:\u4fdd\u967a|\u88dc\u511f|\u7279\u7d04|\u6761\u9805|\u65b9\u5f0f|\u7269\u4ef6|\u640d\u5bb3|\u4fa1\u984d|\u8a55\u4fa1|\u57fa\u6e96|\u5bfe\u8c61)"
)
_JP_ENTITY_STOPWORDS = {
    "\u4f01\u696d\u8ca1\u7523\u5305\u62ec\u4fdd\u967a\u306e\u6982\u8981",
    "\u4f01\u696d\u8ca1\u7523\u5305\u62ec\u4fdd\u967a\u306e\u7279\u5fb4",
    "\u4fdd\u967a\u306e\u5bfe\u8c61\u306e\u7bc4\u56f2",
    "\u4fdd\u967a\u306e\u5bfe\u8c61\u306e\u4fa1\u984d",
    "\u4fdd\u967a\u91d1\u984d\u306e\u8a2d\u5b9a",
    "\u7279\u7d04\u306e\u4e00\u89a7",
    "\u5168\u7269\u4ef6\u4ed8\u4fdd\u65b9\u5f0f\u306e\u30e1\u30ea\u30c3\u30c8",
    "\u6982\u8981",
    "\u7279\u5fb4",
    "\u5f15\u53d7\u898f\u5b9a",
    "\u30e1\u30ea\u30c3\u30c8",
    "\u30c7\u30e1\u30ea\u30c3\u30c8",
    "\u6ce8\u610f",
    "\u6ce8",
}
_JP_ENTITY_TYPE_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("\u4fdd\u967a", "product"),
    ("\u88dc\u511f", "benefit"),
    ("\u7279\u7d04", "endorsement"),
    ("\u6761\u9805", "clause"),
    ("\u65b9\u5f0f", "method"),
    ("\u7269\u4ef6", "property_type"),
    ("\u640d\u5bb3", "loss_type"),
    ("\u4fa1\u984d", "valuation"),
    ("\u8a55\u4fa1", "valuation"),
    ("\u57fa\u6e96", "valuation"),
    ("\u5bfe\u8c61", "coverage"),
)
_PLACEHOLDER_ENTITY_LABELS = {
    "CARDINAL",
    "DATE",
    "DOCUMENT",
    "EVENT",
    "FACILITY",
    "GPE",
    "LANGUAGE",
    "LAW",
    "LOCATION",
    "MONEY",
    "NORP",
    "NUMBER",
    "ORDINAL",
    "ORGANIZATION",
    "PERCENT",
    "PERSON",
    "PRODUCT",
    "QUANTITY",
    "ROLE",
    "TIME",
    "UNKNOWN",
    "WORK_OF_ART",
}


def _classify_entity_type(name: str) -> str:
    for suffix, entity_type in _JP_ENTITY_TYPE_SUFFIXES:
        if name.endswith(suffix):
            return entity_type
    return "section_topic"


def _is_placeholder_entity_label(text: str | None, entity_type: str | None = None) -> bool:
    normalized = _as_text(text, max_len=1000)
    if not normalized:
        return False
    label = normalized.strip().upper()
    if label in _PLACEHOLDER_ENTITY_LABELS:
        return True
    normalized_type = _as_text(entity_type, max_len=100)
    return bool(normalized_type and label == normalized_type.strip().upper())


def _extract_section_topic_entity(title: str | None) -> str | None:
    raw = str(title or "").strip()
    if not raw:
        return None
    if raw.startswith(("第", "【", "（", "(", "注", "＜", "<")):
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


def _node_source_element_id(node: dict[str, Any]) -> str | None:
    return _as_text(node.get("source_element_id") or node.get("source_block_id"), max_len=64)


def _entities_payload(raw_element: dict[str, Any]) -> dict[str, Any]:
    metadata = raw_element.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    entities = metadata.get("entities")
    return entities if isinstance(entities, dict) else {}


def _entity_items_from_raw_element(raw_element: dict[str, Any]) -> list[dict[str, Any]]:
    items = _entities_payload(raw_element).get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _entity_relationships_from_raw_element(raw_element: dict[str, Any]) -> list[dict[str, Any]]:
    relationships = _entities_payload(raw_element).get("relationships")
    if not isinstance(relationships, list):
        return []
    return [item for item in relationships if isinstance(item, dict)]


def _entity_lookup_keys(text: str | None) -> list[str]:
    raw_text = _as_text(text, max_len=1000)
    if not raw_text:
        return []
    keys: list[str] = []
    for candidate in (raw_text, _normalize_entity_name(raw_text)):
        normalized = _as_text(candidate, max_len=1000)
        if not normalized:
            continue
        compact = normalized.replace(" ", "")
        for key in (normalized, compact):
            if key and key not in keys:
                keys.append(key)
    return keys


def _guess_relation_entity_type(text: str | None) -> str:
    normalized = _as_text(text, max_len=1000)
    if not normalized:
        return "UNKNOWN"
    if _RELATION_DATE_RE.search(normalized):
        return "DATE"
    if _RELATION_MONEY_RE.search(normalized):
        return "MONEY"
    return "UNKNOWN"


def build_bookrag_entities(
    document_row: dict[str, Any],
    raw_elements: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    doc_id = _as_text(document_row.get("doc_id"), max_len=64)
    if not doc_id:
        return [], [], []

    node_map = {str(node.get("node_id")): node for node in nodes if node.get("node_id")}
    nodes_by_source_element: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        source_element_id = _node_source_element_id(node)
        if not source_element_id:
            continue
        nodes_by_source_element.setdefault(source_element_id, []).append(node)
    for source_element_id in nodes_by_source_element:
        nodes_by_source_element[source_element_id].sort(
            key=lambda row: (_as_int(row.get("ordinal")) or 0, str(row.get("node_id") or ""))
        )

    entity_index: dict[tuple[str, str], dict[str, Any]] = {}
    entity_node_ids: dict[str, set[str]] = {}
    entity_ids_by_key: dict[str, set[str]] = {}
    entity_links: list[dict[str, Any]] = []
    entity_relations: list[dict[str, Any]] = []
    seen_links: set[tuple[str, str, int]] = set()
    seen_relations: set[tuple[int, str, str, str]] = set()

    def register_entity_aliases(entity: dict[str, Any], *names: str | None) -> None:
        entity_id = _as_text(entity.get("entity_id"), max_len=64)
        if not entity_id:
            return
        for name in names:
            for key in _entity_lookup_keys(name):
                entity_ids_by_key.setdefault(key, set()).add(entity_id)

    def resolve_entity_id(name: str | None) -> str | None:
        raw_text = _as_text(name, max_len=1000)
        if not raw_text:
            return None
        exact_candidates: set[str] = set()
        for key in (raw_text, raw_text.replace(" ", "")):
            exact_candidates.update(entity_ids_by_key.get(key, set()))
        if len(exact_candidates) == 1:
            return next(iter(exact_candidates))
        matched_ids: set[str] = set(exact_candidates)
        normalized = _normalize_entity_name(raw_text)
        for key in (normalized, normalized.replace(" ", "") if normalized else None):
            if key:
                matched_ids.update(entity_ids_by_key.get(key, set()))
        if len(matched_ids) == 1:
            return next(iter(matched_ids))
        return None

    def get_or_create_entity(name: str, entity_type: str) -> dict[str, Any] | None:
        normalized_input = _as_text(name, max_len=1000)
        if _is_placeholder_entity_label(normalized_input, entity_type):
            return None
        if entity_type in {"DATE", "MONEY"}:
            canonical_name = normalized_input
        else:
            canonical_name = _normalize_entity_name(normalized_input)
        if not canonical_name:
            return None
        canonical_key = canonical_name.replace(" ", "")
        key = (canonical_key, entity_type or "UNKNOWN")
        entity = entity_index.get(key)
        if entity is None:
            entity = {
                "entity_id": uuid.uuid4().hex,
                "doc_id": doc_id,
                "canonical_name": _as_text(canonical_key, max_len=1000),
                "display_name": _as_text(canonical_name, max_len=1000),
                "entity_type": _as_text(entity_type, max_len=50) or "UNKNOWN",
                "mention_count": 0,
                "node_count": 0,
            }
            entity_index[key] = entity
            entity_node_ids[entity["entity_id"]] = set()
        register_entity_aliases(entity, name, entity.get("canonical_name"), entity.get("display_name"))
        return entity

    for ordinal_raw, raw_element in enumerate(raw_elements, start=1):
        source_element_id = _as_text(raw_element.get("element_id") or raw_element.get("id"), max_len=64)
        metadata = raw_element.get("metadata") if isinstance(raw_element.get("metadata"), dict) else {}
        page_number = _as_int(metadata.get("page_number"))
        linked_nodes = list(nodes_by_source_element.get(source_element_id or "") or [])
        for item in _entity_items_from_raw_element(raw_element):
            entity_name = _as_text(item.get("entity"), max_len=1000)
            entity_type = _as_text(item.get("type"), max_len=50) or "UNKNOWN"
            if not entity_name:
                continue
            entity = get_or_create_entity(entity_name, entity_type)
            if entity is None:
                continue
            entity["mention_count"] = int(entity.get("mention_count") or 0) + 1

            for node in linked_nodes:
                node_id = _as_text(node.get("node_id"), max_len=64)
                if not node_id:
                    continue
                link_key = (entity["entity_id"], node_id, ordinal_raw)
                if link_key in seen_links:
                    continue
                seen_links.add(link_key)
                entity_node_ids[entity["entity_id"]].add(node_id)
                section_node = _nearest_section_node(node, node_map)
                entity_links.append(
                    {
                        "link_id": uuid.uuid4().hex,
                        "entity_id": entity["entity_id"],
                        "doc_id": doc_id,
                        "node_id": node_id,
                        "section_node_id": _as_text(section_node.get("node_id"), max_len=64) if section_node else None,
                        "source_field": "metadata.entities.items",
                        "mention_text": entity_name,
                        "page_start": _as_int(node.get("page_start")) or page_number,
                        "page_end": _as_int(node.get("page_end")) or page_number,
                        "ordinal": ordinal_raw,
                        "section_path": _as_text(section_node.get("path"), max_len=2000) if section_node else None,
                    }
                )

    def resolve_or_create_relation_entity(name: str | None) -> str | None:
        resolved = resolve_entity_id(name)
        if resolved:
            return resolved
        normalized_name = _as_text(name, max_len=1000)
        if not normalized_name:
            return None
        if _is_placeholder_entity_label(normalized_name):
            return None
        entity = get_or_create_entity(normalized_name, _guess_relation_entity_type(normalized_name))
        if entity is None:
            return None
        return _as_text(entity.get("entity_id"), max_len=64)

    for ordinal_raw, raw_element in enumerate(raw_elements, start=1):
        source_element_id = _as_text(raw_element.get("element_id") or raw_element.get("id"), max_len=64)
        metadata = raw_element.get("metadata") if isinstance(raw_element.get("metadata"), dict) else {}
        page_number = _as_int(metadata.get("page_number"))
        linked_nodes = list(nodes_by_source_element.get(source_element_id or "") or [])
        primary_node = linked_nodes[0] if linked_nodes else None
        section_node = _nearest_section_node(primary_node, node_map) if primary_node else None
        source_node_id = _as_text(primary_node.get("node_id"), max_len=64) if primary_node else None
        page_start = _as_int(primary_node.get("page_start")) if primary_node else page_number
        page_end = _as_int(primary_node.get("page_end")) if primary_node else page_number
        section_node_id = _as_text(section_node.get("node_id"), max_len=64) if section_node else None
        section_path = _as_text(section_node.get("path"), max_len=2000) if section_node else None

        for relationship_row in _entity_relationships_from_raw_element(raw_element):
            from_entity_text = _as_text(relationship_row.get("from"), max_len=1000)
            relationship = _as_text(relationship_row.get("relationship"), max_len=100)
            to_entity_text = _as_text(relationship_row.get("to"), max_len=1000)
            if not from_entity_text or not relationship or not to_entity_text:
                continue
            relation_key = (ordinal_raw, from_entity_text, relationship, to_entity_text)
            if relation_key in seen_relations:
                continue
            seen_relations.add(relation_key)
            entity_relations.append(
                {
                    "relation_id": uuid.uuid4().hex,
                    "doc_id": doc_id,
                    "source_element_id": source_element_id,
                    "source_node_id": source_node_id,
                    "section_node_id": section_node_id,
                    "from_entity_id": resolve_or_create_relation_entity(from_entity_text),
                    "from_entity_text": from_entity_text,
                    "relationship": relationship,
                    "to_entity_id": resolve_or_create_relation_entity(to_entity_text),
                    "to_entity_text": to_entity_text,
                    "page_start": page_start,
                    "page_end": page_end,
                    "ordinal": ordinal_raw,
                    "section_path": section_path,
                }
            )

    for entity in entity_index.values():
        entity["node_count"] = len(entity_node_ids.get(entity["entity_id"], set()))

    entities = sorted(
        entity_index.values(),
        key=lambda row: (str(row.get("entity_type") or ""), str(row.get("canonical_name") or "")),
    )
    entity_links.sort(
        key=lambda row: (str(row.get("entity_id") or ""), _as_int(row.get("ordinal")) or 0, str(row.get("node_id") or ""))
    )
    entity_relations.sort(
        key=lambda row: (_as_int(row.get("ordinal")) or 0, str(row.get("relationship") or ""), str(row.get("from_entity_text") or ""), str(row.get("to_entity_text") or ""))
    )
    return entities, entity_links, entity_relations
