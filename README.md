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
- `Format Fusion` mode runs Unstructured Workflow (`teradata-sql` destination connector) and writes processed text rows into a Teradata table automatically.

3. Step 3: Retrieval Chat
- Supports `VectorStore.ask` and `VectorStore.similarity_search`
- Independent Run List dropdown for chat target vector store

## Current Behavior

- Step 1 `Run List` and Step 3 `Run List` are decoupled (no cross-update).
- In Step 3, clicking `Run List` loads real vector stores and displays an available item by default.
- Step 1 `destroy` refreshes only Step 1 list data, not the Step 3 dropdown.
- No auto-list on connect; list execution is manual.

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

## Format Fusion Environment

- Required:
  - `UNSTRUCTURED_API_KEY`
- Optional:
  - `UNSTRUCTURED_PLATFORM_URL` (default: `https://platform.unstructuredapp.io/`)
  - `UNSTRUCTURED_WORKFLOW_POLL_SECONDS` (default: `120`)
  - `UNSTRUCTURED_WORKFLOW_POLL_INTERVAL` (default: `2`)
  - `UNSTRUCTURED_TERADATA_BATCH_SIZE` (default: `200`)
  - `UNSTRUCTURED_KEEP_WORKFLOW_RESOURCES` (`true/false`, default: `false`)

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

- Default username: `admin`
- Default password: `admin`

## Project Structure

- Application entry: `app/main.py`
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
