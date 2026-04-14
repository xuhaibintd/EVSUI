# Teradata Vector Store

Teradata Vector Store is a `FastAPI + Jinja2 + HTMX` three-step interface for connecting to Teradata, creating vector stores, and validating retrieval in chat.

## Overview

1. Step 1: Connect & Manage
- Database connection and authentication:
  - `create_context(host, username, password)`
  - `set_auth_token(base_url, pat_token, pem_file)`
- Management actions:
  - `VSManager.health()`
  - `VSManager.list()`
  - Select and run `VectorStore.destroy()`

2. Step 2: Create Vector Store
- Supports multi-file upload
- Full `VectorStore.create(...)` parameter form
- Built-in parameter sets for `VECTORDISTANCE / KMEANS / HNSW`
- `Multi Format` mode runs Unstructured Workflow (`teradata-sql` destination connector), creates a Teradata table first, and writes processed text rows into `<Vector Store Name>_unstructured`.
- `Multi-Format BookRAG` mode skips `VectorStore.create()` and writes Unstructured `by_title` chunks into a dedicated Teradata table while preserving full chunk JSON for traceability.

3. Step 3: Retrieval Chat
- Supports `VectorStore.ask` and `VectorStore.similarity_search`
- Independent Run List dropdown for chat target vector store

## Current Behavior

- Step 1 `Run List` and Step 3 `Run List` are decoupled (no cross-update).
- In Step 3, clicking `Run List` loads real vector stores and displays an available item by default.
- Step 1 `destroy` refreshes only Step 1 list data, not the Step 3 dropdown.
- No auto-list on connect; list execution is manual.
- Step 2 submit validation blocks create unless `vector_store_name`, `doc_pipeline_mode`, `embeddings_model`, and a document source are present. Uploaded files and `document_files` both satisfy this check.
- For uploaded-file create flow, `object_names` is not auto-filled by the UI.
- Step 2 does not report success when `VectorStore.create()` merely returns; it waits until `VectorStore.status()` reaches `Ready`.
- If `create()` reports `already exists`, the app verifies existence with unfiltered `VSManager.list()` and only reuses the store when its current status is `Ready`.

## Requirements

- Python 3.10+
- Dependencies in `requirements.txt`:
  - `fastapi`
  - `uvicorn[standard]`
  - `jinja2`
  - `python-multipart`
  - `teradataml`
  - `teradatagenai`
  - `unstructured-client`
  - `packaging`

## Multi Format Config

- Configure Unstructured credentials in `app/config/unstructured.json`.
- Supported API key fields: `api_key`, `key_id`, `UNSTRUCTURED_API_KEY`, `UNSTRUCTURED_API_KEY_AUTH`
- Supported API URL fields: `api_url`, `UNSTRUCTURED_API_URL`, `UNSTRUCTURED_PLATFORM_URL`

Example:

```json
{
  "api_key": "your-unstructured-api-key",
  "api_url": "https://platform.unstructuredapp.io/api/v1"
}
```

- Optional runtime env:
  - `UNSTRUCTURED_WORKFLOW_POLL_SECONDS` (default: `120`)
  - `UNSTRUCTURED_WORKFLOW_POLL_INTERVAL` (default: `2`)
  - `UNSTRUCTURED_TERADATA_FLUSH_WAIT_SECONDS` (default: `20`)
  - `UNSTRUCTURED_TERADATA_FLUSH_WAIT_INTERVAL` (default: `2`)

Notes:
- Web console sign-in URL: `https://platform.unstructured.io`
- Workflow API URL default: `https://platform.unstructuredapp.io/api/v1`
- If the config file exists but does not contain an API key, multi-format create will fail with `Unstructured API key missing`.

## Quick Start

```bash
cd EVSUI
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8010
```

Windows PowerShell:

```powershell
cd EVSUI
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8010
```

Open: `http://127.0.0.1:8010`

## Login

- Configure users in `app/config/auth_users.json`.
- The repository currently ships with:

```json
{
  "users": {
    "admin": "<redacted-password>"
  }
}
```

- You can replace it with your own users, for example:

```json
{
  "users": {
    "admin": "change-me",
    "alice": "alice-pass",
    "bob": "bob-pass"
  }
}
```

- Optional:
  - `POC_AUTH_FILE` to point to a different JSON file path.
  - Fallback single-user env vars: `POC_ADMIN_USER`, `POC_ADMIN_PASSWORD` (used only when config file has no users).

- Multi-user isolation:
  - Each login gets its own session (`evsui_sid`) and independent UI state.

## Project Structure

- Application entry and routes: `app/main.py`
- Auth config: `app/config/auth_users.json`
- Service layer:
  - `app/services/create_config.py` (create form schema/coercion)
  - `app/services/multi_format.py` (multi-format preprocessing pipeline)
- Templates: `app/templates/`
- Static assets: `app/static/`
- Upload directories:
  - Documents: `uploads/documents/`
  - PEM: `uploads/pem/`
- Optional environment source:
  - `../VS_Basics_Full_Kit/vars-vs_demo.json`

## Main Routes

- `GET /` Home
- `GET /login`, `POST /login`, `POST /logout`
- `POST /ui/evs/connect`, `POST /ui/evs/reset`
- `POST /ui/evs/upload-pem`
- `POST /ui/evs/health`, `POST /ui/evs/list`
- `POST /ui/chat/vs-list`
- `POST /ui/evs/select`, `POST /ui/evs/destroy`
- `POST /ui/create/upload-documents`, `POST /ui/create/upload`
- `POST /ui/chat`, `POST /ui/chat/reset`
- `GET /healthz`

## Health Check

`GET /healthz` returns:

```json
{"status":"ok"}
```
