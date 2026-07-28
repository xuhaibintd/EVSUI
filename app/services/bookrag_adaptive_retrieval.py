from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date
from typing import Any, Callable, Iterable

from app.services.bookrag_document_metadata import fetch_governed_document_scope
from app.services.bookrag_query_planner import QueryFacet, QueryPlan, plan_bookrag_query
from app.services.bookrag_retrieval import (
    render_bookrag_evidence_packages,
    retrieve_bookrag_evidence,
)
from app.services.bookrag_retrieval_policy import (
    BookRAGRetrievalPolicy,
    load_bookrag_retrieval_policy,
)


EvidencePackage = dict[str, Any]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _sql_text(value: Any) -> str:
    return "'" + _text(value).replace("'", "''") + "'"


def build_document_filter(doc_ids: Iterable[Any]) -> str:
    values = sorted({_text(value) for value in doc_ids if _text(value)})
    if not values:
        raise ValueError("At least one document id is required for governed retrieval.")
    return "doc_id IN (" + ", ".join(_sql_text(value) for value in values) + ")"


def build_exact_node_filter(packages: Iterable[EvidencePackage]) -> str:
    pairs = sorted(
        {
            (_text(match.get("doc_id")), _text(match.get("node_id")))
            for package in packages
            if isinstance(package, dict)
            for match in [package.get("match") or {}]
            if isinstance(match, dict)
            and _text(match.get("doc_id"))
            and _text(match.get("node_id"))
        }
    )
    if not pairs:
        raise ValueError("Final BookRAG evidence contains no document/node keys.")
    return " OR ".join(
        f"(doc_id={_sql_text(doc_id)} AND node_id={_sql_text(node_id)})"
        for doc_id, node_id in pairs
    )


def _document_date(document: dict[str, Any]) -> date | None:
    value = _text(document.get("publication_date"))
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _document_is_background_eligible(
    document: dict[str, Any],
    policy: BookRAGRetrievalPolicy,
) -> bool:
    series = _text(document.get("document_series")).lower()
    role = _text(document.get("document_role")).lower()
    return (
        series in policy.background.eligible_series
        or role in policy.background.eligible_roles
    )


def partition_document_scope(
    documents: Iterable[dict[str, Any]],
    policy: BookRAGRetrievalPolicy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep the newest configured periodic documents in current; older ones become background."""
    source = [dict(row) for row in documents if _text(row.get("doc_id"))]
    non_background = [
        row for row in source if not _document_is_background_eligible(row, policy)
    ]
    eligible = [
        row for row in source if _document_is_background_eligible(row, policy)
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        series = _text(row.get("document_series")).lower()
        role = _text(row.get("document_role")).lower()
        grouped[f"series:{series}" if series else f"role:{role}"].append(row)

    current = list(non_background)
    background: list[dict[str, Any]] = []
    keep_count = policy.background.latest_documents_per_series_kept_in_current
    for rows in grouped.values():
        ordered = sorted(
            rows,
            key=lambda row: (
                _document_date(row) or date.min,
                _text(row.get("filename")),
                _text(row.get("doc_id")),
            ),
            reverse=True,
        )
        current.extend(ordered[:keep_count])
        background.extend(ordered[keep_count:])
    current.sort(
        key=lambda row: (
            _document_date(row) or date.min,
            _text(row.get("filename")),
        ),
        reverse=True,
    )
    background.sort(
        key=lambda row: (
            _document_date(row) or date.min,
            _text(row.get("filename")),
        ),
        reverse=True,
    )
    return current, background


def _package_key(package: EvidencePackage) -> tuple[str, str]:
    match = package.get("match") or {}
    if not isinstance(match, dict):
        match = {}
    return _text(match.get("doc_id")), _text(
        match.get("node_id") or match.get("content")
    )


def _package_text(package: EvidencePackage) -> str:
    parts: list[str] = []
    for key in ("match", "section", "block"):
        value = package.get(key) or {}
        if not isinstance(value, dict):
            continue
        for field in (
            "title",
            "content",
            "text",
            "image_caption",
            "image_context",
            "path",
        ):
            text = _text(value.get(field))
            if text:
                parts.append(text)
    return "\n".join(parts)


def _mark_candidates(
    packages: Iterable[EvidencePackage],
    *,
    track: str,
    facet: QueryFacet,
) -> list[EvidencePackage]:
    result: list[EvidencePackage] = []
    for semantic_rank, package in enumerate(packages, start=1):
        item = dict(package)
        item["retrieval_track"] = track
        item["matched_facets"] = [facet.facet_id]
        item["_semantic_rank"] = semantic_rank
        result.append(item)
    return result


def _combine_candidates(packages: Iterable[EvidencePackage]) -> list[EvidencePackage]:
    combined: dict[tuple[str, str], EvidencePackage] = {}
    order: list[tuple[str, str]] = []
    for package in packages:
        key = _package_key(package)
        if not any(key):
            continue
        existing = combined.get(key)
        if existing is None:
            combined[key] = dict(package)
            order.append(key)
            continue
        existing["_semantic_rank"] = min(
            int(existing.get("_semantic_rank") or 10_000),
            int(package.get("_semantic_rank") or 10_000),
        )
        existing["matched_facets"] = list(
            dict.fromkeys(
                [
                    *list(existing.get("matched_facets") or []),
                    *list(package.get("matched_facets") or []),
                ]
            )
        )
    return [combined[key] for key in order]


def rerank_packages(
    packages: Iterable[EvidencePackage],
    policy: BookRAGRetrievalPolicy,
    *,
    apply_freshness: bool,
) -> list[EvidencePackage]:
    candidates = _combine_candidates(packages)
    dates = sorted(
        {
            parsed
            for package in candidates
            if isinstance((document := package.get("document") or {}), dict)
            and (parsed := _document_date(document)) is not None
        },
        reverse=True,
    )
    date_rank = {value: index for index, value in enumerate(dates, start=1)}
    rrf_constant = policy.ranking.rrf_constant
    ranked: list[EvidencePackage] = []
    for package in candidates:
        document = package.get("document") or {}
        if not isinstance(document, dict):
            document = {}
        semantic_rank = max(1, int(package.get("_semantic_rank") or 1))
        parsed_date = _document_date(document)
        freshness_rank = date_rank.get(parsed_date, len(dates) + 1)
        series = _text(document.get("document_series")).lower()
        role = _text(document.get("document_role")).lower()
        role_bonus = (
            policy.ranking.series_bonus.get(series, 0.0)
            + policy.ranking.role_bonus.get(role, 0.0)
        )
        adaptive_score = policy.ranking.semantic_weight / (
            rrf_constant + semantic_rank
        )
        if apply_freshness:
            adaptive_score += policy.ranking.freshness_weight / (
                rrf_constant + freshness_rank
            )
        adaptive_score += policy.ranking.role_weight * role_bonus
        item = dict(package)
        item["adaptive_score"] = round(adaptive_score, 12)
        item["semantic_rank"] = semantic_rank
        item["freshness_rank"] = freshness_rank if parsed_date else None
        ranked.append(item)
    ranked.sort(
        key=lambda package: (
            float(package.get("adaptive_score") or 0.0),
            _document_date(package.get("document") or {}) or date.min,
            -int(package.get("semantic_rank") or 1),
        ),
        reverse=True,
    )
    return ranked


def diversify_packages(
    packages: Iterable[EvidencePackage],
    policy: BookRAGRetrievalPolicy,
    *,
    limit: int,
) -> list[EvidencePackage]:
    selected: list[EvidencePackage] = []
    document_counts: dict[str, int] = defaultdict(int)
    maximum = policy.diversity.maximum_nodes_per_document
    for package in packages:
        doc_id, _ = _package_key(package)
        if doc_id and document_counts[doc_id] >= maximum:
            continue
        selected.append(package)
        if doc_id:
            document_counts[doc_id] += 1
        if len(selected) >= limit:
            break
    return selected


def evaluate_evidence_coverage(
    plan: QueryPlan,
    packages: Iterable[EvidencePackage],
    policy: BookRAGRetrievalPolicy,
) -> dict[str, Any]:
    source = list(packages)
    unique_documents = {
        doc_id for package in source if (doc_id := _package_key(package)[0])
    }
    combined_text = "\n".join(_package_text(package) for package in source)
    lowered = combined_text.casefold()
    facet_coverage: dict[str, bool] = {}
    for facet in plan.facets:
        required_terms = [
            term.casefold() for term in facet.required_terms if term.strip()
        ]
        facet_coverage[facet.facet_id] = (
            not required_terms
            or all(term in lowered for term in required_terms)
        )
    substantive_characters = len(combined_text)
    minimum_characters = (
        policy.coverage.minimum_explanation_characters
        if plan.needs_explanation
        else policy.coverage.minimum_substantive_characters
    )
    reasons: list[str] = []
    if len(source) < policy.coverage.minimum_current_packages:
        reasons.append("too_few_current_packages")
    if len(unique_documents) < policy.coverage.minimum_unique_current_documents:
        reasons.append("too_few_current_documents")
    if substantive_characters < minimum_characters:
        reasons.append("insufficient_substantive_content")
    missing_facets = [
        facet_id for facet_id, covered in facet_coverage.items() if not covered
    ]
    if missing_facets:
        reasons.append("missing_required_facets")
    return {
        "sufficient": not reasons,
        "reasons": reasons,
        "package_count": len(source),
        "unique_document_count": len(unique_documents),
        "substantive_characters": substantive_characters,
        "facet_coverage": facet_coverage,
        "missing_facet_ids": missing_facets,
    }


def _search_facets(
    *,
    vector_store: Any,
    vector_store_name: str,
    schema_name: str | None,
    facets: Iterable[QueryFacet],
    doc_ids: Iterable[str],
    track: str,
    top_k: int,
    execute_sql_fn: Callable[..., Any],
) -> tuple[list[EvidencePackage], list[Any]]:
    filter_sql = build_document_filter(doc_ids)
    candidates: list[EvidencePackage] = []
    similarity_results: list[Any] = []
    for facet in facets:
        similarity_result = vector_store.similarity_search(
            question=facet.query,
            top_k=top_k,
            filter=filter_sql,
        )
        similarity_results.append(similarity_result)
        evidence = retrieve_bookrag_evidence(
            vector_store_name=vector_store_name,
            similarity_result=similarity_result,
            execute_sql_fn=execute_sql_fn,
            schema_name=schema_name,
        )
        candidates.extend(
            _mark_candidates(
                list(evidence.get("packages") or []),
                track=track,
                facet=facet,
            )
        )
    return candidates, similarity_results


def _facets_for_background(
    plan: QueryPlan,
    coverage: dict[str, Any],
) -> tuple[QueryFacet, ...]:
    missing = set(coverage.get("missing_facet_ids") or [])
    if missing:
        selected = tuple(
            facet for facet in plan.facets if facet.facet_id in missing
        )
        if selected:
            return selected
    return plan.facets


def discover_facets_from_candidates(
    plan: QueryPlan,
    packages: Iterable[EvidencePackage],
    *,
    maximum: int,
) -> tuple[QueryFacet, ...]:
    """Discover document-native section dimensions without a fixed asset taxonomy."""
    if not plan.discover_facets or maximum <= 0:
        return ()
    labels: list[str] = []
    seen: set[str] = set()
    existing_queries = {facet.query.casefold() for facet in plan.facets}
    for package in packages:
        candidates: list[str] = []
        for key in ("match", "section"):
            value = package.get(key) or {}
            if not isinstance(value, dict):
                continue
            title = _text(value.get("title"))
            if title:
                candidates.append(title)
            path = _text(value.get("path"))
            if path:
                candidates.extend(
                    segment.strip()
                    for segment in path.replace("＞", ">").split(">")
                    if segment.strip()
                )
        for label in candidates:
            normalized = " ".join(label.split()).strip(" -–—:：")
            key = normalized.casefold()
            if (
                len(normalized) < 2
                or len(normalized) > 60
                or key in seen
                or key in existing_queries
                or normalized.lower().endswith(".pdf")
            ):
                continue
            seen.add(key)
            labels.append(normalized)
            if len(labels) >= maximum:
                break
        if len(labels) >= maximum:
            break
    return tuple(
        QueryFacet(
            facet_id=f"discovered_{index}",
            query=f"{plan.question} {label}",
            required_terms=(),
        )
        for index, label in enumerate(labels, start=1)
    )


def _final_limit(
    plan: QueryPlan,
    requested_top_k: int | None,
    policy: BookRAGRetrievalPolicy,
) -> int:
    if requested_top_k is not None:
        try:
            requested = int(requested_top_k)
        except (TypeError, ValueError):
            requested = policy.candidate_budget.minimum_final
    else:
        requested = policy.candidate_budget.minimum_final + plan.complexity
    return max(
        1,
        min(policy.candidate_budget.maximum_final, requested),
    )


def retrieve_adaptive_bookrag_evidence(
    *,
    vector_store: Any,
    vector_store_name: str,
    question: str,
    schema_name: str | None,
    execute_sql_fn: Callable[..., Any],
    top_k: int | None = None,
    policy: BookRAGRetrievalPolicy | None = None,
) -> tuple[dict[str, Any], Any | None]:
    effective_policy = policy or load_bookrag_retrieval_policy()
    plan = plan_bookrag_query(
        question,
        explanation_markers=effective_policy.background.explanation_markers,
        facet_discovery_markers=(
            effective_policy.planning.facet_discovery_markers
        ),
    )
    scope = fetch_governed_document_scope(
        vector_store_name=vector_store_name,
        schema_name=schema_name,
        execute_sql_fn=execute_sql_fn,
        temporal_scope=plan.temporal_scope,
        background_document_series=effective_policy.background.eligible_series,
        background_document_roles=effective_policy.background.eligible_roles,
        metadata_statuses=effective_policy.governance.allowed_metadata_statuses,
    )
    documents = list(scope.get("primary_documents") or [])
    current_documents, background_documents = partition_document_scope(
        documents, effective_policy
    )
    current_doc_ids = [
        _text(row.get("doc_id")) for row in current_documents if _text(row.get("doc_id"))
    ]
    background_doc_ids = [
        _text(row.get("doc_id"))
        for row in background_documents
        if _text(row.get("doc_id"))
    ]
    if not current_doc_ids and background_doc_ids:
        current_doc_ids, background_doc_ids = background_doc_ids, []
    if not current_doc_ids:
        return (
            {
                "vector_store_name": vector_store_name,
                "schema_name": schema_name,
                "packages": [],
                "package_count": 0,
                "packages_total": 0,
                "similarity_row_count": 0,
                "similarity_headers": [],
                "similarity_preview": "",
                "evidence_text": "",
                "retrieval_source": f"{scope.get('view_name')} -> bnode.content",
                "retrieval_scope": scope,
                "query_plan": plan.as_dict(),
                "coverage": {
                    "sufficient": False,
                    "reasons": ["no_governed_documents"],
                },
                "retrieval_policy": effective_policy.as_public_dict(),
            },
            None,
        )

    candidate_top_k = effective_policy.candidate_budget.per_track
    current_candidates, current_similarity_results = _search_facets(
        vector_store=vector_store,
        vector_store_name=vector_store_name,
        schema_name=schema_name,
        facets=plan.facets,
        doc_ids=current_doc_ids,
        track="latest_related",
        top_k=candidate_top_k,
        execute_sql_fn=execute_sql_fn,
    )
    discovered_facets = discover_facets_from_candidates(
        plan,
        current_candidates,
        maximum=effective_policy.planning.maximum_dynamic_facets,
    )
    if discovered_facets:
        discovered_candidates, discovered_results = _search_facets(
            vector_store=vector_store,
            vector_store_name=vector_store_name,
            schema_name=schema_name,
            facets=discovered_facets,
            doc_ids=current_doc_ids,
            track="latest_related",
            top_k=candidate_top_k,
            execute_sql_fn=execute_sql_fn,
        )
        current_candidates.extend(discovered_candidates)
        current_similarity_results.extend(discovered_results)
        plan = replace(plan, facets=(*plan.facets, *discovered_facets))
    current_ranked = rerank_packages(
        current_candidates, effective_policy, apply_freshness=True
    )
    limit = _final_limit(plan, top_k, effective_policy)
    current_diverse = diversify_packages(
        current_ranked, effective_policy, limit=limit
    )
    coverage = evaluate_evidence_coverage(
        plan, current_diverse, effective_policy
    )

    background_ranked: list[EvidencePackage] = []
    background_similarity_results: list[Any] = []
    if not coverage["sufficient"] and background_doc_ids:
        background_candidates, background_similarity_results = _search_facets(
            vector_store=vector_store,
            vector_store_name=vector_store_name,
            schema_name=schema_name,
            facets=_facets_for_background(plan, coverage),
            doc_ids=background_doc_ids,
            track="periodic_background",
            top_k=candidate_top_k,
            execute_sql_fn=execute_sql_fn,
        )
        background_ranked = rerank_packages(
            background_candidates, effective_policy, apply_freshness=False
        )

    if background_ranked and (limit > 1 or not current_ranked):
        maximum_background = max(
            1,
            int(round(
                limit
                * effective_policy.background.maximum_fraction_of_final_evidence
            )),
        )
        background_capacity = limit if not current_ranked else limit - 1
        background_selected = diversify_packages(
            background_ranked,
            effective_policy,
            limit=min(maximum_background, background_capacity),
        )
        current_selected = diversify_packages(
            current_ranked,
            effective_policy,
            limit=limit - len(background_selected),
        )
    else:
        current_selected = current_diverse[:limit]
        background_selected = []

    final_packages = _combine_candidates(
        [*current_selected, *background_selected]
    )
    for rank, package in enumerate(final_packages, start=1):
        package["rank"] = rank
        package.pop("_semantic_rank", None)

    scope.update(
        {
            "mode": (
                "adaptive_current_with_conditional_background"
                if background_selected
                else "adaptive_current_only"
            ),
            "current_documents": current_documents,
            "background_documents": background_documents,
            "current_doc_ids": current_doc_ids,
            "background_doc_ids": background_doc_ids,
            "background_used": bool(background_selected),
        }
    )
    evidence = {
        "vector_store_name": vector_store_name,
        "schema_name": schema_name,
        "packages": final_packages,
        "package_count": len(final_packages),
        "packages_total": len(final_packages),
        "candidate_package_count": len(current_ranked) + len(background_ranked),
        "similarity_row_count": len(current_candidates)
        + len(background_ranked),
        "similarity_headers": [],
        "similarity_preview": "",
        "evidence_text": render_bookrag_evidence_packages(final_packages),
        "retrieval_source": f"{scope.get('view_name')} -> bnode.content",
        "retrieval_scope": scope,
        "query_plan": plan.as_dict(),
        "coverage": {
            **coverage,
            "background_used": bool(background_selected),
            "background_candidate_count": len(background_ranked),
        },
        "retrieval_policy": effective_policy.as_public_dict(),
    }
    first_similarity_result = (
        current_similarity_results[0]
        if current_similarity_results
        else (
            background_similarity_results[0]
            if background_similarity_results
            else None
        )
    )
    return evidence, first_similarity_result


def lock_similarity_result_to_evidence(
    *,
    vector_store: Any,
    question: str,
    packages: Iterable[EvidencePackage],
) -> Any:
    source = list(packages)
    return vector_store.similarity_search(
        question=question,
        top_k=max(1, len(source)),
        filter=build_exact_node_filter(source),
    )
