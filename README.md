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
- `Multi Format` mode uses Unstructured Workflow Endpoint on-demand jobs, creates a Teradata table first, and writes processed chunk rows into `<Vector Store Name>_unstructured`.
- `Multi-Format BookRAG` mode skips `VectorStore.create()` and uses Unstructured Workflow Endpoint on-demand jobs with inline `job_nodes` to collect raw elements into dedicated Teradata tables for traceability.

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

## Unstructured Chain Guide

This project should follow Unstructured's current hosted API guidance:

- Use the **Workflow Endpoint / on-demand jobs** for production workflows.
- Treat the **Partition Endpoint** as **legacy / prototyping only**.
- Do not mix Workflow and Partition assumptions in the same feature design.

Official references:
- Workflow docs: https://docs.unstructured.io/api-reference/workflow/workflows
- Workflow UI guide: https://docs.unstructured.io/ui/workflows
- Partition Endpoint overview: https://docs.unstructured.io/platform-api/partition-api/overview
- Partition Endpoint parameters: https://docs.unstructured.io/api-reference/partition/api-parameters
- Partitioning strategy guide: https://docs.unstructured.io/ui/partitioning

### Official API Choice

1. **Workflow Endpoint**
- Officially recommended for production-level usage.
- Supports batches, latest models, enrichments, chunking strategies, embeddings, and remote sources.
- Conceptual chain: `Source -> Partitioner -> optional Enrichment -> optional Chunker -> optional Embedder -> Destination`

2. **Partition Endpoint**
- Officially marked as legacy / rapid prototyping.
- Intended for one local file at a time, with limited chunking.
- Conceptual chain: `Local file -> Partitioner(strategy=...) -> optional chunking_strategy`

### Official Invocation Paths

1. **Partition Endpoint (legacy)**
- Typical call shape: `POST https://api.unstructuredapp.io/general/v0/general`
- Typical request shape: multipart form with `files` plus partition parameters such as `strategy` and `output_format`
- Official position: legacy, local-file only, one file at a time, limited chunking, intended for rapid prototyping

2. **Workflow on-demand job**
- Typical call shape: `POST https://platform.unstructuredapp.io/api/v1/jobs/`
- Typical request shape: multipart form with `request_data` and `input_files`
- `request_data` can define a temporary workflow using inline `job_nodes`, or reference a template
- Official position: recommended Workflow Operations path for local-file job runs; the workflow exists only for that job run

3. **Long-lived workflow + run**
- Define reusable workflow: `POST https://platform.unstructuredapp.io/api/v1/workflows`
- Run reusable workflow: `POST https://platform.unstructuredapp.io/api/v1/workflows/{workflow_id}/run`
- Typical request shape: define persistent `workflow_nodes` once, then submit `input_files` when running it
- Official position: use when you need a named workflow resource that can be listed, updated, and reused by `workflow_id`

### Current EVSUI Mapping

1. **Unstructured** (`doc_pipeline_mode=multi_format`)
- Uses the **Workflow Endpoint**.
- Current transport path: `local file -> POST /jobs -> inline job_nodes`
- Implemented chain: `Partitioner -> optional Enrichment nodes -> Chunker`
- Current workflow chunker options in EVSUI:
  - `chunk_by_character`
  - `chunk_by_title`
  - `chunk_by_page`
  - `chunk_by_similarity`

2. **Unstructured BookRAG** (`doc_pipeline_mode=multi_format_bookrag`)
- Uses the **Workflow Endpoint**.
- Current transport path: `local file -> POST /jobs -> inline job_nodes`
- Current implemented chain: `Partitioner -> optional Enrichment nodes`
- Current app behavior stores raw workflow output in Teradata BookRAG tables.
- Current app behavior submits an on-demand job with inline `job_nodes`; it does **not** currently create/reuse a named Workflow and does **not** run by `workflow_id`.
- Current BookRAG flow does **not** add a Workflow `Chunker` node.
- Do not describe the current BookRAG implementation as `by_title` chunking unless the code actually adds a Workflow chunk node.

### Official Route Combinations For Workflow Endpoint

1. **Fast**
- Official use: text-only documents.
- Recommended chain: `Partitioner(Fast) -> Chunker`
- Do **not** expect image description, table description, table-to-HTML, or generative OCR outputs here.

2. **Auto**
- Official recommendation: use in most cases.
- Recommended chain: `Partitioner(Auto) -> optional Enrichment nodes -> Chunker`
- For PDFs, Auto can route page-by-page: simple embedded-text pages can go to Fast; more complex pages can go to High Res or VLM.

3. **High Res**
- Official use: supported file types needing stronger structure handling, simple tables, images, or bounding-box coordinates.
- Recommended chain: `Partitioner(High Res) -> optional Enrichment nodes -> Chunker`

4. **VLM**
- Official use: highest-quality processing for visually complex PDFs/images, especially complex tables, images, multilingual, scanned, or handwritten content.
- Recommended chain: `Partitioner(VLM) -> Chunker`
- For VLM workflows, separate image-description, table-description, table-to-HTML, and generative-OCR nodes are **not needed (or allowed)** by the official workflow guidance.

### Official Route Selection Guidance

- **Auto**: recommended in most cases.
- **Fast**: only when you are sure the files are text-only and have no tables, images, multilingual, scanned, or handwritten content.
- **High Res**: use when you are sure at least one file has images or simple tables, and you need stronger layout handling or coordinates.
- **VLM**: best when files contain complex tables, images, multilingual text, scanned pages, or handwriting.

### Official Enrichment Rules

- `Fast + enrichment nodes`: do not expect enrichment outputs.
- `Auto/High Res + enrichment nodes`: supported when the file content and routed partition path are eligible.
- `VLM + separate enrichment nodes`: do not add them as a normal design pattern; official workflow guidance says they are not needed or allowed.

### Current EVSUI Defaults

These are **application defaults**, not official Unstructured defaults:

- `multi_format_strategy = auto`
- `multi_format_chunk_strategy = chunk_by_character`
- `multi_format_chunk_size = 600`
- `multi_format_chunk_overlap = 80`
- `multi_format_chunk_new_after_n_chars = 600`
- `multi_format_chunk_combine_text_under_n_chars = 600`
- `multi_format_chunk_multipage_sections = true`
- `multi_format_chunk_similarity_threshold = 0.5`
- `multi_format_infer_table_structure = false`
- all Unstructured enrichments default to `false` in the UI

### Coding Rules For This Repo

- When updating `multi_format`, think in **Workflow Endpoint** terms only.
- Do not reintroduce Partition Endpoint-only concepts such as `chunking_strategy=basic` into the current `multi_format` workflow path.
- If documentation, UI labels, or tests mention `by_title`, `basic`, or other chunk labels, make sure they match the actual chain in code.
- When documenting Unstructured integration, distinguish API entrypoints from DAG node types: a Workflow that starts with a `Partitioner` node is still not the legacy Partition Endpoint.
- Do not describe current BookRAG execution as a reusable named Workflow unless the code actually creates/reuses a Workflow resource and runs jobs by `workflow_id` or `/workflows/{workflow_id}/run`.
- If BookRAG later adds a real Workflow `Chunker` node, update this README and tests in the same change.

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
