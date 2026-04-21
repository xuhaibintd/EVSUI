from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

BOOKRAG_SECTION_RULES_PATH = Path(__file__).resolve().parent.parent / "config" / "bookrag_section_rules.json"

DEFAULT_BOOKRAG_SECTION_RULES: dict[str, Any] = {
    "version": 1,
    "updated_at": "",
    "profiles": {
        "jp": {
            "chapter_patterns": [
                {
                    "name": "chapter",
                    "pattern": r"^\s*\u7b2c[0-9\u4e00-\u9fff]+\u7ae0",
                    "level": 1,
                    "family": "chapter",
                    "enabled": True,
                    "priority": 10,
                },
                {
                    "name": "section",
                    "pattern": r"^\s*\u7b2c[0-9\u4e00-\u9fff]+\u7bc0",
                    "level": 2,
                    "family": "chapter",
                    "enabled": True,
                    "priority": 20,
                },
                {
                    "name": "clause",
                    "pattern": r"^\s*\u7b2c[0-9\u4e00-\u9fff]+\u6b3e",
                    "level": 3,
                    "family": "chapter",
                    "enabled": True,
                    "priority": 30,
                },
                {
                    "name": "item",
                    "pattern": r"^\s*\u7b2c[0-9\u4e00-\u9fff]+\u76ee",
                    "level": 4,
                    "family": "chapter",
                    "enabled": True,
                    "priority": 40,
                },
                {
                    "name": "article",
                    "pattern": r"^\s*\u7b2c[0-9\u4e00-\u9fff]+\u6761",
                    "level": 4,
                    "family": "chapter",
                    "enabled": True,
                    "priority": 50,
                },
            ],
            "numeric_pattern": r"^\s*([0-9\uff10-\uff19]+(?:[\.\uff0e][0-9\uff10-\uff19]+){0,4})(?:[\.\uff0e\u3002]\s*|\s+)(.+?)\s*$",
            "enum_heading_pattern": r"^\s*[\(\uff08]\s*([0-9]+)\s*[\)\uff09]\s*(.+?)\s*$",
            "alpha_section_pattern": r"^\s*([A-Za-z\uff21-\uff3a\uff41-\uff5a])[\.\uff0e\u3002]\s*(.+?)\s*$",
            "bracket_section_pattern": r"^\s*\u3010[^\u3011]{1,60}\u3011\s*$",
            "note_pattern": r"^\s*[\(\uff08]?\s*\u6ce8\s*[0-9A-Za-z\uff10-\uff19]*",
            "table_html_pattern": r"<\s*table\b",
            "heading_tag_pattern": r"<\s*h([1-6])\b",
            "header_footer_types": ["footer", "header", "page-header", "page-footer"],
            "major_section_families": ["chapter", "numeric"],
            "group_section_families": ["bracket"],
            "enum_section_families": ["enum"],
            "fullwidth_numeric_source": "\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19\uff0e",
            "fullwidth_numeric_target": "0123456789.",
        }
    },
}

_COMPILED_CACHE: dict[str, Any] = {}
_COMPILED_CACHE_MTIME_NS: int | None = None


def _deep_copy_default_rules() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_BOOKRAG_SECTION_RULES)


def _string_list(values: Any) -> list[str]:
    if isinstance(values, list):
        result = []
        for item in values:
            text = str(item or "").strip()
            if text:
                result.append(text)
        return result
    if isinstance(values, str):
        return [item.strip() for item in values.split(",") if item.strip()]
    return []


def _normalize_chapter_patterns(values: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(values, list):
        return result
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            continue
        pattern = str(item.get("pattern") or "").strip()
        if not pattern:
            continue
        result.append(
            {
                "name": str(item.get("name") or f"rule_{index + 1}").strip() or f"rule_{index + 1}",
                "pattern": pattern,
                "level": max(1, int(item.get("level") or 1)),
                "family": str(item.get("family") or "chapter").strip() or "chapter",
                "enabled": bool(item.get("enabled", True)),
                "priority": int(item.get("priority") or ((index + 1) * 10)),
            }
        )
    result.sort(key=lambda item: (int(item.get("priority") or 0), str(item.get("name") or "")))
    return result


def _normalize_rules_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    default_payload = _deep_copy_default_rules()
    incoming = payload if isinstance(payload, dict) else {}
    incoming_profiles = incoming.get("profiles") if isinstance(incoming.get("profiles"), dict) else {}
    normalized = {
        "version": int(incoming.get("version") or default_payload["version"]),
        "updated_at": str(incoming.get("updated_at") or default_payload["updated_at"]),
        "profiles": {},
    }

    for profile_name, default_profile in default_payload["profiles"].items():
        incoming_profile = incoming_profiles.get(profile_name) if isinstance(incoming_profiles.get(profile_name), dict) else {}
        normalized["profiles"][profile_name] = {
            "chapter_patterns": _normalize_chapter_patterns(incoming_profile.get("chapter_patterns", default_profile["chapter_patterns"])),
            "numeric_pattern": str(incoming_profile.get("numeric_pattern") or default_profile["numeric_pattern"]).strip(),
            "enum_heading_pattern": str(incoming_profile.get("enum_heading_pattern") or default_profile["enum_heading_pattern"]).strip(),
            "alpha_section_pattern": str(incoming_profile.get("alpha_section_pattern") or default_profile["alpha_section_pattern"]).strip(),
            "bracket_section_pattern": str(incoming_profile.get("bracket_section_pattern") or default_profile["bracket_section_pattern"]).strip(),
            "note_pattern": str(incoming_profile.get("note_pattern") or default_profile["note_pattern"]).strip(),
            "table_html_pattern": str(incoming_profile.get("table_html_pattern") or default_profile["table_html_pattern"]).strip(),
            "heading_tag_pattern": str(incoming_profile.get("heading_tag_pattern") or default_profile["heading_tag_pattern"]).strip(),
            "header_footer_types": _string_list(incoming_profile.get("header_footer_types", default_profile["header_footer_types"])),
            "major_section_families": _string_list(incoming_profile.get("major_section_families", default_profile["major_section_families"])),
            "group_section_families": _string_list(incoming_profile.get("group_section_families", default_profile["group_section_families"])),
            "enum_section_families": _string_list(incoming_profile.get("enum_section_families", default_profile["enum_section_families"])),
            "fullwidth_numeric_source": str(incoming_profile.get("fullwidth_numeric_source") or default_profile["fullwidth_numeric_source"]),
            "fullwidth_numeric_target": str(incoming_profile.get("fullwidth_numeric_target") or default_profile["fullwidth_numeric_target"]),
        }
    return normalized


def ensure_bookrag_section_rules_file() -> Path:
    path = BOOKRAG_SECTION_RULES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        payload = _deep_copy_default_rules()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_bookrag_section_rules() -> dict[str, Any]:
    path = ensure_bookrag_section_rules_file()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = _deep_copy_default_rules()
    normalized = _normalize_rules_payload(payload)
    if normalized != payload:
        path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return normalized


def compile_bookrag_section_rules(rules_payload: dict[str, Any] | None, *, profile: str = "jp") -> dict[str, Any]:
    payload = _normalize_rules_payload(rules_payload)
    profile_rules = payload["profiles"].get(profile)
    if not isinstance(profile_rules, dict):
        raise ValueError(f"Unsupported BookRAG rules profile: {profile}")

    compiled_patterns: list[dict[str, Any]] = []
    for index, item in enumerate(profile_rules.get("chapter_patterns", []), start=1):
        pattern_text = str(item.get("pattern") or "").strip()
        try:
            compiled = re.compile(pattern_text)
        except re.error as ex:
            raise ValueError(f"Invalid chapter pattern #{index} ({item.get('name') or 'unnamed'}): {ex}") from ex
        compiled_patterns.append(
            {
                "name": str(item.get("name") or f"rule_{index}"),
                "pattern": compiled,
                "pattern_text": pattern_text,
                "level": max(1, int(item.get("level") or 1)),
                "family": str(item.get("family") or "chapter").strip() or "chapter",
                "enabled": bool(item.get("enabled", True)),
                "priority": int(item.get("priority") or (index * 10)),
            }
        )
    compiled_patterns.sort(key=lambda item: (int(item.get("priority") or 0), str(item.get("name") or "")))

    def compile_single(field_name: str, flags: int = 0) -> re.Pattern[str]:
        text = str(profile_rules.get(field_name) or "").strip()
        try:
            return re.compile(text, flags)
        except re.error as ex:
            raise ValueError(f"Invalid {field_name}: {ex}") from ex

    source = str(profile_rules.get("fullwidth_numeric_source") or "")
    target = str(profile_rules.get("fullwidth_numeric_target") or "")
    if len(source) != len(target):
        raise ValueError("fullwidth numeric source/target must have the same length.")

    return {
        "profile": profile,
        "chapter_patterns": compiled_patterns,
        "numeric_re": compile_single("numeric_pattern"),
        "enum_heading_re": compile_single("enum_heading_pattern"),
        "alpha_section_re": compile_single("alpha_section_pattern"),
        "bracket_section_re": compile_single("bracket_section_pattern"),
        "note_re": compile_single("note_pattern"),
        "table_html_re": compile_single("table_html_pattern", re.IGNORECASE),
        "heading_tag_re": compile_single("heading_tag_pattern", re.IGNORECASE),
        "header_footer_types": {item.lower() for item in _string_list(profile_rules.get("header_footer_types"))},
        "major_section_families": set(_string_list(profile_rules.get("major_section_families"))),
        "group_section_families": set(_string_list(profile_rules.get("group_section_families"))),
        "enum_section_families": set(_string_list(profile_rules.get("enum_section_families"))),
        "fullwidth_numeric_trans": str.maketrans(source, target),
    }


def get_compiled_bookrag_section_rules(*, profile: str = "jp") -> dict[str, Any]:
    global _COMPILED_CACHE_MTIME_NS
    path = ensure_bookrag_section_rules_file()
    current_mtime_ns = path.stat().st_mtime_ns
    cache_key = profile
    if _COMPILED_CACHE_MTIME_NS == current_mtime_ns and cache_key in _COMPILED_CACHE:
        return _COMPILED_CACHE[cache_key]
    payload = load_bookrag_section_rules()
    compiled = compile_bookrag_section_rules(payload, profile=profile)
    _COMPILED_CACHE.clear()
    _COMPILED_CACHE[cache_key] = compiled
    _COMPILED_CACHE_MTIME_NS = current_mtime_ns
    return compiled


def save_bookrag_section_rules(rules_payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_rules_payload(rules_payload)
    compile_bookrag_section_rules(normalized, profile="jp")
    normalized["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = ensure_bookrag_section_rules_file()
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _COMPILED_CACHE.clear()
    return normalized
