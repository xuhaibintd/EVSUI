from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


BOOKRAG_RETRIEVAL_POLICY_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "bookrag_retrieval_policy.json"
)


def _as_int(value: Any, default: int, *, minimum: int = 0, maximum: int = 10_000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _as_float(
    value: Any,
    default: float,
    *,
    minimum: float = 0.0,
    maximum: float = 100.0,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _text_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        text
        for item in value
        if (text := str(item or "").strip().lower())
    )


def _float_map(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip().lower(): _as_float(item, 0.0)
        for key, item in value.items()
        if str(key).strip()
    }


@dataclass(frozen=True)
class CandidateBudget:
    per_track: int = 20
    minimum_final: int = 4
    maximum_final: int = 18


@dataclass(frozen=True)
class RankingPolicy:
    semantic_weight: float = 1.0
    freshness_weight: float = 0.5
    role_weight: float = 0.15
    rrf_constant: int = 60
    series_bonus: dict[str, float] = field(default_factory=dict)
    role_bonus: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class BackgroundPolicy:
    eligible_series: tuple[str, ...] = ()
    eligible_roles: tuple[str, ...] = ()
    latest_documents_per_series_kept_in_current: int = 1
    maximum_fraction_of_final_evidence: float = 0.4
    explanation_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanningPolicy:
    facet_discovery_markers: tuple[str, ...] = ()
    maximum_dynamic_facets: int = 8


@dataclass(frozen=True)
class DocumentClassificationRule:
    pattern: str
    series: str
    role: str


@dataclass(frozen=True)
class DocumentClassificationPolicy:
    fallback_series: str = "other"
    fallback_role: str = "other"
    rules: tuple[DocumentClassificationRule, ...] = ()


@dataclass(frozen=True)
class CoveragePolicy:
    minimum_current_packages: int = 2
    minimum_unique_current_documents: int = 2
    minimum_substantive_characters: int = 480
    minimum_explanation_characters: int = 900


@dataclass(frozen=True)
class DiversityPolicy:
    maximum_nodes_per_document: int = 2


@dataclass(frozen=True)
class GovernancePolicy:
    allowed_metadata_statuses: tuple[str, ...] = ("confirmed",)


@dataclass(frozen=True)
class BookRAGRetrievalPolicy:
    policy_version: int
    candidate_budget: CandidateBudget
    ranking: RankingPolicy
    background: BackgroundPolicy
    planning: PlanningPolicy
    document_classification: DocumentClassificationPolicy
    coverage: CoveragePolicy
    diversity: DiversityPolicy
    governance: GovernancePolicy
    source_path: str

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "candidate_budget": {
                "per_track": self.candidate_budget.per_track,
                "minimum_final": self.candidate_budget.minimum_final,
                "maximum_final": self.candidate_budget.maximum_final,
            },
            "background": {
                "conditional": True,
                "eligible_series": list(self.background.eligible_series),
                "eligible_roles": list(self.background.eligible_roles),
            },
            "planning": {
                "maximum_dynamic_facets": self.planning.maximum_dynamic_facets,
            },
            "governance": {
                "allowed_metadata_statuses": list(
                    self.governance.allowed_metadata_statuses
                )
            },
        }


def _parse_policy(payload: dict[str, Any], *, source_path: str) -> BookRAGRetrievalPolicy:
    candidate = payload.get("candidate_budget") or {}
    ranking = payload.get("ranking") or {}
    background = payload.get("background") or {}
    planning = payload.get("planning") or {}
    document_classification = payload.get("document_classification") or {}
    coverage = payload.get("coverage") or {}
    diversity = payload.get("diversity") or {}
    governance = payload.get("governance") or {}

    minimum_final = _as_int(candidate.get("minimum_final"), 4, minimum=1, maximum=100)
    maximum_final = _as_int(candidate.get("maximum_final"), 18, minimum=1, maximum=100)
    if minimum_final > maximum_final:
        minimum_final = maximum_final

    classification_rules = tuple(
        DocumentClassificationRule(
            pattern=str(row.get("pattern") or "").strip(),
            series=str(row.get("series") or "").strip().lower(),
            role=str(row.get("role") or "").strip().lower(),
        )
        for row in list(document_classification.get("rules") or [])
        if isinstance(row, dict)
        and str(row.get("pattern") or "").strip()
        and str(row.get("series") or "").strip()
        and str(row.get("role") or "").strip()
    )
    for rule in classification_rules:
        re.compile(rule.pattern, flags=re.IGNORECASE)

    return BookRAGRetrievalPolicy(
        policy_version=_as_int(payload.get("policy_version"), 1, minimum=1),
        candidate_budget=CandidateBudget(
            per_track=_as_int(candidate.get("per_track"), 20, minimum=1, maximum=20),
            minimum_final=minimum_final,
            maximum_final=maximum_final,
        ),
        ranking=RankingPolicy(
            semantic_weight=_as_float(ranking.get("semantic_weight"), 1.0),
            freshness_weight=_as_float(ranking.get("freshness_weight"), 0.5),
            role_weight=_as_float(ranking.get("role_weight"), 0.15),
            rrf_constant=_as_int(ranking.get("rrf_constant"), 60, minimum=1),
            series_bonus=_float_map(ranking.get("series_bonus")),
            role_bonus=_float_map(ranking.get("role_bonus")),
        ),
        background=BackgroundPolicy(
            eligible_series=_text_tuple(background.get("eligible_series")),
            eligible_roles=_text_tuple(background.get("eligible_roles")),
            latest_documents_per_series_kept_in_current=_as_int(
                background.get("latest_documents_per_series_kept_in_current"),
                1,
                minimum=0,
                maximum=20,
            ),
            maximum_fraction_of_final_evidence=_as_float(
                background.get("maximum_fraction_of_final_evidence"),
                0.4,
                maximum=1.0,
            ),
            explanation_markers=_text_tuple(background.get("explanation_markers")),
        ),
        planning=PlanningPolicy(
            facet_discovery_markers=_text_tuple(
                planning.get("facet_discovery_markers")
            ),
            maximum_dynamic_facets=_as_int(
                planning.get("maximum_dynamic_facets"),
                8,
                minimum=0,
                maximum=20,
            ),
        ),
        document_classification=DocumentClassificationPolicy(
            fallback_series=(
                str(document_classification.get("fallback_series") or "other")
                .strip()
                .lower()
            ),
            fallback_role=(
                str(document_classification.get("fallback_role") or "other")
                .strip()
                .lower()
            ),
            rules=classification_rules,
        ),
        coverage=CoveragePolicy(
            minimum_current_packages=_as_int(
                coverage.get("minimum_current_packages"), 2, minimum=1
            ),
            minimum_unique_current_documents=_as_int(
                coverage.get("minimum_unique_current_documents"), 2, minimum=1
            ),
            minimum_substantive_characters=_as_int(
                coverage.get("minimum_substantive_characters"), 480, minimum=0
            ),
            minimum_explanation_characters=_as_int(
                coverage.get("minimum_explanation_characters"), 900, minimum=0
            ),
        ),
        diversity=DiversityPolicy(
            maximum_nodes_per_document=_as_int(
                diversity.get("maximum_nodes_per_document"), 2, minimum=1, maximum=20
            )
        ),
        governance=GovernancePolicy(
            allowed_metadata_statuses=_text_tuple(
                governance.get("allowed_metadata_statuses")
            )
            or ("confirmed",)
        ),
        source_path=source_path,
    )


@lru_cache(maxsize=8)
def load_bookrag_retrieval_policy(
    path: str | Path = BOOKRAG_RETRIEVAL_POLICY_PATH,
) -> BookRAGRetrievalPolicy:
    policy_path = Path(path).expanduser().resolve()
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("BookRAG retrieval policy must be a JSON object.")
    return _parse_policy(payload, source_path=str(policy_path))
