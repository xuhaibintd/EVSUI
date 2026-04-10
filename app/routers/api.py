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

@router.post("/api/bookrag/retrieve")
async def api_bookrag_retrieve(request: Request, payload: BookRAGRetrieveRequest):
    if not _is_logged_in(request, request.app):
        raise HTTPException(status_code=401, detail="Unauthorized")
    _activate_session_state(request, request.app)

    if VectorStore is None:
        raise HTTPException(status_code=503, detail=f"VectorStore runtime is unavailable: {TERADATA_IMPORT_ERROR}")
    if execute_sql is None:
        raise HTTPException(status_code=503, detail="teradataml.execute_sql is unavailable.")

    question = str(payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required.")

    vector_store_name = str(payload.vector_store_name or "").strip()
    if not vector_store_name:
        raise HTTPException(status_code=400, detail="vector_store_name is required.")

    try:
        vector_store = VectorStore(vector_store_name)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"cannot open VectorStore('{vector_store_name}'): {ex}") from ex

    try:
        try:
            similarity_result = vector_store.similarity_search(question=question)
        except TypeError:
            similarity_result = vector_store.similarity_search(question)
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"similarity_search failed on '{vector_store_name}': {ex}") from ex

    try:
        evidence = retrieve_bookrag_evidence(
            vector_store_name=vector_store_name,
            similarity_result=similarity_result,
            execute_sql_fn=execute_sql,
            schema_name=str(payload.schema_name).strip() or None,
        )
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"BookRAG evidence retrieval failed for '{vector_store_name}': {ex}") from ex

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
        "evidence": evidence,
        "assistant_message": assistant_message,
        "user_time": user_time,
        "assistant_time": assistant_time,
    }


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}

