# Teradata Vector Store

Teradata Vector Store provides vector-search and retrieval capabilities on top of Teradata data. It stores document chunks and embeddings as managed vector stores, then exposes operations for creation, health checks, listing, deletion, semantic similarity search, and grounded Q&A through `VectorStore` and `VSManager`.

EVSUI is a `FastAPI + Jinja2 + HTMX` interface for working with Teradata Vector Store. It helps users connect to Teradata, create vector stores from uploaded or configured document sources, validate retrieval in chat, run precision checks, and manage per-session Unstructured IO credentials.

## Overview

### Connect & Manage

- Database connection and authentication:
  - `create_context(host, username, password)`
  - `set_auth_token(base_url, pat_token, pem_file)`
- Management actions:
  - `VSManager.health()`
  - `VSManager.list()`
  - Select and run `VectorStore.destroy()`

### Vector Store Creation

- Supports multi-file upload
- Full `VectorStore.create(...)` parameter form
- Built-in parameter sets for `VECTORDISTANCE / KMEANS / HNSW`
- `Multi Format` mode uses Unstructured Workflow Endpoint on-demand jobs and a reusable three-stage flow: raw JSON, standard unstructured CSV, then `<Vector Store Name>_unstructured` table loading. Its JSON-to-row mapping and table contract remain unchanged.
- `Multi-Format BookRAG` mode uses Unstructured Workflow Endpoint on-demand jobs with inline `job_nodes`, builds document-scoped Teradata tables, and can optionally run `VectorStore.create()` from `bnode.content` with `(doc_id, node_id)` as the vector key. See [BookRAG Pipeline: Data Structures and Processing Flow](docs/bookrag_pipeline_diagram.md) for the visual pipeline and table model.
- BookRAG is intended for industrial-grade, audit-ready document QA where section paths, tables, images, entities, relations, and multi-evidence reasoning matter. See [BookRAG for Industrial-Grade Applications / 産業用途における BookRAG のユースケース](docs/bookrag_industrial_use_cases.md) for English and Japanese scenario guidance.

### Vector Store Retrieval

- Supports `VectorStore.ask` and `VectorStore.similarity_search`
- Independent Run List dropdown for chat target vector store

### Precision Evaluation

- Compares selected source PDF and generated JSON debug output.
- Produces a precision evaluation report for inspection.

### Admin Rules

- Shows Unstructured IO account settings for the active session.
- Saves `unstructured_api_url` and `unstructured_api_key` into the current user session.
- Session values are used by Multi Format and Multi-Format BookRAG before falling back to `app/config/local_dev.json`.

## Current Behavior

- Connect & Manage `Run List` and Vector Store Retrieval `Run List` are decoupled (no cross-update).
- In Vector Store Retrieval, clicking `Run List` loads real vector stores and displays an available item by default.
- Connect & Manage `destroy` refreshes only the management list data, not the retrieval dropdown.
- No auto-list on connect; list execution is manual.
- Vector Store Creation submit validation blocks create unless `vector_store_name`, `doc_pipeline_mode`, `embeddings_model`, and a document source are present. Uploaded files and `document_files` both satisfy this check.
- For uploaded-file create flow, `object_names` is not auto-filled by the UI.
- Vector Store Creation does not report success when `VectorStore.create()` merely returns. By default it polls every 5 seconds (`EVS_VECTORSTORE_READY_POLL_SECONDS`) until `VectorStore.status()` reaches the terminal `Ready` or `Failed` state; there is no time-based cutoff. Operations may set `EVS_VECTORSTORE_READY_TIMEOUT_SECONDS` explicitly when an infrastructure-level request limit is required. An explicitly configured timeout is reported as still processing and leaves the CSV manifest in `creating`, because the server-side operation is not cancelled.
- After a loaded BookRAG store reaches `Ready`, the app verifies that the vector index row count matches the non-empty `bnode.content` row count. `EVS_BOOKRAG_INDEX_READY_TIMEOUT_SECONDS` can optionally add a database-visibility grace period; the default is a single immediate verification. An unavailable verification query is a warning; a successfully verified empty or incomplete index is an error.
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
- Workflow available models: https://docs.unstructured.io/api-reference/workflow/models
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
- The UI separates processing into **Document Parsing**, **Generate CSV from JSON**, and **Load CSV to Unstructured Table**. The CSV stage only applies the existing `UNSTRUCTURED_CHUNK_COLUMNS` mapping; it does not build BookRAG nodes, graphs, or auxiliary tables.
- After loading and row-count verification, the table-ready run can be selected in Basic and used by `VectorStore.create()` with `text` as the data column and `id` as the key column.

2. **Unstructured BookRAG** (`doc_pipeline_mode=multi_format_bookrag`)
- Uses the **Workflow Endpoint**.
- Current transport path: `local file -> POST /jobs -> inline job_nodes`
- Current implemented chain: `Partitioner -> optional Enrichment nodes`
- Current app behavior stores raw workflow output and the derived document/block/node structures in Teradata BookRAG tables.
- Visual architecture reference: [BookRAG Pipeline: Data Structures and Processing Flow](docs/bookrag_pipeline_diagram.md)
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

## BookRAG Data and Relationship Contract

This section is the normative description of the current BookRAG implementation. It is written for both developers and external LLM/MCP clients. Last updated: **2026-07-14**.

### Canonical Rules

- `doc_id` is the stable identity of one uploaded document instance. A new UUID is assigned on upload and is preserved through that upload manifest, JSON/CSV staging, Teradata tables, vector keys, retrieval, and document relationships. Uploading the same file again creates a new `doc_id`; identity is not derived from the filename or file content.
- Every identifier that is only unique inside one document must be joined together with `doc_id`. Do not join `node_id`, `element_id`, `entity_id`, `link_id`, or `relation_id` by itself.
- The active vector source is the physical `bnode` table: data column `content`, key columns `(doc_id, node_id)`.
- `bleaf` is a legacy/cleanup-only view target and is not the current vector source. Do not create a new query dependency on it.
- `bchk` remains as a compatibility/helper table target, but the current Multi-Format BookRAG pipeline does not generate or query it.
- Physical table names are generated by `build_bookrag_table_targets()`. Teradata's 30-character identifier limit may shorten/hash a long vector-store name, so clients must not construct names by string concatenation. Use `GET /api/bookrag/schema?vector_store_name=...` to obtain the actual names.

### Active Tables

| Suffix | Contract key | Role | Primary key | Purpose |
|---|---|---|---|---|
| `bdoc` | `documents` | Core | `doc_id` | Document catalog, original filename, source/debug JSON path, workflow/job metadata, file properties |
| `bblk` | `blocks` | Core | `(doc_id, element_id)` | Normalized Unstructured source elements, including text, HTML, tables, image descriptions, page and hierarchy metadata |
| `bnode` | `nodes` | Core | `(doc_id, node_id)` | Book tree used for hierarchy traversal, embedding, vector search, and evidence reconstruction |
| `bdrel` | `document_relations` | Core | `(from_doc_id, relation_type, to_doc_id)` | Human-governed directed relationships between source files |
| `braw` | `raw` | Audit, optional | `(doc_id, ordinal_raw)` | Near-raw Unstructured output retained for traceability; it is not in the normal query contract |
| `bent` | `entities` | Graph, optional | `(doc_id, entity_id)` | Canonical entities extracted inside a document |
| `belnk` | `entity_links` | Graph, optional | `(doc_id, link_id)` | Entity mentions linked to nodes/sections |
| `brel` | `entity_relations` | Graph, optional | `(doc_id, relation_id)` | Entity-to-entity relations with source block/node evidence |

The UI groups the active tables as follows:

- Core: `bdoc + bblk + bnode + bdrel` (always enabled together by the current pipeline contract).
- Audit: `braw` (independent optional table, enabled by default).
- Graph: `bent + belnk + brel` (always enabled together by the current pipeline contract).
- Mandatory tables still produce a header-only CSV when their row count is zero. The load stage creates and verifies the empty table without sending that CSV to the Teradata batch loader.

### Logical Join Contract

These are application-level foreign-key rules. Teradata does not need physical `FOREIGN KEY` constraints, but preprocessing integrity validation and external clients must honor the same joins.

| From | To | Join | Requirement |
|---|---|---|---|
| `bblk` | `bdoc` | `bblk.doc_id = bdoc.doc_id` | Required |
| `bnode` | `bdoc` | `bnode.doc_id = bdoc.doc_id` | Required |
| child `bnode` | parent `bnode` | `(child.doc_id, child.parent_node_id) = (parent.doc_id, parent.node_id)` | Required except the document root |
| `bnode` | `bblk` | `(bnode.doc_id, bnode.source_element_id) = (bblk.doc_id, bblk.element_id)` | Required except the document root |
| `bdrel` source | `bdoc` | `bdrel.from_doc_id = bdoc.doc_id` | Required |
| `bdrel` target | `bdoc` | `bdrel.to_doc_id = bdoc.doc_id` | Required |
| `bent` | `bdoc` | `bent.doc_id = bdoc.doc_id` | Required when Graph is enabled |
| `belnk` | `bdoc` | `belnk.doc_id = bdoc.doc_id` | Required when Graph is enabled |
| `belnk` | `bnode` | `(belnk.doc_id, belnk.node_id) = (bnode.doc_id, bnode.node_id)` | Required when Graph is enabled |
| `belnk` section | `bnode` | `(belnk.doc_id, belnk.section_node_id) = (bnode.doc_id, bnode.node_id)` | Optional |
| `belnk` | `bent` | `(belnk.doc_id, belnk.entity_id) = (bent.doc_id, bent.entity_id)` | Required when Graph is enabled |
| `brel` | `bdoc` | `brel.doc_id = bdoc.doc_id` | Required when Graph is enabled |
| `brel` | `bblk` | `(brel.doc_id, brel.source_element_id) = (bblk.doc_id, bblk.element_id)` | Required when Graph is enabled |
| `brel` source node | `bnode` | `(brel.doc_id, brel.source_node_id) = (bnode.doc_id, bnode.node_id)` | Required when Graph is enabled |
| `brel` section | `bnode` | `(brel.doc_id, brel.section_node_id) = (bnode.doc_id, bnode.node_id)` | Optional |
| `brel` from entity | `bent` | `(brel.doc_id, brel.from_entity_id) = (bent.doc_id, bent.entity_id)` | Required when Graph is enabled |
| `brel` to entity | `bent` | `(brel.doc_id, brel.to_entity_id) = (bent.doc_id, bent.entity_id)` | Required when Graph is enabled |

The executable source of truth is `BOOKRAG_RELATIONSHIP_SPECS` in `app/services/bookrag_schema.py`. `GET /api/bookrag/schema` serializes that same contract for MCP-capable clients.

### Document Relationship Table (`bdrel`)

`bdrel` is separate from `bdoc` because one document can have zero, one, or many directed relationships, including multiple relationship types to the same target. Adding repeated relationship columns to `bdoc` would make this many-to-many model difficult to validate and edit.

Columns:

| Column | Meaning |
|---|---|
| `from_doc_id`, `to_doc_id` | Authoritative relationship endpoints; both must exist in `bdoc` and must be different |
| `from_filename`, `to_filename` | Human-readable snapshots copied/canonicalized from `bdoc`; display/edit aids only, never join keys |
| `relation_type` | One of `summary_of`, `next_issue_of`, `updates`, `supplement_to`, `follow_up_to`, `references`, `related_to` |
| `relation_description` | Human-readable business explanation used as retrieval context |
| `source_type` | Provenance: `human`, `rule`, `import`, or `llm` |
| `created_by`, `created_at`, `updated_by`, `updated_at` | Audit fields maintained during persistence/editing |

Relationship direction is meaningful. For example, `A summary_of B` means A is the summary and B is the full report; `A next_issue_of B` means A is the newer issue and B is the preceding issue. A row cannot point to itself. Duplicate `(from_doc_id, relation_type, to_doc_id)` values are rejected.

Create-time filename initialization is deliberately conservative:

- `②` summary and `①` full report with the same issue become a `summary_of` relationship.
- `①` full reports, `②` summaries, and `③/④` monthly updates are ordered by the issue date and become `next_issue_of` relationships.
- Spot (`⑤`) and Topics (`⑥`) reports are not assigned semantic relationships automatically; a person must classify them.
- The upload panel remains file-only. After `bdoc` is complete, valid filename-rule relationships are inserted into `bdrel` with both document IDs, both canonical filenames, a relationship description, and `source_type=rule`.
- Every row in `bdrel` is effective and included in normal retrieval. Incorrect relationships must be edited or deleted.
- A document with no defensible relationship remains only in `bdoc`; the pipeline never creates a self-relation or another placeholder relationship merely to give every document a `bdrel` row.

### Creation and Persistence Flow

The **Document Parsing** action below **3. Enrichment Nodes** submits the current BookRAG parsing settings and all uploaded documents, runs the concurrent Unstructured-to-JSON stage, and reports per-file success, element count, and elapsed time. It stores a `manifest.json` beside the per-document JSON files with stable document metadata and JSON checksums. The generated raw JSON is the reusable source artifact for later CSV generation; this stage does not create CSV files, prepare Teradata tables, or write database rows.

The **Generate CSV from JSON** action can select any locally stored parsing manifest in `ready` status and requires an explicit target Vector Store name and target database. It verifies every JSON checksum and runs the shared JSON-to-table-row algorithm concurrently for all documents. Every document produces Core/Audit/Graph CSV files, including header-only Graph files when no entity rows exist. After every document finishes, the stage creates exactly one run-level `bdrel` CSV from cross-document relationship rules, also header-only when no relationships exist. Each generation creates a new CSV run directory and manifest containing the target name, schema, and complete physical-table mapping, so rerunning after an algorithm change never overwrites an earlier result. A CSV run is marked `ready` only when every document and the run-level CSV succeed; this stage never invokes Unstructured and never writes database rows.

The **Load CSV to Tables** action accepts only a `ready` CSV manifest. It validates every CSV path, checksum, table key, row count, and header before creating the mapped BookRAG tables. CSV files load concurrently, and persisted table counts must match the manifest before the run is marked table-ready. This stage never creates a Vector Store.

After table loading succeeds, the existing **Basic > Vector Store Name** field becomes a dropdown of table-ready runs. Selecting a run keeps the normal Search Algorithm, Rerank, and other create settings, and the existing bottom **Create Vector Store** button reads the verified load summary without loading CSV again. The server uses the manifest's target name and qualified `bnode` table as `object_names`, with `content` as the data column and `doc_id,node_id` as key columns. A CSV load or row-count failure therefore prevents that run from appearing in the dropdown.

1. Upload saves each file under its UUID `doc_id` and records `{doc_id, filename, saved_path}` in the document manifest.
2. The upload UI stops at the file catalog; it does not render or submit document relationships.
3. Unstructured jobs run concurrently (default `5`; override with `BOOKRAG_UNSTRUCTURED_WORKERS`). Each completed job writes its fixed per-file raw JSON stage file. The pipeline waits for every JSON job before continuing.
4. After the JSON barrier, files are transformed concurrently (default `5`; override with `BOOKRAG_CSV_PREPARE_WORKERS`). Each JSON keeps the existing fixed per-file/per-table CSV mapping; CSV files are neither merged nor split. The pipeline waits for every CSV to be ready before loading any rows.
5. After the CSV barrier, all prepared CSV load tasks run concurrently (default `5`; override with `BOOKRAG_CSV_LOAD_WORKERS`) and their results are collected together.
6. After all documents exist in `bdoc`, the pipeline creates `bdrel` like the other Core tables, derives conservative filename-rule relationships, validates both endpoints against `bdoc`, and inserts them as effective rows.
7. When the embedding option is enabled, `VectorStore.create()` uses the physical `bnode` table, `content` as data, and `(doc_id, node_id)` as its composite key. When disabled, table preprocessing completes without vector creation.

`bdoc.source_file` stores the original uploaded document path. `page_count` is derived from the maximum extracted block page, `language_hint` records the configured OCR languages when present, and `created_at` records when the document row was built. Raw JSON stage paths remain available in the preprocessing summary/debug artifacts and are not stored as the source document path.

Unstructured processing is concurrent, but job submission is rate-limited separately. EVSUI spaces submissions by 1.35 seconds and, when the service returns HTTP 429, follows `retry_after` with an additional safety margin and retries up to six times. A transient submission limit must not fail the complete multi-file run.

If preprocessing fails after BookRAG tables have been created but before any rows are inserted, retrying with the same vector store name reuses each empty table after validating that all columns required by the current table contract are present. A table with existing rows, an unverifiable row count, or incompatible columns is never reused; choose a new vector store name in those cases.

CSV loading uses native Teradata driver protocols. A CSV with fewer than `BOOKRAG_CSV_FASTLOAD_MIN_ROWS` rows (default `100000`) uses the driver's `teradata_read_csv` path; larger CSVs use `teradataml.read_csv(..., use_fastload=True)`. The application term “batch” refers to one completed per-file result summary and is not a Teradata product/protocol name.

### Retrieval Contract

For applications that use the EVSUI retrieval API:

1. Vector similarity returns a composite `(doc_id, node_id)` match from `bnode`.
2. Retrieval loads the matched node and its ancestor nodes from `bnode` using document-scoped keys.
3. It resolves the source element from `bblk` and document metadata from `bdoc`.
4. It loads every matching `bdrel` row in both directions and adds `direction`, `related_doc_id`, `related_filename`, type, and description to each evidence package and the LLM context.
5. When Graph tables exist, entity mentions and relations are attached using the composite joins above.

For external MCP/SQL applications, call `GET /api/bookrag/schema?vector_store_name=<name>&schema_name=<schema>` and use the returned physical table names, primary keys, roles, and relationships. Do not infer table names, omit `doc_id` from joins, or use filenames as keys.

### Administration and Migration

- **Vector Store Creation -> Upload PDF / Documents** is file upload only. `bdrel` is created during Create together with `bdoc`, `bblk`, and `bnode`.
- Create-time filename-rule rows are effective immediately. Use **Administration -> Business Configuration -> Document Relationships** to load, review, add, edit, delete, import, or export rows.
- The Document Relationships panel refreshes its own Vector Store list on load and provides **Refresh Vector Stores**; it does not depend on running the Retrieval page's list action first.
- If an older vector store has `bdoc` but no `bdrel`, click **Initialize bdrel**. This only creates the empty table after verifying that `bdoc` contains documents; it does not invent relationships.
- When an existing legacy `bdrel` table is next initialized or changed, obsolete `is_active` and `confidence` columns are dropped without deleting rows. Retrieval already treats every legacy row as effective.
- CSV import may identify endpoints by `doc_id`. A filename-only import is accepted only when that filename is present and unique in `bdoc`; stored filenames are then canonicalized from `bdoc`.
- Adding or changing `bdrel` rows does not require re-running Unstructured or rebuilding embeddings because document relationships are loaded at retrieval time.
- New uploads use stable upload-instance UUIDs throughout one create flow. Re-uploading or rebuilding from a newly generated manifest assigns new IDs, so any external references or imported `bdrel` rows must be remapped to the new `bdoc.doc_id` values.

### LLM-Readable Summary

```yaml
api_version: bookrag-v1
documentation_revision: 2026-07-14
identity:
  document: [doc_id]
  vector: [doc_id, node_id]
embedding:
  table_key: nodes
  suffix: bnode
  data_columns: [content]
  key_columns: [doc_id, node_id]
tables:
  core: [documents, blocks, nodes, document_relations]
  audit_optional: [raw]
  graph_optional: [entities, entity_links, entity_relations]
inactive_legacy_targets: [chunks, leaf_nodes]
document_relations:
  suffix: bdrel
  primary_key: [from_doc_id, relation_type, to_doc_id]
  authoritative_endpoints: [from_doc_id, to_doc_id]
  display_only: [from_filename, to_filename]
  retrieval_filter: none
client_rules:
  - obtain physical names from GET /api/bookrag/schema
  - always include doc_id in document-scoped joins
  - treat filenames as labels, never identifiers
  - use bnode rather than bleaf for embedding and retrieval
```

## Multi Format Config

- For local debugging, copy `app/config/local_dev.example.json` to `app/config/local_dev.json` and fill in `unstructured`.
- `app/config/local_dev.json` is ignored by Git and must not be committed.
- Users can override Unstructured IO settings for their active session from the Admin Rules page.
- Multi Format and Multi-Format BookRAG use session Unstructured IO settings first, then fall back to `app/config/local_dev.json`.
- Supported API key fields: `api_key`, `key_id`, `UNSTRUCTURED_API_KEY`, `UNSTRUCTURED_API_KEY_AUTH`
- Supported API URL fields: `api_url`, `UNSTRUCTURED_API_URL`, `UNSTRUCTURED_PLATFORM_URL`
- Unstructured does not currently expose a public Workflow models-list endpoint in the documented API or Python SDK. EVSUI ships with an internal fallback model catalog and can load overrides from `app/config/unstructured_models.json` or `UNSTRUCTURED_MODEL_CATALOG_PATH`.
- To update UI model choices without code changes, copy `app/config/unstructured_models.example.json` to `app/config/unstructured_models.json` and edit the `partitioner_vlm`, `enrichment`, or `table_to_html` sections.

Example:

```json
{
  "unstructured": {
    "api_key": "your-unstructured-api-key",
    "api_url": "https://platform.unstructuredapp.io/api/v1"
  }
}
```

- Optional runtime env:
  - `UNSTRUCTURED_WORKFLOW_POLL_SECONDS` (default: `1800`)
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

## BookRAG API Notes

- `GET /api/bookrag/schema?vector_store_name=...&schema_name=...` returns the authoritative physical table names, primary keys, table roles, and logical join contract for MCP/SQL clients.
- `GET /api/bookrag/retrieve` with no query parameters returns a dummy connectivity payload.
- `GET /api/bookrag/retrieve?question=...&vector_store_name=...` runs a real retrieval.
- `POST /api/bookrag/retrieve` runs a real retrieval from a JSON body with `question` and `vector_store_name`.
- API access accepts either the normal EVSUI login session cookie or `Authorization: Bearer <token>` / `x-api-key: <token>` when `EVSUI_API_TOKEN` is configured.

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

- For local debugging, configure login defaults in `app/config/local_dev.json`.
- If values are absent, the login page and connection form are left blank for the user to fill in.
- `app/config/auth_users.json` is still supported for local user lists, but it is ignored by Git.

```json
{
  "login": {
    "username": "admin",
    "password": "change-me",
    "users": {
      "alice": "alice-pass",
      "bob": "bob-pass"
    }
  }
}
```

- Connection defaults can be configured in the same local file:

```json
{
  "connection": {
    "host": "db-host",
    "username": "db-user",
    "password": "db-password",
    "ues_url": "https://example/open-analytics",
    "pat_token": "ccp-token",
    "pem_file": "uploads\\pem\\debug.pem"
  }
}
```

- Optional:
  - `POC_AUTH_FILE` to point to a different JSON file path.
  - Fallback single-user env vars: `POC_ADMIN_USER`, `POC_ADMIN_PASSWORD` (used only when config file has no users).

- Multi-user isolation:
  - Each login gets its own session (`evsui_sid`) and independent UI state, including Unstructured IO settings.

## Project Structure

- Application entry and routes: `app/main.py`
- Local debug config example: `app/config/local_dev.example.json`
- Service layer:
  - `app/services/create_config.py` (create form schema/coercion)
  - `app/services/multi_format.py` (multi-format preprocessing pipeline)
  - `app/services/bookrag_schema.py` (BookRAG table schemas, primary keys, and external relationship contract)
  - `app/services/bookrag_document_relations.py` (`bdrel` suggestion, validation, persistence, and CRUD)
  - `app/services/bookrag_integrity.py` (per-document relationship validation before persistence)
  - `app/services/bookrag_retrieval.py` (document-scoped evidence reconstruction and relationship enrichment)
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
- `POST /ui/admin/unstructured-config`
- `GET /ui/admin/document-relations`
- `POST /ui/admin/document-relations/initialize`, `/save`, `/delete`, `/import`
- `GET /ui/admin/document-relations/export`
- `GET /api/bookrag/schema`, `GET|POST /api/bookrag/retrieve`
- `GET /healthz`

## Health Check

`GET /healthz` returns:

```json
{"status":"ok"}
```
