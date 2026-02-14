from __future__ import annotations

import json
import hashlib
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

try:
    from teradataml import create_context, remove_context
    from teradatagenai import VSManager, set_auth_token
except Exception as ex:  # pragma: no cover - dependency/runtime specific.
    create_context = None
    remove_context = None
    VSManager = None
    set_auth_token = None
    TERADATA_IMPORT_ERROR = str(ex)
else:
    TERADATA_IMPORT_ERROR = ""

try:
    from teradatagenai import VectorStore
except Exception:
    VectorStore = None

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = PROJECT_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DOCUMENT_UPLOAD_DIR = UPLOAD_DIR / "documents"
DOCUMENT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PEM_UPLOAD_DIR = UPLOAD_DIR / "pem"
PEM_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
VS_BASICS_DIR = PROJECT_DIR.parent / "VS_Basics_Full_Kit"
DEFAULT_PAT_TOKEN = "<redacted-pat-token>"
logger = logging.getLogger("evsui.connect")
logger.setLevel(logging.INFO)


CREATE_FIELDS: list[dict[str, str]] = [
    {"name": "description", "label": "Description", "group": "Notebook Core", "kind": "text", "placeholder": "Vector store description"},
    {"name": "target_database", "label": "Target Database", "group": "Notebook Core", "kind": "text", "placeholder": "oaf"},
    {"name": "object_names", "label": "Object Names", "group": "Notebook Core", "kind": "textarea", "placeholder": "TokioMarine_pdf_test"},
    {"name": "data_columns", "label": "Data Columns", "group": "Notebook Core", "kind": "text", "placeholder": "chunks"},
    {"name": "vector_column", "label": "Vector Column", "group": "Notebook Core", "kind": "text", "placeholder": "Embedding"},
    {"name": "document_files", "label": "Document Files", "group": "Notebook Core", "kind": "textarea", "placeholder": "Leave empty to use uploaded files"},
    {"name": "chunk_size", "label": "Chunk Size", "group": "Notebook Core", "kind": "number", "placeholder": "500"},
    {"name": "optimized_chunking", "label": "Optimized Chunking", "group": "Notebook Core", "kind": "select", "placeholder": "false,true"},
    {"name": "embeddings_model", "label": "Embeddings Model", "group": "Notebook Core", "kind": "select", "placeholder": "amazon.titan-embed-text-v1,amazon.titan-embed-image-v1,amazon.titan-embed-text-v2:0,text-embedding-ada-002,text-embedding-3-small,text-embedding-3-large"},
    {"name": "search_algorithm", "label": "Search Algorithm", "group": "Notebook Core", "kind": "select", "placeholder": "VECTORDISTANCE,KMEANS,HNSW"},
    {"name": "top_k", "label": "Top K", "group": "Notebook Core", "kind": "number", "placeholder": "5"},
    {"name": "metric", "label": "Metric", "group": "Embedding & Search", "kind": "select", "placeholder": "COSINE,EUCLIDEAN,DOTPRODUCT"},
    {"name": "search_threshold", "label": "Search Threshold", "group": "Embedding & Search", "kind": "text", "placeholder": "0.75"},
    {"name": "search_numcluster", "label": "Search Num Cluster", "group": "Embedding & Search", "kind": "number", "placeholder": "4"},
    {"name": "prompt", "label": "Prompt", "group": "Embedding & Search", "kind": "textarea", "placeholder": "Prompt used by ask/prepare_response"},
    {"name": "chat_completion_model", "label": "Chat Completion Model", "group": "Embedding & Search", "kind": "text", "placeholder": "gpt-4o-mini"},
    {"name": "chat_completion_max_tokens", "label": "Chat Completion Max Tokens", "group": "Embedding & Search", "kind": "number", "placeholder": "512"},
    {"name": "initial_delay_ms", "label": "Initial Delay (ms)", "group": "Embedding & Search", "kind": "number", "placeholder": "5000"},
    {"name": "delay_max_retries", "label": "Delay Max Retries", "group": "Embedding & Search", "kind": "number", "placeholder": "12"},
    {"name": "delay_exp_base", "label": "Delay Exponential Base", "group": "Embedding & Search", "kind": "number", "placeholder": "1"},
    {"name": "delay_jitter", "label": "Delay Jitter", "group": "Embedding & Search", "kind": "select", "placeholder": "false,true"},
    {"name": "ignore_embedding_errors", "label": "Ignore Embedding Errors", "group": "Embedding & Search", "kind": "select", "placeholder": "false,true"},
    {"name": "batch", "label": "Batch", "group": "Embedding & Search", "kind": "select", "placeholder": "false,true"},
    {"name": "embeddings_dims", "label": "Embeddings Dims", "group": "Embedding & Search", "kind": "number", "placeholder": "1536"},
    {"name": "key_columns", "label": "Key Columns", "group": "Extended Create Params", "kind": "text", "placeholder": "id, document_id"},
    {"name": "header_height", "label": "Header Height", "group": "Extended Create Params", "kind": "number", "placeholder": "0"},
    {"name": "footer_height", "label": "Footer Height", "group": "Extended Create Params", "kind": "number", "placeholder": "0"},
    {"name": "initial_centroids_method", "label": "Initial Centroids Method", "group": "HNSW / KMEANS Params", "kind": "select", "placeholder": "RANDOM,KMEANS++"},
    {"name": "train_numcluster", "label": "Train Num Cluster", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "8"},
    {"name": "max_iternum", "label": "Max Iter Num", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "10"},
    {"name": "stop_threshold", "label": "Stop Threshold", "group": "HNSW / KMEANS Params", "kind": "text", "placeholder": "0.0395"},
    {"name": "seed", "label": "Seed", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "10"},
    {"name": "num_init", "label": "Num Init", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "1"},
    {"name": "ef_search", "label": "EF Search", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "64"},
    {"name": "num_layer", "label": "Num Layer", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "2"},
    {"name": "ef_construction", "label": "EF Construction", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "64"},
    {"name": "num_connpernode", "label": "Num Conn Per Node", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "32"},
    {"name": "maxnum_connpernode", "label": "Max Num Conn Per Node", "group": "HNSW / KMEANS Params", "kind": "number", "placeholder": "32"},
    {"name": "apply_heuristics", "label": "Apply Heuristics", "group": "HNSW / KMEANS Params", "kind": "select", "placeholder": "true,false"},
    {"name": "include_objects", "label": "Include Objects", "group": "Metadata / RAG Params", "kind": "textarea", "placeholder": "db1.*, sales.*"},
    {"name": "exclude_objects", "label": "Exclude Objects", "group": "Metadata / RAG Params", "kind": "textarea", "placeholder": "tmp.*, backup.*"},
    {"name": "include_patterns", "label": "Include Patterns", "group": "Metadata / RAG Params", "kind": "textarea", "placeholder": "finance_pattern"},
    {"name": "exclude_patterns", "label": "Exclude Patterns", "group": "Metadata / RAG Params", "kind": "textarea", "placeholder": "raw_pattern"},
    {"name": "sample_size", "label": "Sample Size", "group": "Metadata / RAG Params", "kind": "number", "placeholder": "1000"},
    {"name": "rerank_weight", "label": "Rerank Weight", "group": "Metadata / RAG Params", "kind": "text", "placeholder": "0.5"},
    {"name": "relevance_top_k", "label": "Relevance Top K", "group": "Metadata / RAG Params", "kind": "number", "placeholder": "5"},
    {"name": "relevance_search_threshold", "label": "Relevance Search Threshold", "group": "Metadata / RAG Params", "kind": "text", "placeholder": "0.2"},
]

BOOL_FIELDS = {"optimized_chunking", "delay_jitter", "ignore_embedding_errors", "batch", "apply_heuristics"}
CREATE_FIELD_MAX_LEN = 50
ALLOWED_VALIDATION_TARGETS = {"vectorstore.ask", "vectorstore.similarity_search"}
INT_FIELDS = {
    "chunk_size",
    "header_height",
    "footer_height",
    "embeddings_dims",
    "initial_delay_ms",
    "delay_max_retries",
    "delay_exp_base",
    "top_k",
    "search_numcluster",
    "relevance_top_k",
    "chat_completion_max_tokens",
    "train_numcluster",
    "max_iternum",
    "seed",
    "num_init",
    "ef_search",
    "num_layer",
    "ef_construction",
    "num_connpernode",
    "maxnum_connpernode",
    "sample_size",
}
FLOAT_FIELDS = {"search_threshold", "rerank_weight", "relevance_search_threshold", "stop_threshold"}
CSV_FIELDS = {
    "object_names",
    "key_columns",
    "data_columns",
    "document_files",
    "include_objects",
    "exclude_objects",
    "include_patterns",
    "exclude_patterns",
}


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _group_create_fields() -> list[tuple[str, list[dict[str, str]]]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for field in CREATE_FIELDS:
        groups.setdefault(field["group"], []).append(field)
    return list(groups.items())


def _split_csv(value: str) -> list[str]:
    return [chunk.strip() for chunk in value.replace("\n", ",").split(",") if chunk.strip()]


def _coerce_create_param(name: str, raw: str):
    if name in CSV_FIELDS:
        chunks = _split_csv(raw)
        if len(chunks) == 1:
            return chunks[0]
        return chunks
    if name in BOOL_FIELDS:
        return raw.lower() == "true"
    if name in INT_FIELDS:
        return int(raw)
    if name in FLOAT_FIELDS:
        return float(raw)
    return raw


def _derive_base_url(ues_url: str) -> str:
    src = ues_url.strip()
    # strip off the trailing /open-analytics
    if src.endswith("/open-analytics"):
        return src[:-15]
    return src


def _save_pem_upload(pem_file: UploadFile) -> str:
    safe_name = Path(pem_file.filename or "uploaded.pem").name
    target = PEM_UPLOAD_DIR / safe_name
    payload = pem_file.file.read()
    target.write_bytes(payload)
    return str(target.relative_to(PROJECT_DIR))


def _latest_uploaded_pem_relative() -> str:
    try:
        files = [item for item in PEM_UPLOAD_DIR.iterdir() if item.is_file()]
    except FileNotFoundError:
        return ""
    if not files:
        return ""
    latest = max(files, key=lambda item: item.stat().st_mtime)
    return str(latest.relative_to(PROJECT_DIR))


def _collect_upload_files(form_data, field_name: str = "files") -> list[UploadFile]:
    files: list[UploadFile] = []
    for key, value in form_data.multi_items():
        if key != field_name:
            continue
        # Request.form() returns Starlette UploadFile objects; rely on duck-typing
        # instead of strict isinstance(FastAPI UploadFile).
        if hasattr(value, "filename") and hasattr(value, "read"):
            files.append(value)
    return files


async def _save_document_uploads(files: list[UploadFile]) -> tuple[list[dict], list[str]]:
    uploaded_items: list[dict] = []
    notices: list[str] = []
    for file in files:
        if not file.filename:
            continue

        safe_name = Path(file.filename).name
        if not safe_name:
            continue

        target = DOCUMENT_UPLOAD_DIR / safe_name
        relative_path = str(target.relative_to(PROJECT_DIR))
        existed_before = target.exists()

        payload = await file.read()
        target.write_bytes(payload)
        uploaded_items.append(
            {
                "name": safe_name,
                "saved_path": relative_path,
                "size": len(payload),
                "time": _now_ts(),
                "status": "overwritten" if existed_before else "uploaded",
            }
        )

    return uploaded_items, notices


def _resolve_path_hint(path_hint: str) -> str:
    hint = path_hint.strip()
    if not hint:
        return ""
    candidate = Path(hint)
    candidates = []
    if candidate.is_absolute():
        candidates.append(candidate)
    else:
        candidates.append(PROJECT_DIR / candidate)
        candidates.append(PROJECT_DIR.parent / candidate)
        candidates.append(VS_BASICS_DIR / candidate)
    for item in candidates:
        if item.exists():
            return str(item.resolve())
    return hint


def _normalize_pem_filename_for_auth(resolved_pem_path: str) -> str:
    if not resolved_pem_path:
        return resolved_pem_path
    path_obj = Path(resolved_pem_path)
    if not path_obj.exists() or not path_obj.is_file():
        return resolved_pem_path
    match = re.match(r"^\d{8}_\d{6}_\d+_(.+)$", path_obj.name)
    if not match:
        return resolved_pem_path
    normalized_name = match.group(1)
    normalized_path = path_obj.parent / normalized_name
    if normalized_path.exists() and normalized_path.is_file():
        return str(normalized_path.resolve())
    shutil.copyfile(path_obj, normalized_path)
    return str(normalized_path.resolve())


def _cleanup_context() -> dict[str, str]:
    result = {
        "vs_disconnect": "skipped (VSManager unavailable)",
        "remove_context": "skipped (remove_context unavailable)",
    }
    if VSManager is not None:
        try:
            VSManager.disconnect(raise_error=False)
            result["vs_disconnect"] = "called"
        except Exception:
            result["vs_disconnect"] = "error"
    if remove_context is not None:
        try:
            remove_context()
            result["remove_context"] = "called"
        except Exception:
            result["remove_context"] = "error"
    return result


def _cleanup_result_status(cleanup_result: dict[str, str]) -> str:
    if cleanup_result.get("vs_disconnect") == "error" or cleanup_result.get("remove_context") == "error":
        return "warn"
    return "ok"


def _cleanup_result_detail(cleanup_result: dict[str, str]) -> str:
    return (
        f"VSManager.disconnect(): {cleanup_result.get('vs_disconnect', 'skipped')}; "
        f"remove_context(): {cleanup_result.get('remove_context', 'skipped')}."
    )


def _format_preview(value, max_chars: int | None = 900) -> str:
    if value is None:
        return "None"
    if hasattr(value, "columns") and hasattr(value, "head") and hasattr(value, "shape"):
        try:
            total_rows = int(value.shape[0])
            if max_chars is None:
                try:
                    text = value.to_string(index=False, max_colwidth=48)
                except TypeError:
                    text = value.to_string(index=False)
                text = f"rows={total_rows}\n{text}"
            else:
                preview_rows = min(total_rows, 10)
                preview_df = value.head(preview_rows)
                try:
                    text = preview_df.to_string(index=False, max_colwidth=48)
                except TypeError:
                    text = preview_df.to_string(index=False)
                if total_rows > preview_rows:
                    text = f"rows={total_rows}\n{text}\n... ({total_rows - preview_rows} more rows)"
                else:
                    text = f"rows={total_rows}\n{text}"
        except Exception:
            text = str(value)
    elif hasattr(value, "to_string"):
        try:
            text = value.to_string(index=False)
        except Exception:
            text = str(value)
    elif isinstance(value, (dict, list, tuple)):
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            text = str(value)
    else:
        text = str(value)
    text = text.strip()
    if max_chars is not None and len(text) > max_chars:
        return f"{text[:max_chars]}... (truncated)"
    return text


def _build_file_meta(path_hint: str) -> dict[str, str | int | bool]:
    meta: dict[str, str | int | bool] = {
        "input": path_hint,
        "resolved": "",
        "exists": False,
        "size": 0,
        "sha256": "",
    }
    if not path_hint:
        return meta
    resolved = _resolve_path_hint(path_hint)
    meta["resolved"] = resolved
    p = Path(resolved)
    if not p.exists() or not p.is_file():
        return meta
    payload = p.read_bytes()
    meta["exists"] = True
    meta["size"] = len(payload)
    meta["sha256"] = hashlib.sha256(payload).hexdigest()
    return meta


def _new_connect_step(step: str, status: str, detail: str) -> dict[str, str]:
    status_lower = status.lower()
    message = f"[{step}] {detail}"
    if status_lower == "error":
        logger.error(message)
    elif status_lower == "warn":
        logger.warning(message)
    else:
        logger.info(message)
    return {
        "time": datetime.now().strftime("%H:%M:%S"),
        "step": step,
        "status": status,
        "detail": detail,
    }


def _append_connect_step(state: dict, step: str, status: str, detail: str, limit: int = 120) -> None:
    steps = list(state.get("connect_steps", []))
    steps.append(_new_connect_step(step, status, detail))
    state["connect_steps"] = steps[-limit:]


def _mask_token(token: str) -> str:
    value = token.strip()
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _load_connect_defaults() -> dict[str, str]:
    latest_uploaded_pem = _latest_uploaded_pem_relative()
    defaults = {
        "host": "<redacted-host>",
        "username": "<redacted-user>",
        "password": "<redacted-user>",
        "ues_url": "https://tddemos.innovationlabs.teradata.com/api/accounts/1ca5520e-5abd-441d-ba25-40c83ff23b2e/open-analytics",
        "pat_token": DEFAULT_PAT_TOKEN,
        "pem_file": latest_uploaded_pem or "<redacted-user>_jcb.pem",
    }

    vars_file = VS_BASICS_DIR / "vars-vs_demo.json"
    if not vars_file.exists():
        return defaults

    try:
        session_vars = json.loads(vars_file.read_text(encoding="utf-8"))
        env = session_vars.get("environment", {})
        users = (
            session_vars.get("hierarchy", {})
            .get("users", {})
            .get("business_users", [])
        )
        selected_user = users[0] if users else {}

        ues_url = str(env.get("UES_URI", defaults["ues_url"])).strip()
        return {
            "host": str(env.get("host", defaults["host"])).strip(),
            "username": str(selected_user.get("username", defaults["username"])).strip(),
            "password": str(selected_user.get("password", defaults["password"])),
            "ues_url": ues_url,
            "pat_token": defaults["pat_token"],
            "pem_file": latest_uploaded_pem or str(selected_user.get("key_file", defaults["pem_file"])).strip(),
        }
    except Exception:
        return defaults


def _default_evs_state() -> dict:
    connect_defaults = _load_connect_defaults()
    return {
        "connected": False,
        "connected_at": "",
        "last_error": "",
        "last_success": "",
        "health_preview": "",
        "list_preview": "",
        "actual_params": {},
        "connect_steps": [],
        "params": connect_defaults,
    }


def _default_create_values() -> dict[str, str]:
    data = {
        "vector_store_name": "TokioMarine",
        "create_preset": "vectordistance",
        "search_algorithm": "VECTORDISTANCE",
    }
    for field in CREATE_FIELDS:
        data.setdefault(field["name"], "")
    return data


def _apply_create_preset(payload: dict, preset: str, vector_store_name: str):
    if "object_names" not in payload:
        payload["object_names"] = f"{vector_store_name}_pdf_test"
    payload.setdefault("data_columns", ["chunks"])
    payload.setdefault("vector_column", "Embedding")
    payload.setdefault("chunk_size", 500)
    payload.setdefault("optimized_chunking", False)
    payload.setdefault("embeddings_model", "amazon.titan-embed-text-v2:0")
    payload.setdefault("top_k", 5)

    if preset == "vectordistance":
        payload["search_algorithm"] = "VECTORDISTANCE"
    elif preset == "hnsw":
        payload["search_algorithm"] = "HNSW"
        payload.setdefault("metric", "COSINE")
        payload.setdefault("seed", 10)
        payload.setdefault("ef_construction", 64)
        payload.setdefault("ef_search", 64)
        payload.setdefault("num_connpernode", 32)
        payload.setdefault("maxnum_connpernode", 32)
        payload.setdefault("apply_heuristics", True)


def _build_create_call_preview(vector_store_name: str, payload: dict) -> str:
    payload_json = json.dumps(payload, indent=2, ensure_ascii=False)
    return (
        f"pdf_vs = VectorStore('{vector_store_name}')\n"
        f"create_kwargs = {payload_json}\n"
        "pdf_vs.create(**create_kwargs)\n"
        "pdf_vs.status()\n\n"
        "# Notebook next calls:\n"
        "pdf_vs.ask(question='...', prompt='...')\n"
        "response = pdf_vs.similarity_search(question='...')\n"
        "pdf_vs.destroy()\n"
        "VSManager.disconnect()"
    )


def _normalize_document_files_for_create(create_payload: dict) -> tuple[dict, list[str]]:
    exec_payload = dict(create_payload)
    warnings: list[str] = []
    doc_files = exec_payload.get("document_files")
    if not doc_files:
        return exec_payload, warnings

    if isinstance(doc_files, str):
        raw_items = [doc_files]
    elif isinstance(doc_files, (list, tuple, set)):
        raw_items = [str(item).strip() for item in doc_files if str(item).strip()]
    else:
        raw_items = [str(doc_files).strip()]

    resolved_items: list[str] = []
    for raw in raw_items:
        resolved = _resolve_path_hint(raw)
        resolved_items.append(resolved)
        if not Path(resolved).exists():
            warnings.append(f"Document file not found on disk: {raw}")

    if len(resolved_items) == 1:
        exec_payload["document_files"] = resolved_items[0]
    else:
        exec_payload["document_files"] = resolved_items

    return exec_payload, warnings


app = FastAPI(title="EVSUI", version="0.3.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.state.evs_state = _default_evs_state()
app.state.create_form_values: dict[str, str] = _default_create_values()
app.state.last_create_operation: dict | None = None
app.state.document_uploads: list[dict] = []
app.state.document_upload_notices: list[str] = []
app.state.chat_history: list[dict] = [
    {
        "role": "assistant",
        "content": "EVS Validation Chat is ready. You can verify ask/similarity_search here.",
        "time": datetime.now().strftime("%H:%M"),
    }
]


def _active_vector_store_name() -> str:
    last = app.state.last_create_operation or {}
    name = str(last.get("vector_store_name", "")).strip()
    if name:
        return name
    current = app.state.create_form_values or {}
    return str(current.get("vector_store_name", "")).strip() or "TokioMarine"


def _detect_message_language(text: str) -> str:
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7a3]", text):
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    return "en"


def _ask_prompt_for_language(lang: str) -> str:
    if lang == "ja":
        return (
            "文書の根拠に基づいて回答してください。"
            "質問と同じ言語（日本語）で回答し、他の言語に切り替えないでください。"
            "文書内に根拠がない場合は、その旨を日本語で明確に回答してください。"
        )
    if lang == "zh":
        return (
            "请仅依据检索到的文档内容回答。"
            "必须使用与提问完全一致的语言（中文）作答，不要切换到其他语言。"
            "如果文档中没有依据，请用中文明确说明。"
        )
    if lang == "ko":
        return (
            "문서 근거만 사용해 답변하세요."
            "질문과 동일한 언어(한국어)로만 답변하고 다른 언어로 바꾸지 마세요."
            "문서 근거가 없으면 한국어로 명확히 알려주세요."
        )
    return (
        "Answer only with evidence from retrieved documents. "
        "Use exactly the same language as the user's question. "
        "If evidence is missing, state that clearly in the same language."
    )


def _build_evs_reply(message: str, validation_target: str) -> str:
    if VectorStore is None:
        return "Validation failed: VectorStore runtime is unavailable."

    question = message.strip()
    lang = _detect_message_language(question)
    ask_prompt = _ask_prompt_for_language(lang)
    target = validation_target.strip().lower()
    vs_name = _active_vector_store_name()

    try:
        vector_store = VectorStore(vs_name)
    except Exception as ex:
        return f"Validation failed: cannot open VectorStore('{vs_name}'): {ex}"

    try:
        if target == "vectorstore.similarity_search":
            try:
                result = vector_store.similarity_search(question=question)
            except TypeError:
                result = vector_store.similarity_search(question)
            return _format_preview(result, max_chars=None)

        try:
            result = vector_store.ask(question=question, prompt=ask_prompt)
        except TypeError:
            try:
                result = vector_store.ask(question, ask_prompt)
            except TypeError:
                try:
                    result = vector_store.ask(question=question)
                except TypeError:
                    result = vector_store.ask(question)
        return _format_preview(result, max_chars=None)
    except Exception as ex:
        method_name = "similarity_search" if target == "vectorstore.similarity_search" else "ask"
        return f"{method_name} failed on '{vs_name}': {ex}"


def _current_user(request: Request) -> str:
    return request.cookies.get("evsui_user", "")


def _user_initials(username: str) -> str:
    value = username.strip().upper()
    if not value:
        return "??"
    parts = value.split()
    if len(parts) >= 2:
        return (parts[0][:1] + parts[1][:1])[:2]
    return value[:2]


def _build_home_context(request: Request) -> dict:
    username = _current_user(request)
    return {
        "messages": app.state.chat_history,
        "evs": app.state.evs_state,
        "create_param_groups": _group_create_fields(),
        "create_values": app.state.create_form_values,
        "create_result": app.state.last_create_operation,
        "document_uploads": app.state.document_uploads,
        "document_upload_error": "",
        "document_upload_notices": app.state.document_upload_notices,
        "logged_in": _is_logged_in(request),
        "username": username,
        "user_initials": _user_initials(username),
    }


def _render_connect_panel(request: Request):
    return templates.TemplateResponse(
        request,
        "partials/evs_connect_panel.html",
        {"evs": app.state.evs_state},
    )


def _is_logged_in(request: Request) -> bool:
    return request.cookies.get("evsui_auth") == "1"


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if not _is_logged_in(request):
        return RedirectResponse(url="/login", status_code=303)
    context = _build_home_context(request)
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _is_logged_in(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "", "logged_in": False, "username": "", "user_initials": ""},
    )


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(default=""), password: str = Form(default="")):
    if username == "admin" and password == "admin":
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie("evsui_auth", "1", httponly=True, samesite="lax")
        response.set_cookie("evsui_user", username, httponly=True, samesite="lax")
        return response
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Invalid username or password.", "logged_in": False, "username": "", "user_initials": ""},
    )


@app.post("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("evsui_auth")
    response.delete_cookie("evsui_user")
    return response


@app.post("/ui/evs/connect", response_class=HTMLResponse)
async def evs_connect(
    request: Request,
    host: str = Form(default=""),
    username: str = Form(default=""),
    password: str = Form(default=""),
    ues_url: str = Form(default=""),
    pat_token: str = Form(default=""),
    current_pem_file: str = Form(default=""),
    pem_file: UploadFile = File(default=None),
):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    state = app.state.evs_state
    steps: list[dict[str, str]] = []
    actual_params: dict = {}
    resolved_pem_path = current_pem_file.strip()
    if pem_file is not None and pem_file.filename:
        suffix = Path(pem_file.filename).suffix.lower()
        if suffix in {".pem", ".key", ".crt"}:
            resolved_pem_path = _save_pem_upload(pem_file)
            steps.append(_new_connect_step("PEM File", "ok", f"Uploaded PEM saved as: {resolved_pem_path}"))
    elif resolved_pem_path:
        steps.append(_new_connect_step("PEM File", "ok", f"Using existing PEM path: {resolved_pem_path}"))
    else:
        steps.append(_new_connect_step("PEM File", "warn", "No PEM file provided."))

    params = {
        "host": host.strip(),
        "username": username.strip(),
        "password": password,
        "ues_url": ues_url.strip(),
        "pat_token": (pat_token or "").strip(),
        "pem_file": resolved_pem_path,
    }
    if params["pat_token"]:
        steps.append(_new_connect_step("PAT Token", "ok", f"Using submitted token: {_mask_token(params['pat_token'])}"))
    else:
        steps.append(_new_connect_step("PAT Token", "warn", "PAT token is empty. User must input it manually."))
    state["params"] = params
    steps.append(
        _new_connect_step(
            "Input Capture",
            "ok",
            f"host={params['host']}, username={params['username']}, ues_url={params['ues_url']}",
        )
    )

    missing = []
    if not params["host"]:
        missing.append("host")
    if not params["username"]:
        missing.append("username")
    if not params["password"]:
        missing.append("password")
    if not params["pat_token"]:
        missing.append("pat_token")
    if not params["ues_url"]:
        missing.append("ues_url")

    if missing:
        steps.append(_new_connect_step("Validate Required Fields", "error", f"Missing required fields: {', '.join(missing)}"))
        state["connected"] = False
        state["connected_at"] = ""
        state["last_success"] = ""
        state["last_error"] = f"Missing required fields: {', '.join(missing)}"
        state["health_preview"] = ""
        state["list_preview"] = ""
        state["actual_params"] = actual_params
        state["connect_steps"] = steps
    elif not (create_context and set_auth_token and VSManager):
        steps.append(
            _new_connect_step(
                "Dependency Check",
                "error",
                f"teradataml/teradatagenai import failed: {TERADATA_IMPORT_ERROR}",
            )
        )
        state["connected"] = False
        state["connected_at"] = ""
        state["last_success"] = ""
        state["last_error"] = (
            "teradataml/teradatagenai is not available. "
            "Install them first. "
            f"Import error: {TERADATA_IMPORT_ERROR}"
        )
        state["health_preview"] = ""
        state["list_preview"] = ""
        state["actual_params"] = actual_params
        state["connect_steps"] = steps
    else:
        steps.append(_new_connect_step("Validate Required Fields", "ok", "All required fields are present."))
        derived_base_url = _derive_base_url(params["ues_url"])
        steps.append(_new_connect_step("Derive Base URL", "ok", f"base_url = {derived_base_url}"))
        resolved_pem_for_auth = _resolve_path_hint(params["pem_file"])
        normalized_pem_for_auth = _normalize_pem_filename_for_auth(resolved_pem_for_auth) if resolved_pem_for_auth else ""
        pem_meta = _build_file_meta(params["pem_file"])
        warnings: list[str] = []
        if params["pem_file"] and resolved_pem_for_auth == params["pem_file"]:
            warnings.append("PEM path not found on disk; authentication will use provided raw value.")
            steps.append(
                _new_connect_step(
                    "Resolve PEM Path",
                    "warn",
                    f"PEM file not found on disk, using raw value: {params['pem_file']}",
                )
            )
        elif resolved_pem_for_auth:
            steps.append(_new_connect_step("Resolve PEM Path", "ok", f"Resolved PEM path: {resolved_pem_for_auth}"))
        else:
            steps.append(_new_connect_step("Resolve PEM Path", "warn", "No PEM path resolved."))
        if normalized_pem_for_auth and normalized_pem_for_auth != resolved_pem_for_auth:
            steps.append(
                _new_connect_step(
                    "Normalize PEM Filename",
                    "ok",
                    f"Auth will use normalized filename path: {normalized_pem_for_auth}",
                )
            )
        elif normalized_pem_for_auth:
            steps.append(
                _new_connect_step(
                    "Normalize PEM Filename",
                    "ok",
                    f"Filename already valid for auth: {normalized_pem_for_auth}",
                )
            )
        try:
            cleanup_before = _cleanup_context()
            steps.append(
                _new_connect_step(
                    "Cleanup Previous Session",
                    _cleanup_result_status(cleanup_before),
                    _cleanup_result_detail(cleanup_before),
                )
            )
            create_context(host=params["host"], username=params["username"], password=params["password"])
            steps.append(_new_connect_step("create_context", "ok", "Database context created successfully."))

            auth_kwargs = {"base_url": derived_base_url, "pat_token": params["pat_token"]}
            if normalized_pem_for_auth:
                auth_kwargs["pem_file"] = normalized_pem_for_auth
            elif resolved_pem_for_auth:
                auth_kwargs["pem_file"] = resolved_pem_for_auth
            elif params["pem_file"]:
                auth_kwargs["pem_file"] = params["pem_file"]
            actual_params = {
                "create_context": {
                    "host": params["host"],
                    "username": params["username"],
                    "password_length": len(params["password"] or ""),
                },
                "set_auth_token": auth_kwargs | {"pat_token": params["pat_token"], "pem_meta": pem_meta},
                "pem_resolution": {
                    "input": params["pem_file"],
                    "resolved": resolved_pem_for_auth,
                    "normalized": normalized_pem_for_auth,
                },
            }
            set_auth_token(**auth_kwargs)
            steps.append(_new_connect_step("set_auth_token", "ok", "VS authentication token set successfully with selected PEM."))

            state["connected"] = True
            state["connected_at"] = _now_ts()
            state["last_error"] = " | ".join(warnings) if warnings else ""
            state["last_success"] = "Step 1 completed. Database connection and VS authentication succeeded."
            state["health_preview"] = ""
            state["list_preview"] = ""
            state["actual_params"] = actual_params
            state["connect_steps"] = steps
        except Exception as ex:
            cleanup_after_fail = _cleanup_context()
            steps.append(_new_connect_step("Execution Failed", "error", str(ex)))
            steps.append(
                _new_connect_step(
                    "Rollback Cleanup",
                    _cleanup_result_status(cleanup_after_fail),
                    _cleanup_result_detail(cleanup_after_fail),
                )
            )
            state["connected"] = False
            state["connected_at"] = ""
            state["last_success"] = ""
            state["last_error"] = f"Connection/auth failed: {ex}"
            state["health_preview"] = ""
            state["list_preview"] = ""
            state["actual_params"] = actual_params
            state["connect_steps"] = steps

    return _render_connect_panel(request)


@app.post("/ui/evs/upload-pem", response_class=HTMLResponse)
async def upload_pem_file(
    request: Request,
    current_pem_file: str = Form(default=""),
    pem_file: UploadFile = File(default=None),
):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)

    pem_file_path = current_pem_file.strip() or app.state.evs_state["params"].get("pem_file", "")
    pem_upload_error = ""

    if pem_file is None or not pem_file.filename:
        pem_upload_error = "No PEM file selected."
    else:
        suffix = Path(pem_file.filename).suffix.lower()
        if suffix not in {".pem", ".key", ".crt"}:
            pem_upload_error = "Only .pem, .key, .crt files are allowed."
        else:
            pem_file_path = _save_pem_upload(pem_file)
            app.state.evs_state["params"]["pem_file"] = pem_file_path

    return templates.TemplateResponse(
        request,
        "partials/pem_upload_status.html",
        {
            "pem_file_path": pem_file_path,
            "pem_upload_error": pem_upload_error,
        },
    )


@app.post("/ui/evs/reset", response_class=HTMLResponse)
async def evs_reset(request: Request):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    cleanup_result = _cleanup_context()
    reset_state = _default_evs_state()
    reset_state["last_success"] = "Disconnected and reset completed."
    reset_state["connect_steps"] = [
        _new_connect_step(
            "Reset / Disconnect",
            _cleanup_result_status(cleanup_result),
            f"Reset endpoint called. {_cleanup_result_detail(cleanup_result)}",
        )
    ]
    app.state.evs_state = reset_state
    app.state.create_form_values = _default_create_values()
    app.state.last_create_operation = None
    app.state.document_uploads = []
    app.state.document_upload_notices = []
    return _render_connect_panel(request)


@app.post("/ui/create/upload-documents", response_class=HTMLResponse)
async def upload_documents_for_create(request: Request):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)

    form = await request.form()
    files = _collect_upload_files(form, field_name="files")

    saved: list[dict] = []
    notices: list[str] = []
    upload_error = ""
    if not files:
        upload_error = "No files selected."
    else:
        saved, notices = await _save_document_uploads(files)
        if not saved:
            upload_error = "No valid files found in selection."

    if saved:
        app.state.document_uploads = saved
    app.state.document_upload_notices = notices

    return templates.TemplateResponse(
        request,
        "partials/selected_documents.html",
        {
            "document_uploads": app.state.document_uploads,
            "document_upload_error": upload_error,
            "document_upload_notices": notices,
        },
    )


@app.post("/ui/evs/health", response_class=HTMLResponse)
async def evs_run_health(request: Request):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    state = app.state.evs_state
    if not state["connected"]:
        state["health_preview"] = "Connect in Step 1 first."
        state["last_error"] = "Run blocked: connection is not established."
        _append_connect_step(state, "VSManager.health()", "warn", "Blocked: Step 1 is not connected.")
        return _render_connect_panel(request)
    if VSManager is None:
        state["health_preview"] = f"Cannot run: {TERADATA_IMPORT_ERROR}"
        state["last_error"] = "VS runtime is unavailable."
        _append_connect_step(state, "VSManager.health()", "error", f"Runtime unavailable: {TERADATA_IMPORT_ERROR}")
        return _render_connect_panel(request)
    health_fn = getattr(VSManager, "health", None)
    if not callable(health_fn):
        state["health_preview"] = "Cannot run: VSManager.health is not callable."
        state["last_error"] = "VSManager.health() is not callable."
        _append_connect_step(state, "VSManager.health()", "error", "VSManager.health is missing or not callable.")
        return _render_connect_panel(request)
    try:
        health_output = health_fn()
        state["health_preview"] = _format_preview(health_output)
        state["last_error"] = ""
        state["last_success"] = "VSManager.health() completed."
        _append_connect_step(state, "VSManager.health()", "ok", "Called successfully.")
    except Exception as ex:
        state["health_preview"] = f"Error: {ex}"
        state["last_error"] = f"VSManager.health() failed: {ex}"
        _append_connect_step(state, "VSManager.health()", "error", f"Execution failed: {ex}")
    return _render_connect_panel(request)


@app.post("/ui/evs/list", response_class=HTMLResponse)
async def evs_run_list(request: Request):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    state = app.state.evs_state
    if not state["connected"]:
        state["list_preview"] = "Connect in Step 1 first."
        state["last_error"] = "Run blocked: connection is not established."
        _append_connect_step(state, "VSManager.list()", "warn", "Blocked: Step 1 is not connected.")
        return _render_connect_panel(request)
    if VSManager is None:
        state["list_preview"] = f"Cannot run: {TERADATA_IMPORT_ERROR}"
        state["last_error"] = "VS runtime is unavailable."
        _append_connect_step(state, "VSManager.list()", "error", f"Runtime unavailable: {TERADATA_IMPORT_ERROR}")
        return _render_connect_panel(request)
    list_fn = getattr(VSManager, "list", None)
    if not callable(list_fn):
        state["list_preview"] = "Cannot run: VSManager.list is not callable."
        state["last_error"] = "VSManager.list() is not callable."
        _append_connect_step(state, "VSManager.list()", "error", "VSManager.list is missing or not callable.")
        return _render_connect_panel(request)
    try:
        list_output = list_fn()
        state["list_preview"] = _format_preview(list_output)
        if hasattr(list_output, "shape"):
            rows = int(list_output.shape[0])
            _append_connect_step(state, "VSManager.list()", "ok", f"Called successfully. rows={rows}.")
        else:
            _append_connect_step(state, "VSManager.list()", "ok", "Called successfully.")
        state["last_error"] = ""
        state["last_success"] = "VSManager.list() completed."
    except Exception as ex:
        state["list_preview"] = f"Error: {ex}"
        state["last_error"] = f"VSManager.list() failed: {ex}"
        _append_connect_step(state, "VSManager.list()", "error", f"Execution failed: {ex}")
    return _render_connect_panel(request)


@app.post("/ui/create/upload", response_class=HTMLResponse)
async def upload_and_prepare_create(request: Request):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    if not app.state.evs_state["connected"]:
        return templates.TemplateResponse(
            request,
            "partials/create_result.html",
            {
                "create_result": {
                    "status": "error",
                    "time": _now_ts(),
                    "message": "Connect/authenticate in Step 1 first.",
                }
            },
        )

    form = await request.form()
    files = _collect_upload_files(form, field_name="files")

    saved: list[dict] = []
    upload_notices: list[str] = []
    if files:
        saved, upload_notices = await _save_document_uploads(files)
    if saved:
        app.state.document_uploads = saved
    app.state.document_upload_notices = upload_notices

    create_values: dict[str, str] = {}
    vector_store_name = str(form.get("vector_store_name", "")).strip() or "TokioMarine"
    create_preset = str(form.get("create_preset", "vectordistance")).strip() or "vectordistance"
    create_values["vector_store_name"] = vector_store_name
    create_values["create_preset"] = create_preset

    create_payload: dict = {}
    warnings: list[str] = list(upload_notices)
    for field in CREATE_FIELDS:
        raw = str(form.get(field["name"], "")).strip()
        if len(raw) > CREATE_FIELD_MAX_LEN:
            raw = raw[:CREATE_FIELD_MAX_LEN]
            warnings.append(f"Field [{field['name']}] exceeded {CREATE_FIELD_MAX_LEN} chars and was truncated.")
        create_values[field["name"]] = raw
        if not raw:
            continue
        try:
            create_payload[field["name"]] = _coerce_create_param(field["name"], raw)
        except ValueError:
            warnings.append(f"Field [{field['name']}] cannot be cast; kept as string.")
            create_payload[field["name"]] = raw

    if saved and "document_files" not in create_payload:
        create_payload["document_files"] = [item["saved_path"] for item in saved]
    elif (not saved) and ("document_files" not in create_payload) and app.state.document_uploads:
        create_payload["document_files"] = [item["saved_path"] for item in app.state.document_uploads]

    _apply_create_preset(create_payload, create_preset, vector_store_name)
    app.state.create_form_values = create_values

    exec_payload, path_warnings = _normalize_document_files_for_create(create_payload)
    warnings.extend(path_warnings)

    execution_output_preview = ""
    status_output_preview = ""

    if VectorStore is None:
        result_status = "error"
        result_message = "Step 2 failed: VectorStore runtime is unavailable in current environment."
    else:
        try:
            vector_store = VectorStore(vector_store_name)
            create_output = vector_store.create(**exec_payload)
            execution_output_preview = _format_preview(create_output)

            status_fn = getattr(vector_store, "status", None)
            if callable(status_fn):
                try:
                    status_output_preview = _format_preview(status_fn())
                except Exception as status_ex:
                    status_output_preview = f"Status check failed: {status_ex}"

            result_status = "ok_with_warnings" if warnings else "ok"
            result_message = "Step 2 completed. VectorStore.create() executed successfully."
        except Exception as ex:
            result_status = "error"
            result_message = f"Step 2 failed while executing VectorStore.create(): {ex}"

    result = {
        "status": result_status,
        "time": _now_ts(),
        "message": result_message,
        "vector_store_name": vector_store_name,
        "create_preset": create_preset,
        "uploaded_files": saved if saved else app.state.document_uploads,
        "warnings": warnings,
        "create_payload_json": json.dumps(create_payload, indent=2, ensure_ascii=False),
        "create_execute_payload_json": json.dumps(exec_payload, indent=2, ensure_ascii=False),
        "create_call_preview": _build_create_call_preview(vector_store_name, create_payload),
        "execution_output_preview": execution_output_preview,
        "status_output_preview": status_output_preview,
    }
    app.state.last_create_operation = result

    return templates.TemplateResponse(
        request,
        "partials/create_result.html",
        {"create_result": result},
    )


@app.post("/ui/chat", response_class=HTMLResponse)
async def chat_send(
    request: Request,
    message: str = Form(...),
    validation_target: str = Form(default="vectorstore.ask"),
):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    if not app.state.evs_state["connected"]:
        app.state.chat_history.append(
            {
                "role": "assistant",
                "content": "Step 3 is locked. Connect and authenticate in Step 1 first.",
                "time": datetime.now().strftime("%H:%M"),
            }
        )
        app.state.chat_history = app.state.chat_history[-80:]
        return templates.TemplateResponse(
            request,
            "partials/chat_messages.html",
            {"messages": app.state.chat_history},
        )

    clean = message.strip()
    selected_target = validation_target.strip().lower()
    if selected_target not in ALLOWED_VALIDATION_TARGETS:
        selected_target = "vectorstore.ask"
    if clean:
        app.state.chat_history.append(
            {
                "role": "user",
                "content": clean,
                "time": datetime.now().strftime("%H:%M"),
            }
        )
        app.state.chat_history.append(
            {
                "role": "assistant",
                "content": _build_evs_reply(clean, selected_target),
                "time": datetime.now().strftime("%H:%M"),
            }
        )
        app.state.chat_history = app.state.chat_history[-80:]

    return templates.TemplateResponse(
        request,
        "partials/chat_messages.html",
        {"messages": app.state.chat_history},
    )


@app.post("/ui/chat/reset", response_class=HTMLResponse)
async def chat_reset(request: Request):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    app.state.chat_history = [
        {
            "role": "assistant",
            "content": "Session cleared. Continue with notebook-based EVS validations.",
            "time": datetime.now().strftime("%H:%M"),
        }
    ]
    return templates.TemplateResponse(
        request,
        "partials/chat_messages.html",
        {"messages": app.state.chat_history},
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
