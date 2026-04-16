from __future__ import annotations

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
        "section_path": "2026年3月期第3四半期決算短信 > 1. 2026年3月期第3四半期の連結業績 > （1）連結経営成績（累計）",
        "sample_entities": [
            {"entity_id": "ent-demo-org", "name": "株式会社三菱UFJフィナンシャル・グループ", "entity_type": "ORGANIZATION"},
            {"entity_id": "ent-demo-period", "name": "2026年3月期第3四半期", "entity_type": "DATE"},
            {"entity_id": "ent-demo-metric", "name": "親会社株主に帰属する四半期純利益", "entity_type": "FINANCIAL_METRIC"},
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
                "entity_id": "ent-demo-metric",
                "node_id": "node-demo-001",
                "section_node_id": "node-section-001",
                "source_block_id": "block-demo-001",
                "page_start": 2,
                "page_end": 2,
            },
        ],
        "sample_match": {
            "node_id": "node-demo-001",
            "node_type": "text",
            "title": "（1）連結経営成績（累計）",
            "content": "株式会社三菱UFJフィナンシャル・グループの2026年3月期第3四半期累計期間における連結業績の要約を示すダミー本文です。親会社株主に帰属する四半期純利益、経常利益、連結業務純益などの主要指標を格納する想定です。",
            "path": "2026年3月期第3四半期決算短信 > 1. 2026年3月期第3四半期の連結業績 > （1）連結経営成績（累計）",
            "page_start": 2,
            "page_end": 2,
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
            "????????????????????????",
            "??????????????????????????",
            "????????????????????????",
            "???????????????????",
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
            f"???????????{question}??????"
            f"????????{first.get('title') or first.get('section_title') or '???????'}????"
            "???????? llm_input ????? LLM ???????????????"
        )
    else:
        answer_text = (
            f"???????????{question}?????????? 0 ????"
            "??????retrieve ??? 0 ???????????????????????"
        )

    return {
        "mode": "dummy",
        "model": "bookrag-answer-dummy-v1",
        "grounded": bool(citations),
        "text": answer_text,
        "citations": citations,
    }


@router.get("/api/bookrag/retrieve")
async def api_bookrag_retrieve_get(
    request: Request,
    question: str = "第3四半期決算の要点を確認したい",
    vector_store_name: str = "dummy_vs",
    schema_name: str | None = None,
):
    if not _is_logged_in(request, request.app):
        raise HTTPException(status_code=401, detail="Unauthorized")
    _activate_session_state(request, request.app)

    question_value = str(question or "").strip() or "第3四半期決算の要点を確認したい"
    vector_store_value = str(vector_store_name or "").strip() or "dummy_vs"
    schema_value = str(schema_name).strip() or None

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
    question: str = "?3??????????????",
    vector_store_name: str = "dummy_vs",
    schema_name: str | None = None,
    top_k: int = 5,
):
    if not _is_logged_in(request, request.app):
        raise HTTPException(status_code=401, detail="Unauthorized")
    _activate_session_state(request, request.app)

    question_value = str(question or "").strip() or "?3??????????????"
    vector_store_value = str(vector_store_name or "").strip() or "dummy_vs"
    schema_value = str(schema_name).strip() or None
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
                    "text_as_html": None,
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


@router.post("/api/bookrag/retrieve")
async def api_bookrag_retrieve(request: Request, payload: BookRAGRetrieveRequest):
    if not _is_logged_in(request, request.app):
        raise HTTPException(status_code=401, detail="Unauthorized")
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
    if not _is_logged_in(request, request.app):
        raise HTTPException(status_code=401, detail="Unauthorized")
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

