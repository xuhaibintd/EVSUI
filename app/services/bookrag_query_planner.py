from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable


_FULL_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<!\d)(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?"),
    re.compile(r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)"),
    re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)"),
)
_MONTH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<!\d)(20\d{2})\s*年\s*(\d{1,2})\s*月(?!\s*\d)"),
    re.compile(r"(?<!\d)(20\d{2})[-/.](\d{1,2})(?![-/.\d])"),
)
_QUARTER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<!\d)(20\d{2})\s*年?\s*第?\s*([1-4])\s*(?:四半期|季度)"),
    re.compile(r"(?<!\d)(20\d{2})\s*[QＱ]\s*([1-4])(?!\d)", re.IGNORECASE),
)
_LATEST_QUARTER_PATTERN = re.compile(
    r"(?:最新|直近|足もと|足元|latest|most\s+recent)\s*(?:の\s*)?"
    r"(?:四半期|季度|quarter)",
    re.IGNORECASE,
)
_PAREN_PATTERN = re.compile(r"[（(]([^（）()]{1,100})[）)]")
_QUOTED_PATTERN = re.compile(r"[「『“\"]([^」』”\"]{1,100})[」』”\"]")
_INLINE_SLASH_PATTERN = re.compile(
    r"([A-Za-z0-9\u3040-\u30ff\u3400-\u9fffー]{1,30})"
    r"[/／]"
    r"([A-Za-z0-9\u3040-\u30ff\u3400-\u9fffー]{1,30})"
)
_DIVIDED_COMPARISON_PATTERN = re.compile(
    r"([^\s、。！？?!]{1,30})と([^\s、。！？?!]{1,30})に分けて"
)
_CLAUSE_SPLIT_PATTERN = re.compile(
    r"(?:[。！？?!；;]\s*|(?:。)?\s*(?:また|さらに|あわせて|併せて)\s*)"
)


def _valid_date(year: int, month: int, day: int) -> date | None:
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _next_month(year: int, month: int) -> date:
    return date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)


@dataclass(frozen=True)
class TemporalScope:
    kind: str = "latest_available"
    start_date: date | None = None
    end_date_exclusive: date | None = None
    exact_dates: tuple[date, ...] = ()
    source_text: str = ""

    @property
    def is_explicit(self) -> bool:
        return self.kind != "latest_available"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date_exclusive": (
                self.end_date_exclusive.isoformat()
                if self.end_date_exclusive
                else None
            ),
            "exact_dates": [value.isoformat() for value in self.exact_dates],
            "source_text": self.source_text,
        }


@dataclass(frozen=True)
class QueryFacet:
    facet_id: str
    query: str
    required_terms: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "facet_id": self.facet_id,
            "query": self.query,
            "required_terms": list(self.required_terms),
        }


@dataclass(frozen=True)
class QueryPlan:
    question: str
    temporal_scope: TemporalScope
    facets: tuple[QueryFacet, ...]
    comparison_terms: tuple[str, ...] = ()
    needs_explanation: bool = False
    discover_facets: bool = False
    output_hints: dict[str, Any] = field(default_factory=dict)

    @property
    def complexity(self) -> int:
        return max(1, len(self.facets) + max(0, len(self.comparison_terms) - 1))

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "temporal_scope": self.temporal_scope.as_dict(),
            "facets": [facet.as_dict() for facet in self.facets],
            "comparison_terms": list(self.comparison_terms),
            "needs_explanation": self.needs_explanation,
            "discover_facets": self.discover_facets,
            "complexity": self.complexity,
            "output_hints": dict(self.output_hints),
        }


def parse_temporal_scope(question: str) -> TemporalScope:
    text = str(question or "").strip()
    exact_dates: set[date] = set()
    for pattern in _FULL_DATE_PATTERNS:
        for match in pattern.finditer(text):
            parsed = _valid_date(*(int(part) for part in match.groups()))
            if parsed is not None:
                exact_dates.add(parsed)
    if exact_dates:
        return TemporalScope(
            kind="exact_dates",
            exact_dates=tuple(sorted(exact_dates)),
            source_text=text,
        )

    for pattern in _QUARTER_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        year, quarter = (int(part) for part in match.groups())
        start_month = (quarter - 1) * 3 + 1
        start = date(year, start_month, 1)
        end = date(year + (1 if quarter == 4 else 0), 1 if quarter == 4 else start_month + 3, 1)
        return TemporalScope(
            kind="quarter",
            start_date=start,
            end_date_exclusive=end,
            source_text=match.group(0),
        )

    if _LATEST_QUARTER_PATTERN.search(text):
        return TemporalScope(kind="latest_quarter", source_text=text)

    for pattern in _MONTH_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        year, month = (int(part) for part in match.groups())
        parsed = _valid_date(year, month, 1)
        if parsed is not None:
            return TemporalScope(
                kind="month",
                start_date=parsed,
                end_date_exclusive=_next_month(year, month),
                source_text=match.group(0),
            )

    return TemporalScope(kind="latest_available", source_text=text)


def _unique_texts(values: Iterable[str], *, maximum: int = 12) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n、,。.;；")
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= maximum:
            break
    return tuple(result)


def _comparison_terms(question: str) -> tuple[str, ...]:
    candidates: list[str] = []
    for pattern in (_PAREN_PATTERN, _QUOTED_PATTERN):
        for match in pattern.finditer(question):
            segment = match.group(1)
            if "/" in segment or "／" in segment:
                candidates.extend(re.split(r"[/／]", segment))
            elif len(segment) <= 40:
                candidates.append(segment)
    for match in _INLINE_SLASH_PATTERN.finditer(question):
        candidates.extend(match.groups())
    for match in _DIVIDED_COMPARISON_PATTERN.finditer(question):
        candidates.extend(match.groups())
    return _unique_texts(candidates)


def _query_facets(question: str, comparison_terms: tuple[str, ...]) -> tuple[QueryFacet, ...]:
    clauses = _unique_texts(_CLAUSE_SPLIT_PATTERN.split(question), maximum=6)
    base_clauses = clauses or (question,)
    facets: list[QueryFacet] = [
        QueryFacet(facet_id=f"clause_{index}", query=clause)
        for index, clause in enumerate(base_clauses, start=1)
        if clause
    ]
    for term in comparison_terms:
        facets.append(
            QueryFacet(
                facet_id=f"comparison_{len(facets) + 1}",
                query=f"{question} {term}",
                required_terms=(term,),
            )
        )
    deduped: list[QueryFacet] = []
    seen_queries: set[str] = set()
    for facet in facets:
        key = facet.query.casefold()
        if key in seen_queries:
            continue
        seen_queries.add(key)
        deduped.append(facet)
    return tuple(deduped[:12]) or (QueryFacet(facet_id="question", query=question),)


def plan_bookrag_query(
    question: str,
    *,
    explanation_markers: Iterable[str] = (),
    facet_discovery_markers: Iterable[str] = (),
) -> QueryPlan:
    normalized = re.sub(r"\s+", " ", str(question or "")).strip()
    if not normalized:
        raise ValueError("question is required.")
    comparison_terms = _comparison_terms(normalized)
    marker_values = tuple(
        str(marker or "").strip().casefold()
        for marker in explanation_markers
        if str(marker or "").strip()
    )
    lowered = normalized.casefold()
    needs_explanation = any(marker in lowered for marker in marker_values)
    discovery_markers = tuple(
        str(marker or "").strip().casefold()
        for marker in facet_discovery_markers
        if str(marker or "").strip()
    )
    discover_facets = any(marker in lowered for marker in discovery_markers)
    sentence_match = re.search(r"(\d+)\s*[～~〜-]\s*(\d+)\s*文", normalized)
    output_hints: dict[str, Any] = {}
    if sentence_match:
        output_hints["sentences_per_item"] = [
            int(sentence_match.group(1)),
            int(sentence_match.group(2)),
        ]
    return QueryPlan(
        question=normalized,
        temporal_scope=parse_temporal_scope(normalized),
        facets=_query_facets(normalized, comparison_terms),
        comparison_terms=comparison_terms,
        needs_explanation=needs_explanation,
        discover_facets=discover_facets,
        output_hints=output_hints,
    )
