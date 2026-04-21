from __future__ import annotations

import hmac
import os
import uuid
from typing import Any
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.bookrag_retrieval import retrieve_bookrag_evidence
from app.teradata_runtime import TERADATA_IMPORT_ERROR, VectorStore, execute_sql
from app.utils.table_state import format_preview
from app.web_support import _activate_session_state, _build_bookrag_chat_reply, _is_logged_in

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


class BookRAGDummyEntity(BaseModel):
    entity_id: str
    name: str
    entity_type: str


class BookRAGDummyMapping(BaseModel):
    entity_id: str
    node_id: str
    section_node_id: str
    source_element_id: str
    page_start: int | None = None
    page_end: int | None = None


class BookRAGDummyMatch(BaseModel):
    node_id: str
    node_type: str
    title: str
    content: str
    path: str
    page_start: int | None = None
    page_end: int | None = None
    source_element_id: str


class BookRAGDummyDataResponse(BaseModel):
    status: str
    api: str
    version: str
    message: str
    dummy_date: str
    question_echo: str
    vector_store_name_echo: str
    schema_name_echo: str | None = None
    section_path: str
    sample_entities: list[BookRAGDummyEntity]
    sample_mapping: list[BookRAGDummyMapping]
    sample_match: BookRAGDummyMatch


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


class BookRAGSectionChainItemResponse(BaseModel):
    node_id: str | None = None
    title: str | None = None
    content: str | None = None
    path: str | None = None
    page_start: int | None = None
    page_end: int | None = None


class BookRAGEvidencePackageResponse(BaseModel):
    rank: int
    score: float | None = None
    schema_name: str | None = None
    tables: dict[str, str] = Field(default_factory=dict)
    match: BookRAGEvidenceMatchResponse
    section: BookRAGEvidenceSectionResponse | None = None
    section_chain: list[BookRAGSectionChainItemResponse] = Field(default_factory=list)
    block: BookRAGEvidenceBlockResponse | None = None


class BookRAGEvidenceResponse(BaseModel):
    vector_store_name: str
    schema_name: str | None = None
    packages: list[BookRAGEvidencePackageResponse] = Field(default_factory=list)
    package_count: int
    packages_total: int | None = None
    similarity_row_count: int
    similarity_headers: list[str] = Field(default_factory=list)
    similarity_preview: str
    evidence_text: str
    top_k_applied: int | None = None
    retrieval_source: str | None = None


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
    why_selected: str | None = None


class BookRAGLLMInputResponse(BaseModel):
    payload_version: str
    question: str
    document: BookRAGLLMDocumentResponse
    task: BookRAGLLMTaskResponse
    output_contract: BookRAGLLMOutputContractResponse
    instructions: list[str] = Field(default_factory=list)
    evidence: list[BookRAGLLMEvidenceItemResponse] = Field(default_factory=list)


class BookRAGAnswerCitationResponse(BaseModel):
    rank: int | None = None
    node_id: str | None = None
    source_element_id: str | None = None
    path: str | None = None
    page_start: int | None = None
    page_end: int | None = None


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
    dummy_data: BookRAGDummyDataResponse | None = None
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


def _external_api_token() -> str:
    return str(os.getenv("EVSUI_API_TOKEN", "")).strip()


def _resolve_external_token_context(request: Request) -> dict[str, str] | None:
    configured = _external_api_token()
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
        principal = str(request.cookies.get("evsui_user", "")).strip() or "browser_session"
        return {"mode": "session", "principal": principal}
    return _resolve_external_token_context(request)


def _require_api_access(request: Request) -> dict[str, str]:
    auth_context = _resolve_api_access_context(request)
    if auth_context is not None:
        return auth_context
    raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Bearer"})


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


def _build_bookrag_dummy_table_html() -> str:
    return (
        "<table>"
        "<thead><tr><th>観点</th><th>内容</th></tr></thead>"
        "<tbody>"
        "<tr><td>業績動向</td><td>経常収益・経常利益・純利益はいずれも前年比約3〜4%増で、前年の30%超成長から明確に減速。</td></tr>"
        "<tr><td>収益構造</td><td>貸出金利息は減少傾向、役務取引等収益とその他業務収益は増加し、非金利収益の比重が上昇。</td></tr>"
        "<tr><td>コスト動向</td><td>営業経費は増加傾向で、システム関連費用や人件費の増加が示唆される。</td></tr>"
        "<tr><td>財政状態</td><td>貸出金と預金は増加、借入金は減少しており、資金基盤は安定し調達構造も改善。</td></tr>"
        "<tr><td>主要リスク</td><td>信用リスク、貸倒引当金の見積り不確実性、ロシア・ウクライナ情勢、各国通商政策、金融・物価動向。</td></tr>"
        "</tbody>"
        "</table>"
    )


def _build_bookrag_dummy_data(*, question: str, vector_store_name: str, schema_name: str | None) -> dict[str, object]:
    return {
        "status": "dummy",
        "api": "bookrag.retrieve",
        "version": "dummy-v1",
        "message": "外部システムとの接続確認およびレスポンス項目の識別確認用に返却するダミー応答です。",
        "dummy_date": "2099-12-31",
        "question_echo": question,
        "vector_store_name_echo": vector_store_name,
        "schema_name_echo": schema_name,
        "section_path": "2026年3月期第3四半期決算短信 > 総括 > 業績の安定成長と収益構造の変化",
        "sample_entities": [
            {"entity_id": "ent-demo-org", "name": "株式会社三菱UFJフィナンシャル・グループ", "entity_type": "ORGANIZATION"},
            {"entity_id": "ent-demo-period", "name": "2026年3月期第3四半期", "entity_type": "DATE"},
            {"entity_id": "ent-demo-growth", "name": "前年比約3〜4%増", "entity_type": "FINANCIAL_METRIC"},
            {"entity_id": "ent-demo-noninterest", "name": "非金利収益", "entity_type": "BUSINESS_CATEGORY"},
            {"entity_id": "ent-demo-risk", "name": "信用リスク", "entity_type": "RISK_FACTOR"},
        ],
        "sample_mapping": [
            {
                "entity_id": "ent-demo-org",
                "node_id": "node-demo-001",
                "section_node_id": "node-section-001",
                "source_element_id": "block-demo-001",
                "page_start": 2,
                "page_end": 2,
            },
            {
                "entity_id": "ent-demo-period",
                "node_id": "node-demo-001",
                "section_node_id": "node-section-001",
                "source_element_id": "block-demo-001",
                "page_start": 2,
                "page_end": 2,
            },
            {
                "entity_id": "ent-demo-growth",
                "node_id": "node-demo-001",
                "section_node_id": "node-section-001",
                "source_element_id": "block-demo-001",
                "page_start": 2,
                "page_end": 2,
            },
            {
                "entity_id": "ent-demo-noninterest",
                "node_id": "node-demo-001",
                "section_node_id": "node-section-001",
                "source_element_id": "block-demo-001",
                "page_start": 2,
                "page_end": 3,
            },
            {
                "entity_id": "ent-demo-risk",
                "node_id": "node-demo-001",
                "section_node_id": "node-section-001",
                "source_element_id": "block-demo-001",
                "page_start": 4,
                "page_end": 4,
            },
        ],
        "sample_match": {
            "node_id": "node-demo-001",
            "node_type": "text",
            "title": "総括",
            "content": '【概要】\n三菱UFJフィナンシャル・グループの2026年3月期第3四半期決算は、増収増益を維持しているものの、前年と比べると成長率は大きく鈍化しており、高成長局面から安定成長局面への移行が見られる。\n\n【業績動向】\n経常収益、経常利益、純利益はいずれも前年比で約3〜4%増加した一方、前年は30%以上の高成長であり、成長スピードは明確に減速している。\n\n【収益構造の変化】\n貸出金利息は減少傾向にあり、役務取引等収益およびその他業務収益が増加している。従来の利ざや中心から、非金利収益の比重が高まる構造変化が進んでいる。\n\n【コスト・財政状態・リスク】\n営業経費は増加傾向で、システム関連費用や人件費の増加が示唆される。貸出金残高と預金は増加し、借入金は減少している。今後の業績は信用リスク、貸倒引当金の見積り不確実性、ロシア・ウクライナ情勢、各国の通商政策、金融・物価動向などのマクロ環境に強く依存する。',
            "path": "2026年3月期第3四半期決算短信 > 総括 > 業績の安定成長と収益構造の変化",
            "page_start": 2,
            "page_end": 4,
            "source_element_id": "block-demo-001",
        },
    }

def _retrieve_bookrag_evidence_or_raise(*, question: str, vector_store_name: str, schema_name: str | None):
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
        try:
            similarity_result = vector_store.similarity_search(question=question_value)
        except TypeError:
            similarity_result = vector_store.similarity_search(question_value)
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"similarity_search failed on '{vector_store_value}': {ex}") from ex

    try:
        evidence = retrieve_bookrag_evidence(
            vector_store_name=vector_store_value,
            similarity_result=similarity_result,
            execute_sql_fn=execute_sql,
            schema_name=schema_name,
        )
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"BookRAG evidence retrieval failed for '{vector_store_value}': {ex}") from ex

    return question_value, vector_store_value, evidence


def _clamp_top_k(raw: int | None, *, default: int = 5, minimum: int = 1, maximum: int = 20) -> int:
    try:
        value = int(raw if raw is not None else default)
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


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
    payload.setdefault("evidence_text", "")
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

    evidence_items: list[dict[str, object]] = []
    for package in limited_packages:
        match = package.get("match") or {}
        block = package.get("block") or {}
        section = package.get("section") or {}
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
        }
        if include_entities:
            item["entities"] = package.get("entities") or []
        if include_mapping:
            item["mapping"] = package.get("mapping") or []
        evidence_items.append(item)

    return {
        "payload_version": "bookrag-llm-payload-v1",
        "question": question,
        "document": {
            "doc_id": payload.get("doc_id") or first_match.get("doc_id"),
            "vector_store_name": payload.get("vector_store_name"),
            "schema_name": payload.get("schema_name"),
            "filename": payload.get("filename"),
            "source_file": payload.get("source_file"),
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
            "Answer only from the supplied evidence.",
            "Separate observed facts from inference and do not invent missing support.",
            "Attach rank-based citations to material conclusions.",
            "Prioritize performance, revenue structure, financial position, and risk factors.",
            "Keep the response concise and JSON-ready for external API consumers.",
        ],
        "evidence": evidence_items,
    }


def _build_bookrag_dummy_answer(*, question: str, llm_input: dict[str, object]) -> dict[str, object]:
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

    if evidence_items:
        first = evidence_items[0]
        answer_text = (
            f"質問「{question}」に対するダミー回答です。"
            "三菱UFJフィナンシャル・グループの2026年3月期第3四半期決算は増収増益を維持していますが、"
            "前年比成長率は約3〜4%まで鈍化しており、高成長フェーズから安定成長フェーズへの移行が示唆されます。"
            "収益構造は貸出金利息中心から、役務取引等収益やその他業務収益など非金利収益の比重が高まる方向へ変化しています。"
            "営業経費の増加、信用リスク、貸倒引当金の見積り不確実性、マクロ環境の変動が今後の主要な注目点です。"
            f"主な参照セクションは「{first.get('title') or first.get('section_title') or '総括'}」です。"
        )
    else:
        answer_text = (
            f"質問「{question}」に対するダミー回答です。参照可能な evidence が 0 件のため、"
            "三菱UFJフィナンシャル・グループの2026年3月期第3四半期決算に関する要約は生成せず、"
            "接続確認用の空レスポンスのみを返しています。"
        )

    return {
        "mode": "dummy",
        "model": "bookrag-answer-dummy-v1",
        "grounded": bool(citations),
        "text": answer_text,
        "citations": citations,
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
        if len(content) > 1800:
            content = content[:1800] + " ..."
        evidence_lines.append(f"[{item.get('rank')}] node_id={node_id} title={title}{page_label}\n{content}")
    prompt_parts = [
        "You are a grounded BookRAG answerer.",
        *instructions,
        "When possible, mention node_id or page references already present in the evidence.",
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


def _build_bookrag_live_answer_or_raise(*, question: str, vector_store_name: str, llm_input: dict[str, object]) -> dict[str, object]:
    if VectorStore is None:
        raise HTTPException(status_code=503, detail=f"VectorStore runtime is unavailable: {TERADATA_IMPORT_ERROR}")
    try:
        vector_store = VectorStore(vector_store_name)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"cannot open VectorStore('{vector_store_name}'): {ex}") from ex

    ask_prompt = _build_bookrag_llm_prompt(llm_input)
    ask_fn = getattr(vector_store, "ask", None)
    if not callable(ask_fn):
        raise HTTPException(status_code=500, detail=f"VectorStore.ask is unavailable on '{vector_store_name}'.")
    try:
        try:
            ask_result = ask_fn(question=question, prompt=ask_prompt)
        except TypeError:
            try:
                ask_result = ask_fn(question, ask_prompt)
            except TypeError:
                try:
                    ask_result = ask_fn(question=question)
                except TypeError:
                    ask_result = ask_fn(question)
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"VectorStore.ask failed on '{vector_store_name}': {ex}") from ex

    answer_text = _extract_bookrag_answer_text(ask_result)
    if not answer_text:
        raise HTTPException(status_code=500, detail=f"VectorStore.ask returned empty answer on '{vector_store_name}'.")
    citations = _build_bookrag_citations_from_llm_input(llm_input)
    return {
        "mode": "live",
        "model": "vectorstore.ask",
        "grounded": bool(citations),
        "text": answer_text,
        "citations": citations,
    }


@router.get(
    "/api/bookrag/retrieve",
    response_model=BookRAGRetrieveResponse,
    summary="Retrieve BookRAG dummy or evidence payload",
    description=(
        "Returns a dummy connectivity payload when called without query parameters. "
        "When question/vector_store_name inputs are supplied, performs a real retrieval."
    ),
)
async def api_bookrag_retrieve_get(
    request: Request,
    question: str | None = None,
    vector_store_name: str | None = None,
    schema_name: str | None = None,
    top_k: int = 5,
    dummy: str | None = None,
):
    schema_value = str(schema_name).strip() or None
    top_k_value = _clamp_top_k(top_k)
    has_runtime_inputs = any(value is not None for value in (question, vector_store_name, schema_name))
    if has_runtime_inputs:
        auth_context = _require_api_access(request)
        if auth_context.get("mode") == "session":
            _activate_session_state(request, request.app)
        question_value, vector_store_value, evidence = _retrieve_bookrag_evidence_or_raise(
            question=question,
            vector_store_name=vector_store_name,
            schema_name=schema_value,
        )
        evidence = _normalize_bookrag_evidence(evidence=evidence, top_k=top_k_value)
        assistant_message = _build_bookrag_chat_reply(evidence, vector_store_value)
        return {
            "meta": _build_api_meta(request=request, auth_context=auth_context, top_k=top_k_value),
            "question": question_value,
            "vector_store_name": vector_store_value,
            "schema_name": schema_value,
            "evidence": evidence,
            "dummy_data": None,
            "assistant_message": assistant_message,
            "user_time": None,
            "assistant_time": None,
        }

    question_value = "三菱UFJフィナンシャル・グループの2026年3月期第3四半期決算の要点を確認したい"
    vector_store_value = "dummy_vs"

    return {
        "meta": _build_api_meta(request=request, auth_context=None, top_k=top_k_value),
        "question": question_value,
        "vector_store_name": vector_store_value,
        "schema_name": schema_value,
        "evidence": _normalize_bookrag_evidence(
            evidence={
                "vector_store_name": vector_store_value,
                "schema_name": schema_value,
                "packages": [],
                "package_count": 0,
                "similarity_row_count": 0,
                "similarity_headers": [],
                "similarity_preview": "",
                "evidence_text": "",
            },
            top_k=top_k_value,
        ),
        "dummy_data": _build_bookrag_dummy_data(
            question=question_value,
            vector_store_name=vector_store_value,
            schema_name=schema_value,
        ),
        "assistant_message": "GET 接続確認用のダミー BookRAG 応答を返しました。",
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
    schema_value = str(schema_name).strip() or None
    top_k_value = _clamp_top_k(top_k)
    has_runtime_inputs = any(value is not None for value in (question, vector_store_name, schema_name))
    if has_runtime_inputs:
        auth_context = _require_api_access(request)
        if auth_context.get("mode") == "session":
            _activate_session_state(request, request.app)
        question_value, vector_store_value, evidence = _retrieve_bookrag_evidence_or_raise(
            question=question,
            vector_store_name=vector_store_name,
            schema_name=schema_value,
        )
        evidence = _normalize_bookrag_evidence(evidence=evidence, top_k=top_k_value)
        llm_input = _build_bookrag_llm_input(
            question=question_value,
            evidence=evidence,
            top_k=top_k_value,
            include_entities=True,
            include_mapping=True,
        )
        answer = _build_bookrag_live_answer_or_raise(question=question_value, vector_store_name=vector_store_value, llm_input=llm_input)
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

    question_value = "三菱UFJフィナンシャル・グループの2026年3月期第3四半期決算の要点は？"
    vector_store_value = "dummy_vs"
    dummy_data = _build_bookrag_dummy_data(
        question=question_value,
        vector_store_name=vector_store_value,
        schema_name=schema_value,
    )
    dummy_evidence = _normalize_bookrag_evidence(
        evidence={
            "doc_id": "doc-demo-001",
            "vector_store_name": vector_store_value,
            "schema_name": schema_value,
            "filename": "summary2512_ja.pdf",
            "source_file": "uploads/bookrag_raw_stage/bookrag_20260418_173347/summary2512_ja_92516ea5f4594ebaa12d264b92da860e.json",
            "document_type": "quarterly_earnings_report",
            "language": "ja",
            "reporting_period": "2025-04-01 to 2025-12-31",
            "packages": [
                {
                    "rank": 1,
                    "score": 0.987,
                    "match": {
                        "node_id": dummy_data["sample_match"]["node_id"],
                        "doc_id": "doc-demo-001",
                        "node_type": dummy_data["sample_match"]["node_type"],
                        "title": dummy_data["sample_match"]["title"],
                        "content": dummy_data["sample_match"]["content"],
                        "path": dummy_data["sample_match"]["path"],
                        "page_start": dummy_data["sample_match"]["page_start"],
                        "page_end": dummy_data["sample_match"]["page_end"],
                        "source_element_id": dummy_data["sample_match"]["source_element_id"],
                    },
                    "section": {
                        "title": dummy_data["sample_match"]["title"],
                        "path": dummy_data["sample_match"]["path"],
                        "page_start": dummy_data["sample_match"]["page_start"],
                        "page_end": dummy_data["sample_match"]["page_end"],
                    },
                    "block": {
                        "type": "Table",
                        "text": dummy_data["sample_match"]["content"],
                        "text_as_html": _build_bookrag_dummy_table_html(),
                        "image_caption": None,
                        "image_context": None,
                    },
                    "entities": dummy_data["sample_entities"],
                    "mapping": dummy_data["sample_mapping"],
                }
            ],
            "package_count": 1,
            "similarity_row_count": 1,
            "similarity_headers": [],
            "similarity_preview": "dummy preview",
            "evidence_text": dummy_data["sample_match"]["content"],
        },
        top_k=top_k_value,
    )
    llm_input = _build_bookrag_llm_input(
        question=question_value,
        evidence=dummy_evidence,
        top_k=top_k_value,
        include_entities=True,
        include_mapping=True,
    )
    answer = _build_bookrag_dummy_answer(question=question_value, llm_input=llm_input)
    return {
        "meta": _build_api_meta(request=request, auth_context=None, top_k=top_k_value),
        "question": question_value,
        "vector_store_name": vector_store_value,
        "schema_name": schema_value,
        "top_k": top_k_value,
        "evidence": dummy_evidence,
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
    if auth_context.get("mode") == "session":
        _activate_session_state(request, request.app)

    schema_value = str(payload.schema_name).strip() or None
    top_k_value = _clamp_top_k(payload.top_k)
    question, vector_store_name, evidence = _retrieve_bookrag_evidence_or_raise(
        question=payload.question,
        vector_store_name=payload.vector_store_name,
        schema_name=schema_value,
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
        "dummy_data": None,
        "assistant_message": assistant_message,
        "user_time": user_time,
        "assistant_time": assistant_time,
    }


@router.post("/api/bookrag/answer", response_model=BookRAGAnswerResponse)
async def api_bookrag_answer(request: Request, payload: BookRAGAnswerRequest):
    auth_context = _require_api_access(request)
    if auth_context.get("mode") == "session":
        _activate_session_state(request, request.app)

    schema_value = str(payload.schema_name).strip() or None
    top_k_value = _clamp_top_k(payload.top_k)
    question, vector_store_name, evidence = _retrieve_bookrag_evidence_or_raise(
        question=payload.question,
        vector_store_name=payload.vector_store_name,
        schema_name=schema_value,
    )
    evidence = _normalize_bookrag_evidence(evidence=evidence, top_k=top_k_value)
    llm_input = _build_bookrag_llm_input(
        question=question,
        evidence=evidence,
        top_k=top_k_value,
        include_entities=bool(payload.include_entities),
        include_mapping=bool(payload.include_mapping),
    )
    answer = _build_bookrag_live_answer_or_raise(question=question, vector_store_name=vector_store_name, llm_input=llm_input)

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
