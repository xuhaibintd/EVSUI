# EVSUI Architecture

## Design constraints

EVSUI is a server-rendered FastAPI application around Teradata Vector Store. The Teradata Python SDK uses process-global context, so this release intentionally supports one web worker per application instance. `TeradataRuntimeManager` serializes SDK operations and reactivates the selected connection profile before work. Increasing `WEB_CONCURRENCY` is rejected at startup instead of silently mixing user contexts.

SQLite is the application control-plane database. It stores identity, server sessions, encrypted connection profiles, encrypted external-service credentials, durable job state, artifact metadata, and audit records. Vector data and BookRAG tables remain in Teradata; large documents and generated artifacts remain on the filesystem.

## Module boundaries

| Layer | Modules | Responsibility |
|---|---|---|
| Application | `app/main.py`, `app/core/` | App factory, settings, security, error handling, runtime isolation |
| Delivery | `app/routers/`, `app/templates/`, `app/static/` | HTTP contracts, HTMX fragments, presentation |
| Workflows | `app/workflows/` | Connect/create/retrieve/destroy orchestration |
| Services | `app/services/` | BookRAG, multi-format processing, credentials, jobs, artifacts |
| Integrations | `app/integrations/`, `app/teradata_runtime.py` | Teradata and Unstructured adapters |
| Persistence | `app/repositories/`, `app/db/` | SQLite repositories, migrations, online backup |

Dependencies point inward: routers call workflows/services, which call repositories and integration adapters. Templates do not access SQLite directly. Secrets are decrypted only when a runtime operation requires them and are never rendered back into password fields.

## Runtime state

- Persisted: users, roles, session hashes, database connection profiles, Unstructured configuration, jobs, artifacts, audit events.
- Per browser session: selected connection, connected/disconnected state, current uploads, form values, chat history.
- Process global: active Teradata SDK context, protected by serialization and context reactivation.
- External: vector stores and BookRAG tables in Teradata; Unstructured workflow execution in its API.

## Extension rules

1. Add schema changes only as a new numbered migration; never rewrite an applied migration.
2. Put new SQLite queries in a repository, not in templates or JavaScript.
3. Put external SDK calls behind an integration/service boundary.
4. Register generated files with `ArtifactLifecycle`; destructive cleanup remains disabled by default.
5. Use persistent jobs for work that must survive a web request or process restart. A separate worker process should own those handlers.
6. Do not add a second web worker until Teradata execution has been moved to isolated worker processes or another context-safe boundary.

## Known next boundary

Document parsing and vector creation currently use thread offloading but the browser request still waits for completion. The durable job foundation is in place; moving those workflows to the worker requires stable, serializable command payloads and UI polling. That conversion should be done workflow-by-workflow, without placing plaintext credentials in job payloads.
