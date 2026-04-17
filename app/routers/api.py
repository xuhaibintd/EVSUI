from __future__ import annotations

import hmac
import os
from typing import Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services.bookrag_retrieval import retrieve_bookrag_evidence
from app.teradata_runtime import TERADATA_IMPORT_ERROR, VectorStore, execute_sql
from app.web_support import _activate_session_state, _build_bookrag_chat_reply, _is_logged_in

router = APIRouter()


class BookRAGRetrieveRequest(BaseModel):
    question: str
    vector_store_name: str | None = None
    schema_name: str | None = None


class BookRAGAnswerRequest(BaseModel):
    question: str
    vector_store_name: str | None = None
    schema_name: str | None = None
    top_k: int = 5
    include_entities: bool = True
    include_mapping: bool = True


class BookRAGDummyEntity(BaseModel):
    entity_id: str
    name: str
    entity_type: str


class BookRAGDummyMapping(BaseModel):
    entity_id: str
    node_id: str
    section_node_id: str
    source_block_id: str
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
    source_block_id: str


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


class BookRAGEvidenceResponse(BaseModel):
    vector_store_name: str
    schema_name: str | None = None
    packages: list[dict[str, Any]]
    package_count: int
    similarity_row_count: int
    similarity_headers: list[str]
    similarity_preview: str
    evidence_text: str


class BookRAGRetrieveResponse(BaseModel):
    question: str
    vector_store_name: str
    schema_name: str | None = None
    evidence: BookRAGEvidenceResponse
    dummy_data: BookRAGDummyDataResponse
    assistant_message: str
    user_time: str | None = None
    assistant_time: str | None = None


def _external_api_token() -> str:
    return str(os.getenv("EVSUI_API_TOKEN", "")).strip()


def _has_valid_external_api_token(request: Request) -> bool:
    configured = _external_api_token()
    if not configured:
        return False

    bearer = str(request.headers.get("authorization", "")).strip()
    if bearer.lower().startswith("bearer "):
        token = bearer[7:].strip()
        if token and hmac.compare_digest(token, configured):
            return True

    api_key = str(request.headers.get("x-api-key", "")).strip()
    return bool(api_key) and hmac.compare_digest(api_key, configured)


def _require_api_access(request: Request) -> None:
    if _is_logged_in(request, request.app) or _has_valid_external_api_token(request):
        return
    raise HTTPException(status_code=401, detail="Unauthorized")


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
                "source_block_id": "block-demo-001",
                "page_start": 2,
                "page_end": 2,
            },
            {
                "entity_id": "ent-demo-period",
                "node_id": "node-demo-001",
                "section_node_id": "node-section-001",
                "source_block_id": "block-demo-001",
                "page_start": 2,
                "page_end": 2,
            },
            {
                "entity_id": "ent-demo-growth",
                "node_id": "node-demo-001",
                "section_node_id": "node-section-001",
                "source_block_id": "block-demo-001",
                "page_start": 2,
                "page_end": 2,
            },
            {
                "entity_id": "ent-demo-noninterest",
                "node_id": "node-demo-001",
                "section_node_id": "node-section-001",
                "source_block_id": "block-demo-001",
                "page_start": 2,
                "page_end": 3,
            },
            {
                "entity_id": "ent-demo-risk",
                "node_id": "node-demo-001",
                "section_node_id": "node-section-001",
                "source_block_id": "block-demo-001",
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
            "source_block_id": "block-demo-001",
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


def _build_bookrag_llm_input(
    *,
    question: str,
    evidence: dict[str, object] | None,
    top_k: int,
    include_entities: bool,
    include_mapping: bool,
) -> dict[str, object]:
    packages = list((evidence or {}).get("packages") or [])
    limited_packages = packages[:_clamp_top_k(top_k)]
    evidence_items: list[dict[str, object]] = []
    for package in limited_packages:
        match = package.get("match") or {}
        block = package.get("block") or {}
        section = package.get("section") or {}
        page_start = match.get("page_start") if match.get("page_start") is not None else section.get("page_start")
        page_end = match.get("page_end") if match.get("page_end") is not None else section.get("page_end")
        item: dict[str, object] = {
            "rank": package.get("rank"),
            "score": package.get("score"),
            "path": match.get("path") or section.get("path"),
            "title": match.get("title") or section.get("title"),
            "section_title": section.get("title"),
            "pages": [page_start, page_end],
            "content": match.get("content") or block.get("text") or "",
            "table_html": block.get("text_as_html"),
            "image_caption": block.get("image_caption"),
            "image_context": block.get("image_context"),
            "node_id": match.get("node_id"),
            "source_block_id": match.get("source_block_id"),
        }
        if include_entities:
            item["entities"] = package.get("entities") or []
        if include_mapping:
            item["mapping"] = package.get("mapping") or []
        evidence_items.append(item)

    return {
        "question": question,
        "instructions": [
            "与えられた evidence のみを根拠に回答すること。",
            "数値の傾向、収益構造、財政状態、リスク要因を優先して整理すること。",
            "根拠が弱い推測は避け、必要に応じて不確実性を明示すること。",
            "回答は日本語で簡潔にまとめること。",
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
            "source_block_id": item.get("source_block_id"),
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
    dummy: str | None = None,
):
    schema_value = str(schema_name).strip() or None
    has_runtime_inputs = any(value is not None for value in (question, vector_store_name, schema_name))
    if has_runtime_inputs:
        _require_api_access(request)
        _activate_session_state(request, request.app)
        question_value, vector_store_value, evidence = _retrieve_bookrag_evidence_or_raise(
            question=question,
            vector_store_name=vector_store_name,
            schema_name=schema_value,
        )
        assistant_message = _build_bookrag_chat_reply(evidence, vector_store_value)
        return {
            "question": question_value,
            "vector_store_name": vector_store_value,
            "schema_name": schema_value,
            "evidence": evidence,
            "dummy_data": _build_bookrag_dummy_data(
                question=question_value,
                vector_store_name=vector_store_value,
                schema_name=schema_value,
            ),
            "assistant_message": assistant_message,
            "user_time": None,
            "assistant_time": None,
        }

    question_value = "三菱UFJフィナンシャル・グループの2026年3月期第3四半期決算の要点を確認したい"
    vector_store_value = "dummy_vs"

    return {
        "question": question_value,
        "vector_store_name": vector_store_value,
        "schema_name": schema_value,
        "evidence": {
            "vector_store_name": vector_store_value,
            "schema_name": schema_value,
            "packages": [],
            "package_count": 0,
            "similarity_row_count": 0,
            "similarity_headers": [],
            "similarity_preview": "",
            "evidence_text": "",
        },
        "dummy_data": _build_bookrag_dummy_data(
            question=question_value,
            vector_store_name=vector_store_value,
            schema_name=schema_value,
        ),
        "assistant_message": "GET 接続確認用のダミー BookRAG 応答を返しました。",
        "user_time": None,
        "assistant_time": None,
    }

@router.get("/api/bookrag/answer")
async def api_bookrag_answer_get(
    request: Request,
    question: str | None = None,
    vector_store_name: str | None = None,
    schema_name: str | None = None,
    top_k: int = 5,
):
    schema_value = str(schema_name).strip() or None
    has_runtime_inputs = any(value is not None for value in (question, vector_store_name, schema_name))
    if has_runtime_inputs:
        _require_api_access(request)
        _activate_session_state(request, request.app)
        question_value, vector_store_value, evidence = _retrieve_bookrag_evidence_or_raise(
            question=question,
            vector_store_name=vector_store_name,
            schema_name=schema_value,
        )
        llm_input = _build_bookrag_llm_input(
            question=question_value,
            evidence=evidence,
            top_k=top_k,
            include_entities=True,
            include_mapping=True,
        )
        answer = _build_bookrag_dummy_answer(question=question_value, llm_input=llm_input)
        return {
            "question": question_value,
            "vector_store_name": vector_store_value,
            "schema_name": schema_value,
            "top_k": _clamp_top_k(top_k),
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
    dummy_evidence = {
        "vector_store_name": vector_store_value,
        "schema_name": schema_value,
        "packages": [
            {
                "rank": 1,
                "score": 0.987,
                "match": {
                    "node_id": dummy_data["sample_match"]["node_id"],
                    "title": dummy_data["sample_match"]["title"],
                    "content": dummy_data["sample_match"]["content"],
                    "path": dummy_data["sample_match"]["path"],
                    "page_start": dummy_data["sample_match"]["page_start"],
                    "page_end": dummy_data["sample_match"]["page_end"],
                    "source_block_id": dummy_data["sample_match"]["source_block_id"],
                },
                "section": {
                    "title": dummy_data["sample_match"]["title"],
                    "path": dummy_data["sample_match"]["path"],
                    "page_start": dummy_data["sample_match"]["page_start"],
                    "page_end": dummy_data["sample_match"]["page_end"],
                },
                "block": {
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
    }
    llm_input = _build_bookrag_llm_input(
        question=question_value,
        evidence=dummy_evidence,
        top_k=top_k,
        include_entities=True,
        include_mapping=True,
    )
    answer = _build_bookrag_dummy_answer(question=question_value, llm_input=llm_input)
    return {
        "question": question_value,
        "vector_store_name": vector_store_value,
        "schema_name": schema_value,
        "top_k": _clamp_top_k(top_k),
        "evidence": dummy_evidence,
        "llm_input": llm_input,
        "answer": answer,
        "assistant_message": answer["text"],
    }


@router.post(
    "/api/bookrag/retrieve",
    response_model=BookRAGRetrieveResponse,
    summary="Retrieve BookRAG evidence",
)
async def api_bookrag_retrieve(request: Request, payload: BookRAGRetrieveRequest):
    _require_api_access(request)
    _activate_session_state(request, request.app)

    schema_value = str(payload.schema_name).strip() or None
    question, vector_store_name, evidence = _retrieve_bookrag_evidence_or_raise(
        question=payload.question,
        vector_store_name=payload.vector_store_name,
        schema_name=schema_value,
    )

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
        "question": question,
        "vector_store_name": vector_store_name,
        "schema_name": schema_value,
        "evidence": evidence,
        "dummy_data": _build_bookrag_dummy_data(
            question=question,
            vector_store_name=vector_store_name,
            schema_name=schema_value,
        ),
        "assistant_message": assistant_message,
        "user_time": user_time,
        "assistant_time": assistant_time,
    }


@router.post("/api/bookrag/answer")
async def api_bookrag_answer(request: Request, payload: BookRAGAnswerRequest):
    _require_api_access(request)
    _activate_session_state(request, request.app)

    schema_value = str(payload.schema_name).strip() or None
    question, vector_store_name, evidence = _retrieve_bookrag_evidence_or_raise(
        question=payload.question,
        vector_store_name=payload.vector_store_name,
        schema_name=schema_value,
    )
    llm_input = _build_bookrag_llm_input(
        question=question,
        evidence=evidence,
        top_k=payload.top_k,
        include_entities=bool(payload.include_entities),
        include_mapping=bool(payload.include_mapping),
    )
    answer = _build_bookrag_dummy_answer(question=question, llm_input=llm_input)

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
        "question": question,
        "vector_store_name": vector_store_name,
        "schema_name": schema_value,
        "top_k": _clamp_top_k(payload.top_k),
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
