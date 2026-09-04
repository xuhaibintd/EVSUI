from __future__ import annotations

import hmac
import json
import os
import uuid
from typing import Any
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.bookrag_adaptive_retrieval import (
    lock_similarity_result_to_evidence,
    retrieve_adaptive_bookrag_evidence,
)
from app.services.bookrag_retrieval import (
    render_bookrag_evidence_packages,
)
from app.services.bookrag_schema import build_bookrag_relationship_contract
from app.teradata_runtime import TERADATA_IMPORT_ERROR, VectorStore, execute_sql
from app.utils.table_state import format_preview
from app.web_support import (
    _activate_session_state,  # noqa: F401 - compatibility patch point for API tests/hosts
    _build_bookrag_chat_reply,
    _ensure_connected_runtime_for_session,
    _ensure_external_api_runtime,
    _is_logged_in,
)

router = APIRouter()

BOOKRAG_API_VERSION = "bookrag-v1"


class BookRAGRetrieveRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    vector_store_name: str | None = Field(default=None, max_length=256)
    schema_name: str | None = Field(default=None, max_length=256)
    top_k: int = Field(default=5, ge=1, le=20)


class BookRAGAnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    vector_store_name: str | None = Field(default=None, max_length=256)
    schema_name: str | None = Field(default=None, max_length=256)
    top_k: int = Field(default=5, ge=1, le=20)
    include_entities: bool = True
    include_mapping: bool = True


class BookRAGApiMeta(BaseModel):
    request_id: str
    generated_at: str
    api_version: str
    auth_mode: str
    principal: str
    top_k: int | None = None


class BookRAGEvidenceMatchResponse(BaseModel):
    node_id: str | None = None
    doc_id: str | None = None
    node_type: str | None = None
    title: str | None = None
    content: str | None = None
    path: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    source_element_id: str | None = None
    parent_node_id: str | None = None
    ordinal: int | None = None


class BookRAGEvidenceSectionResponse(BaseModel):
    node_id: str | None = None
    title: str | None = None
    content: str | None = None
    path: str | None = None
    page_start: int | None = None
    page_end: int | None = None


class BookRAGEvidenceBlockResponse(BaseModel):
    element_id: str | None = None
    type: str | None = None
    text: str | None = None
    text_as_html: str | None = None
    image_caption: str | None = None
    image_context: str | None = None
    page_number: int | None = None
    ordinal: int | None = None


class BookRAGEvidenceEntityResponse(BaseModel):
    entity_id: str | None = None
    doc_id: str | None = None
    canonical_name: str | None = None
    display_name: str | None = None
    entity_type: str | None = None
    mention_count: int | None = None
    node_count: int | None = None


class BookRAGEvidenceMappingResponse(BaseModel):
    link_id: str | None = None
    entity_id: str | None = None
    doc_id: str | None = None
    node_id: str | None = None
    section_node_id: str | None = None
    source_field: str | None = None
    mention_text: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    ordinal: int | None = None
    section_path: str | None = None


class BookRAGEvidenceRelationResponse(BaseModel):
    relation_id: str | None = None
    doc_id: str | None = None
    source_element_id: str | None = None
    source_node_id: str | None = None
    section_node_id: str | None = None
    from_entity_id: str | None = None
    from_entity_text: str | None = None
    relationship: str | None = None
    to_entity_id: str | None = None
    to_entity_text: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    ordinal: int | None = None
    section_path: str | None = None


class BookRAGSectionChainItemResponse(BaseModel):
    node_id: str | None = None
    title: str | None = None
    content: str | None = None
    path: str | None = None
    page_start: int | None = None
    page_end: int | None = None


class BookRAGDocumentResponse(BaseModel):
    doc_id: str | None = None
    vector_store_name: str | None = None
    workflow_id: str | None = None
    workflow_name: str | None = None
    job_id: str | None = None
    processing_profile: str | None = None
    source_file: str | None = None
    filename: str | None = None
    filetype: str | None = None
    filesize_bytes: int | None = None
    page_count: int | None = None
    language_hint: str | None = None
    created_at: str | None = None
    publication_date: str | None = None
    publication_date_source: str | None = None
    publication_date_precision: str | None = None
    document_series: str | None = None
    document_role: str | None = None
    logical_document_key: str | None = None
    revision_no: int | None = None
    metadata_status: str | None = None


class BookRAGDocumentRelationResponse(BaseModel):
    from_doc_id: str | None = None
    from_filename: str | None = None
    relation_type: str | None = None
    to_doc_id: str | None = None
    to_filename: str | None = None
    relation_description: str | None = None
    source_type: str | None = None
    direction: str | None = None
    related_doc_id: str | None = None
    related_filename: str | None = None


class BookRAGEvidencePackageResponse(BaseModel):
    rank: int
    score: float | None = None
    adaptive_score: float | None = None
    semantic_rank: int | None = None
    freshness_rank: int | None = None
    retrieval_track: str | None = None
    matched_facets: list[str] = Field(default_factory=list)
    schema_name: str | None = None
    tables: dict[str, str] = Field(default_factory=dict)
    match: BookRAGEvidenceMatchResponse
    section: BookRAGEvidenceSectionResponse | None = None
    section_chain: list[BookRAGSectionChainItemResponse] = Field(default_factory=list)
    block: BookRAGEvidenceBlockResponse | None = None
    document: BookRAGDocumentResponse | None = None
    document_relations: list[BookRAGDocumentRelationResponse] = Field(default_factory=list)
    entities: list[BookRAGEvidenceEntityResponse] = Field(default_factory=list)
    mapping: list[BookRAGEvidenceMappingResponse] = Field(default_factory=list)
    relations: list[BookRAGEvidenceRelationResponse] = Field(default_factory=list)


class BookRAGEvidenceResponse(BaseModel):
    vector_store_name: str
    schema_name: str | None = None
    doc_id: str | None = None
    filename: str | None = None
    source_file: str | None = None
    workflow_name: str | None = None
    processing_profile: str | None = None
    packages: list[BookRAGEvidencePackageResponse] = Field(default_factory=list)
    package_count: int
    packages_total: int | None = None
    similarity_row_count: int
    similarity_headers: list[str] = Field(default_factory=list)
    similarity_preview: str
    evidence_text: str
    top_k_applied: int | None = None
    retrieval_source: str | None = None
    candidate_package_count: int | None = None
    retrieval_scope: dict[str, Any] = Field(default_factory=dict)
    query_plan: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    retrieval_policy: dict[str, Any] = Field(default_factory=dict)


class BookRAGLLMDocumentResponse(BaseModel):
    doc_id: str | None = None
    vector_store_name: str | None = None
    schema_name: str | None = None
    filename: str | None = None
    source_file: str | None = None
    document_type: str | None = None
    language: str | None = None
    reporting_period: str | None = None


class BookRAGLLMTaskResponse(BaseModel):
    mode: str
    output_language: str
    audience: str | None = None
    must_cite: bool = True
    summarize_focus: list[str] = Field(default_factory=list)


class BookRAGLLMOutputContractResponse(BaseModel):
    citation_style: str
    require_grounding: bool = True
    allow_inference: bool = False
    return_json_ready: bool = True


class BookRAGLLMEvidenceItemResponse(BaseModel):
    rank: int | None = None
    score: float | None = None
    retrieval_track: str | None = None
    evidence_type: str | None = None
    path: str | None = None
    section_path: str | None = None
    title: str | None = None
    section_title: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    pages: list[int | None] = Field(default_factory=list)
    content: str = ""
    table_html: str | None = None
    image_caption: str | None = None
    image_context: str | None = None
    node_id: str | None = None
    source_element_id: str | None = None
    entities: list[dict[str, Any]] = Field(default_factory=list)
    mapping: list[dict[str, Any]] = Field(default_factory=list)
    relations: list[dict[str, Any]] = Field(default_factory=list)
    document: dict[str, Any] = Field(default_factory=dict)
    document_relations: list[dict[str, Any]] = Field(default_factory=list)
    why_selected: str | None = None


class BookRAGLLMInputResponse(BaseModel):
    payload_version: str
    question: str
    document: BookRAGLLMDocumentResponse
    task: BookRAGLLMTaskResponse
    output_contract: BookRAGLLMOutputContractResponse
    instructions: list[str] = Field(default_factory=list)
    retrieval_scope: dict[str, Any] = Field(default_factory=dict)
    query_plan: dict[str, Any] = Field(default_factory=dict)
    evidence: list[BookRAGLLMEvidenceItemResponse] = Field(default_factory=list)


class BookRAGAnswerCitationResponse(BaseModel):
    rank: int | None = None
    node_id: str | None = None
    source_element_id: str | None = None
    path: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    doc_id: str | None = None
    filename: str | None = None
    publication_date: str | None = None
    retrieval_track: str | None = None


class BookRAGAnswerPayloadResponse(BaseModel):
    mode: str
    model: str
    grounded: bool
    text: str
    citations: list[BookRAGAnswerCitationResponse] = Field(default_factory=list)


class BookRAGRetrieveResponse(BaseModel):
    meta: BookRAGApiMeta
    question: str
    vector_store_name: str
    schema_name: str | None = None
    evidence: BookRAGEvidenceResponse
    assistant_message: str
    user_time: str | None = None
    assistant_time: str | None = None


class BookRAGAnswerResponse(BaseModel):
    meta: BookRAGApiMeta
    question: str
    vector_store_name: str
    schema_name: str | None = None
    top_k: int
    llm_input: BookRAGLLMInputResponse
    answer: BookRAGAnswerPayloadResponse
    evidence: BookRAGEvidenceResponse
    assistant_message: str
    user_time: str | None = None
    assistant_time: str | None = None


def _external_api_token(request: Request | None = None) -> str:
    settings = getattr(getattr(getattr(request, "app", None), "state", None), "settings", None)
    if settings is not None:
        if not bool(getattr(settings, "external_api_enabled", False)):
            return ""
        return str(getattr(settings, "external_api_token", "") or "").strip()
    return str(os.getenv("EVSUI_API_TOKEN", "")).strip()


def _resolve_external_token_context(request: Request) -> dict[str, str] | None:
    configured = _external_api_token(request)
    if not configured:
        return None

    bearer = str(request.headers.get("authorization", "")).strip()
    if bearer.lower().startswith("bearer "):
        token = bearer[7:].strip()
        if token and hmac.compare_digest(token, configured):
            return {"mode": "bearer", "principal": "external_api"}

    api_key = str(request.headers.get("x-api-key", "")).strip()
    if api_key and hmac.compare_digest(api_key, configured):
        return {"mode": "api_key", "principal": "external_api"}
    return None


def _has_valid_external_api_token(request: Request) -> bool:
    return _resolve_external_token_context(request) is not None


def _resolve_api_access_context(request: Request) -> dict[str, str] | None:
    if _is_logged_in(request, request.app):
        scope = _activate_session_state(request, request.app)
        principal = str((scope or {}).get("username") or "").strip() or "browser_session"
        return {"mode": "session", "principal": principal}
    return _resolve_external_token_context(request)


def _require_api_access(request: Request) -> dict[str, str]:
    auth_context = _resolve_api_access_context(request)
    if auth_context is not None:
        return auth_context
    raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Bearer"})


def _ensure_api_runtime(request: Request, auth_context: dict[str, str]) -> None:
    if auth_context.get("mode") == "session":
        _ensure_connected_runtime_for_session(request, request.app)
    else:
        _ensure_external_api_runtime(request.app)


def _request_id_from_request(request: Request) -> str:
    request_id = str(request.headers.get("x-request-id", "")).strip()
    return request_id[:128] if request_id else uuid.uuid4().hex


def _generated_at_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_api_meta(*, request: Request, auth_context: dict[str, str] | None, top_k: int | None = None) -> dict[str, object]:
    context = auth_context or {"mode": "none", "principal": "anonymous"}
    return {
        "request_id": _request_id_from_request(request),
        "generated_at": _generated_at_utc(),
        "api_version": BOOKRAG_API_VERSION,
        "auth_mode": context.get("mode") or "none",
        "principal": context.get("principal") or "anonymous",
        "top_k": top_k,
    }


def _retrieve_bookrag_evidence_or_raise(
    *,
    question: str,
    vector_store_name: str,
    schema_name: str | None,
    top_k: int | None = None,
    lock_final: bool = False,
):
    if VectorStore is None:
        raise HTTPException(status_code=503, detail=f"VectorStore runtime is unavailable: {TERADATA_IMPORT_ERROR}")
    if execute_sql is None:
        raise HTTPException(status_code=503, detail="teradataml.execute_sql is unavailable.")

    question_value = str(question or "").strip()
    if not question_value:
        raise HTTPException(status_code=400, detail="question is required.")

    vector_store_value = str(vector_store_name or "").strip()
    if not vector_store_value:
        raise HTTPException(status_code=400, detail="vector_store_name is required.")

    try:
        vector_store = VectorStore(vector_store_value)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"cannot open VectorStore('{vector_store_value}'): {ex}") from ex

    try:
        evidence, candidate_similarity_result = retrieve_adaptive_bookrag_evidence(
            vector_store=vector_store,
            vector_store_name=vector_store_value,
            question=question_value,
            schema_name=schema_name,
            execute_sql_fn=execute_sql,
            top_k=top_k,
        )
    except Exception as ex:
        raise HTTPException(
            status_code=500,
            detail=f"Adaptive BookRAG retrieval failed for '{vector_store_value}': {ex}",
        ) from ex
    governed_scope = evidence.get("retrieval_scope") or {}
    if not list(governed_scope.get("allowed_doc_ids") or []):
        raise HTTPException(
            status_code=409,
            detail=(
                f"No governed documents match the requested time scope for '{vector_store_value}'. "
                "Confirm publication dates and metadata status, or revise the time condition."
            ),
        )

    response_similarity_result = candidate_similarity_result
    if lock_final and list(evidence.get("packages") or []):
        try:
            response_similarity_result = lock_similarity_result_to_evidence(
                vector_store=vector_store,
                question=question_value,
                packages=list(evidence.get("packages") or []),
            )
        except Exception as ex:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Final BookRAG evidence locking failed on "
                    f"'{vector_store_value}': {ex}"
                ),
            ) from ex
    return question_value, vector_store_value, evidence, response_similarity_result


def _clamp_top_k(raw: int | None, *, default: int = 5, minimum: int = 1, maximum: int = 20) -> int:
    try:
        value = int(raw if raw is not None else default)
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _normalize_optional_text(raw: object) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value or value.lower() == "none":
        return None
    return value


def _normalize_bookrag_evidence(*, evidence: dict[str, object] | None, top_k: int | None) -> dict[str, object]:
    payload = dict(evidence or {})
    source_packages = list(payload.get("packages") or [])
    packages_total = len(source_packages)
    top_k_applied = _clamp_top_k(top_k) if top_k is not None else None
    limited_packages = source_packages[:top_k_applied] if top_k_applied is not None else source_packages
    payload["packages"] = limited_packages
    payload["package_count"] = len(limited_packages)
    payload["packages_total"] = packages_total
    payload["top_k_applied"] = top_k_applied
    payload["retrieval_source"] = payload.get("retrieval_source") or "bnode.content"
    payload.setdefault("similarity_headers", [])
    payload.setdefault("similarity_preview", "")
    if limited_packages:
        payload["evidence_text"] = render_bookrag_evidence_packages(limited_packages)
    else:
        payload["evidence_text"] = ""
    payload.setdefault("similarity_row_count", 0)
    return payload


def _build_bookrag_llm_input(
    *,
    question: str,
    evidence: dict[str, object] | None,
    top_k: int,
    include_entities: bool,
    include_mapping: bool,
) -> dict[str, object]:
    payload = dict(evidence or {})
    packages = list(payload.get("packages") or [])
    limited_packages = packages[:_clamp_top_k(top_k)]
    first_package = limited_packages[0] if limited_packages else {}
    first_match = (first_package.get("match") if isinstance(first_package, dict) else {}) or {}
    first_document = (first_package.get("document") if isinstance(first_package, dict) else {}) or {}

    evidence_items: list[dict[str, object]] = []
    for package in limited_packages:
        match = package.get("match") or {}
        block = package.get("block") or {}
        section = package.get("section") or {}
        document = package.get("document") or {}
        page_start = match.get("page_start") if match.get("page_start") is not None else section.get("page_start")
        page_end = match.get("page_end") if match.get("page_end") is not None else section.get("page_end")
        section_path = section.get("path") or match.get("path")
        content = match.get("content") or block.get("text") or ""
        if block.get("text_as_html"):
            evidence_type = "table"
            why_selected = "Contains structured numeric evidence that can support grounded answer generation."
        elif block.get("image_caption") or block.get("image_context"):
            evidence_type = "image"
            why_selected = "Contains image-derived context relevant to the question."
        else:
            evidence_type = match.get("node_type") or block.get("type") or "text"
            why_selected = "Directly addresses the requested topic in the retrieved section."
        item: dict[str, object] = {
            "rank": package.get("rank"),
            "score": package.get("score"),
            "retrieval_track": package.get("retrieval_track") or "latest_related",
            "evidence_type": evidence_type,
            "path": match.get("path") or section_path,
            "section_path": section_path,
            "title": match.get("title") or section.get("title"),
            "section_title": section.get("title"),
            "page_start": page_start,
            "page_end": page_end,
            "pages": [page_start, page_end],
            "content": content,
            "table_html": block.get("text_as_html"),
            "image_caption": block.get("image_caption"),
            "image_context": block.get("image_context"),
            "node_id": match.get("node_id"),
            "source_element_id": match.get("source_element_id"),
            "why_selected": why_selected,
            "document": document,
            "document_relations": package.get("document_relations") or [],
        }
        if include_entities:
            item["entities"] = package.get("entities") or []
        if include_mapping:
            item["mapping"] = package.get("mapping") or []
        item["relations"] = package.get("relations") or []
        evidence_items.append(item)

    return {
        "payload_version": "bookrag-llm-payload-v1",
        "question": question,
        "document": {
            "doc_id": payload.get("doc_id") or first_match.get("doc_id"),
            "vector_store_name": payload.get("vector_store_name"),
            "schema_name": payload.get("schema_name"),
            "filename": payload.get("filename") or first_document.get("filename"),
            "source_file": payload.get("source_file") or first_document.get("source_file"),
            "document_type": payload.get("document_type") or "bookrag_document",
            "language": payload.get("language") or "ja",
            "reporting_period": payload.get("reporting_period"),
        },
        "task": {
            "mode": "grounded_summary",
            "output_language": "ja",
            "audience": "external_api",
            "must_cite": True,
            "summarize_focus": [
                "performance",
                "revenue_structure",
                "financial_position",
                "risk_factors",
            ],
        },
        "output_contract": {
            "citation_style": "rank",
            "require_grounding": True,
            "allow_inference": False,
            "return_json_ready": True,
        },
        "instructions": [
            "Answer only from the supplied evidence and its governed document scope.",
            "Separate observed facts from inference and do not invent missing support.",
            "Attach rank-based citations to material conclusions.",
            "Treat latest_related evidence as the basis for current conclusions, ratings, forecasts, and numeric facts.",
            "Use periodic_background evidence only to add relevant background, reasons, mechanisms, or detailed analysis.",
            "When sources conflict, prefer the evidence with the newer publication_date; do not let periodic background override a newer conclusion.",
            "Do not claim that a source is uniquely strongest, weakest, or comprehensive unless the supplied evidence directly establishes that comparison.",
            "Keep the response concise and JSON-ready for external API consumers.",
        ],
        "retrieval_scope": payload.get("retrieval_scope"),
        "query_plan": payload.get("query_plan"),
        "evidence": evidence_items,
    }


def _build_bookrag_citations_from_llm_input(llm_input: dict[str, object]) -> list[dict[str, object]]:
    evidence_items = list(llm_input.get("evidence") or [])
    citations: list[dict[str, object]] = []
    for item in evidence_items[:3]:
        pages = item.get("pages") or [None, None]
        citations.append({
            "rank": item.get("rank"),
            "node_id": item.get("node_id"),
            "source_element_id": item.get("source_element_id"),
            "path": item.get("path"),
            "page_start": pages[0] if len(pages) > 0 else None,
            "page_end": pages[1] if len(pages) > 1 else None,
        })
    return citations


def _build_bookrag_llm_prompt(llm_input: dict[str, object]) -> str:
    instructions = [str(item).strip() for item in list(llm_input.get("instructions") or []) if str(item).strip()]
    evidence_items = list(llm_input.get("evidence") or [])
    evidence_lines: list[str] = []
    for item in evidence_items:
        pages = item.get("pages") or [None, None]
        page_label = ""
        if len(pages) >= 2 and pages[0] is not None:
            page_label = f" pages={pages[0]}-{pages[1] if pages[1] is not None else pages[0]}"
        title = str(item.get("title") or item.get("section_title") or "").strip()
        node_id = str(item.get("node_id") or "").strip()
        content = str(item.get("content") or "").strip()
        document = item.get("document") or {}
        if len(content) > 1800:
            content = content[:1800] + " ..."
        entity_items = list(item.get("entities") or [])
        relation_items = list(item.get("relations") or [])
        document_relation_items = list(item.get("document_relations") or [])
        entity_preview = ", ".join(
            str(entity.get("display_name") or entity.get("canonical_name") or entity.get("entity_id") or "").strip()
            for entity in entity_items[:8]
            if str(entity.get("display_name") or entity.get("canonical_name") or entity.get("entity_id") or "").strip()
        )
        relation_preview = "; ".join(
            " | ".join(
                part for part in [
                    str(relation.get("from_entity_text") or relation.get("from_entity_id") or "").strip(),
                    str(relation.get("relationship") or "").strip(),
                    str(relation.get("to_entity_text") or relation.get("to_entity_id") or "").strip(),
                ]
                if part
            )
            for relation in relation_items[:6]
            if any(
                str(relation.get(field) or "").strip()
                for field in ("from_entity_text", "from_entity_id", "relationship", "to_entity_text", "to_entity_id")
            )
        )
        document_label = " ".join(
            part
            for part in (
                str(document.get("filename") or "").strip(),
                f"publication_date={document.get('publication_date')}"
                if document.get("publication_date")
                else "",
                f"series={document.get('document_series')}"
                if document.get("document_series")
                else "",
                f"role={document.get('document_role')}"
                if document.get("document_role")
                else "",
            )
            if part
        )
        lines = [f"[{item.get('rank')}] node_id={node_id} title={title}{page_label}"]
        track = str(item.get("retrieval_track") or "latest_related").strip()
        lines.append(f"Evidence track: {track}")
        if document_label:
            lines.append(f"Document: {document_label}")
        lines.append(content)
        if entity_preview:
            lines.append(f"Entities: {entity_preview}")
        if relation_preview:
            lines.append(f"Relations: {relation_preview}")
        for document_relation in document_relation_items[:8]:
            related_filename = str(
                document_relation.get("related_filename")
                or document_relation.get("related_doc_id")
                or ""
            ).strip()
            relation_type = str(document_relation.get("relation_type") or "related_to").strip()
            direction = str(document_relation.get("direction") or "outgoing").strip()
            description = str(document_relation.get("relation_description") or "").strip()
            line = f"Document Relationship ({direction}): {relation_type} -> {related_filename}"
            if description:
                line += f" — {description}"
            lines.append(line)
        evidence_lines.append("\n".join(lines))
    scope = llm_input.get("retrieval_scope") or {}
    scope_lines: list[str] = []
    if isinstance(scope, dict):
        if scope.get("mode") == "explicit_timeline":
            scope_lines.append("Mode: explicit timeline; obsolete revisions were excluded.")
        elif scope.get("mode") == "latest_related_with_periodic_background":
            scope_lines.append(
                "Mode: latest related evidence plus periodic background; obsolete revisions were excluded."
            )
            scope_lines.append(
                f"Eligible documents: {len(list(scope.get('allowed_doc_ids') or []))}; "
                f"periodic candidates: {len(list(scope.get('periodic_doc_ids') or []))}."
            )
        else:
            for label, key in (
                ("Primary", "primary_documents"),
                ("Supplement", "supplemental_documents"),
            ):
                filenames = [
                    str(row.get("filename") or row.get("doc_id") or "").strip()
                    for row in list(scope.get(key) or [])
                    if isinstance(row, dict)
                ]
                if filenames:
                    scope_lines.append(f"{label}: " + ", ".join(filenames))
    query_plan = llm_input.get("query_plan") or {}
    plan_lines: list[str] = []
    if isinstance(query_plan, dict):
        facets = [
            str(item.get("query") or "").strip()
            for item in list(query_plan.get("facets") or [])
            if isinstance(item, dict) and str(item.get("query") or "").strip()
        ]
        if facets:
            plan_lines.append("Required facets: " + " | ".join(facets))
        output_hints = query_plan.get("output_hints") or {}
        if isinstance(output_hints, dict) and output_hints:
            plan_lines.append(
                "Output requirements: "
                + json.dumps(output_hints, ensure_ascii=False)
            )
    prompt_parts = [
        "You are a grounded BookRAG answerer.",
        *instructions,
        "When possible, mention node_id or page references already present in the evidence.",
        "Governed document scope:\n" + "\n".join(scope_lines) if scope_lines else "",
        "Query plan:\n" + "\n".join(plan_lines) if plan_lines else "",
        "Evidence:",
        "\n\n".join(evidence_lines) if evidence_lines else "(no evidence)",
    ]
    return "\n\n".join(part for part in prompt_parts if part)


def _extract_bookrag_answer_text(result: object) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        for key in ("text", "answer", "content", "output_text", "response"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(result, (list, tuple)):
        joined = "\n".join(str(item).strip() for item in result if str(item).strip())
        return joined.strip()
    return str(format_preview(result, max_chars=None)).strip()


def _build_bookrag_live_answer_or_raise(
    *,
    question: str,
    vector_store_name: str,
    llm_input: dict[str, object],
    similarity_result: object,
) -> dict[str, object]:
    if VectorStore is None:
        raise HTTPException(status_code=503, detail=f"VectorStore runtime is unavailable: {TERADATA_IMPORT_ERROR}")
    try:
        vector_store = VectorStore(vector_store_name)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"cannot open VectorStore('{vector_store_name}'): {ex}") from ex

    response_prompt = _build_bookrag_llm_prompt(llm_input)
    prepare_response_fn = getattr(vector_store, "prepare_response", None)
    if not callable(prepare_response_fn):
        raise HTTPException(status_code=500, detail=f"VectorStore.prepare_response is unavailable on '{vector_store_name}'.")
    try:
        try:
            ask_result = prepare_response_fn(
                similarity_results=similarity_result,
                question=question,
                prompt=response_prompt,
            )
        except TypeError:
            try:
                ask_result = prepare_response_fn(similarity_result, question, response_prompt)
            except TypeError:
                ask_result = prepare_response_fn(similarity_result, question=question)
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"VectorStore.prepare_response failed on '{vector_store_name}': {ex}") from ex

    answer_text = _extract_bookrag_answer_text(ask_result)
    if not answer_text:
        raise HTTPException(status_code=500, detail=f"VectorStore.prepare_response returned empty answer on '{vector_store_name}'.")
    citations = _build_bookrag_citations_from_llm_input(llm_input)
    return {
        "mode": "live",
        "model": "vectorstore.prepare_response",
        "grounded": bool(citations),
        "text": answer_text,
        "citations": citations,
    }


@router.get("/api/bookrag/schema")
async def api_bookrag_schema(
    request: Request,
    vector_store_name: str,
    schema_name: str | None = None,
):
    auth_context = _require_api_access(request)
    _ensure_api_runtime(request, auth_context)
    selected = str(vector_store_name or "").strip()
    if not selected:
        raise HTTPException(status_code=422, detail="vector_store_name is required")
    return {
        "api": "bookrag.schema",
        "version": BOOKRAG_API_VERSION,
        "vector_store_name": selected,
        "schema_name": _normalize_optional_text(schema_name),
        "contract": build_bookrag_relationship_contract(selected),
    }


@router.get(
    "/api/bookrag/retrieve",
    response_model=BookRAGRetrieveResponse,
    summary="Retrieve BookRAG evidence",
    description="Performs an authenticated BookRAG retrieval.",
)
async def api_bookrag_retrieve_get(
    request: Request,
    question: str | None = None,
    vector_store_name: str | None = None,
    schema_name: str | None = None,
    top_k: int = 5,
):
    schema_value = _normalize_optional_text(schema_name)
    top_k_value = _clamp_top_k(top_k)
    auth_context = _require_api_access(request)
    _ensure_api_runtime(request, auth_context)
    question_value, vector_store_value, evidence, _ = _retrieve_bookrag_evidence_or_raise(
        question=question,
        vector_store_name=vector_store_name,
        schema_name=schema_value,
        top_k=top_k_value,
    )
    evidence = _normalize_bookrag_evidence(evidence=evidence, top_k=top_k_value)
    assistant_message = _build_bookrag_chat_reply(evidence, vector_store_value)
    return {
        "meta": _build_api_meta(request=request, auth_context=auth_context, top_k=top_k_value),
        "question": question_value,
        "vector_store_name": vector_store_value,
        "schema_name": schema_value,
        "evidence": evidence,
        "assistant_message": assistant_message,
        "user_time": None,
        "assistant_time": None,
    }

@router.get("/api/bookrag/answer", response_model=BookRAGAnswerResponse)
async def api_bookrag_answer_get(
    request: Request,
    question: str | None = None,
    vector_store_name: str | None = None,
    schema_name: str | None = None,
    top_k: int = 5,
):
    schema_value = _normalize_optional_text(schema_name)
    top_k_value = _clamp_top_k(top_k)
    auth_context = _require_api_access(request)
    if not _normalize_optional_text(question) or not _normalize_optional_text(vector_store_name):
        raise HTTPException(status_code=422, detail="question and vector_store_name are required")
    _ensure_api_runtime(request, auth_context)
    question_value, vector_store_value, evidence, similarity_result = _retrieve_bookrag_evidence_or_raise(
        question=question,
        vector_store_name=vector_store_name,
        schema_name=schema_value,
        top_k=top_k_value,
        lock_final=True,
    )
    evidence = _normalize_bookrag_evidence(evidence=evidence, top_k=top_k_value)
    llm_input = _build_bookrag_llm_input(
        question=question_value,
        evidence=evidence,
        top_k=top_k_value,
        include_entities=True,
        include_mapping=True,
    )
    answer = _build_bookrag_live_answer_or_raise(
        question=question_value,
        vector_store_name=vector_store_value,
        llm_input=llm_input,
        similarity_result=similarity_result,
    )
    return {
        "meta": _build_api_meta(request=request, auth_context=auth_context, top_k=top_k_value),
        "question": question_value,
        "vector_store_name": vector_store_value,
        "schema_name": schema_value,
        "top_k": top_k_value,
        "evidence": evidence,
        "llm_input": llm_input,
        "answer": answer,
        "assistant_message": answer["text"],
        "user_time": None,
        "assistant_time": None,
    }


@router.post(
    "/api/bookrag/retrieve",
    response_model=BookRAGRetrieveResponse,
    summary="Retrieve BookRAG evidence",
)
async def api_bookrag_retrieve(request: Request, payload: BookRAGRetrieveRequest):
    auth_context = _require_api_access(request)
    _ensure_api_runtime(request, auth_context)

    schema_value = _normalize_optional_text(payload.schema_name)
    top_k_value = _clamp_top_k(payload.top_k)
    question, vector_store_name, evidence, _ = _retrieve_bookrag_evidence_or_raise(
        question=payload.question,
        vector_store_name=payload.vector_store_name,
        schema_name=schema_value,
        top_k=top_k_value,
    )
    evidence = _normalize_bookrag_evidence(evidence=evidence, top_k=top_k_value)

    assistant_message = _build_bookrag_chat_reply(evidence, vector_store_name)
    user_time = datetime.now().strftime("%H:%M")
    assistant_time = datetime.now().strftime("%H:%M")
    request.app.state.chat_history.append({
        "role": "user",
        "content": question,
        "time": user_time,
    })
    request.app.state.chat_history.append({
        "role": "assistant",
        "content": assistant_message,
        "time": assistant_time,
    })
    request.app.state.chat_history = request.app.state.chat_history[-80:]

    return {
        "meta": _build_api_meta(request=request, auth_context=auth_context, top_k=top_k_value),
        "question": question,
        "vector_store_name": vector_store_name,
        "schema_name": schema_value,
        "evidence": evidence,
        "assistant_message": assistant_message,
        "user_time": user_time,
        "assistant_time": assistant_time,
    }


@router.post("/api/bookrag/answer", response_model=BookRAGAnswerResponse)
async def api_bookrag_answer(request: Request, payload: BookRAGAnswerRequest):
    auth_context = _require_api_access(request)
    _ensure_api_runtime(request, auth_context)

    schema_value = _normalize_optional_text(payload.schema_name)
    top_k_value = _clamp_top_k(payload.top_k)
    question, vector_store_name, evidence, similarity_result = _retrieve_bookrag_evidence_or_raise(
        question=payload.question,
        vector_store_name=payload.vector_store_name,
        schema_name=schema_value,
        top_k=top_k_value,
        lock_final=True,
    )
    evidence = _normalize_bookrag_evidence(evidence=evidence, top_k=top_k_value)
    llm_input = _build_bookrag_llm_input(
        question=question,
        evidence=evidence,
        top_k=top_k_value,
        include_entities=bool(payload.include_entities),
        include_mapping=bool(payload.include_mapping),
    )
    answer = _build_bookrag_live_answer_or_raise(
        question=question,
        vector_store_name=vector_store_name,
        llm_input=llm_input,
        similarity_result=similarity_result,
    )

    user_time = datetime.now().strftime("%H:%M")
    assistant_time = datetime.now().strftime("%H:%M")
    request.app.state.chat_history.append({
        "role": "user",
        "content": question,
        "time": user_time,
    })
    request.app.state.chat_history.append({
        "role": "assistant",
        "content": answer["text"],
        "time": assistant_time,
    })
    request.app.state.chat_history = request.app.state.chat_history[-80:]

    return {
        "meta": _build_api_meta(request=request, auth_context=auth_context, top_k=top_k_value),
        "question": question,
        "vector_store_name": vector_store_name,
        "schema_name": schema_value,
        "top_k": top_k_value,
        "llm_input": llm_input,
        "answer": answer,
        "evidence": evidence,
        "assistant_message": answer["text"],
        "user_time": user_time,
        "assistant_time": assistant_time,
    }


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
