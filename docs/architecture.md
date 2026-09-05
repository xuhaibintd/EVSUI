# teradataevsui Architecture

## Design constraints

teradataevsui is a server-rendered FastAPI application around Teradata Vector Store. The Teradata Python SDK uses process-global context, so the application intentionally runs as one process. `TeradataRuntimeManager` serializes interactive and background SDK operations and reactivates the selected connection profile before work. A FastAPI-managed background runner executes durable jobs one at a time. Increasing `WEB_CONCURRENCY` is rejected, and a database-scoped application lock also prevents multiple server processes from sharing the same runtime database.

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
| Background jobs | `app/services/job_worker.py`, `app/services/workflow_jobs.py` | Durable execution, heartbeat, restart recovery |

Dependencies point inward: routers call workflows/services, which call repositories and integration adapters. Templates do not access SQLite directly. Secrets are decrypted only when a runtime operation requires them and are never rendered back into password fields.

## Runtime state

- Persisted: users, roles, session hashes, database connection profiles, Unstructured configuration, jobs, artifacts, audit events.
- Per browser session: selected connection, connected/disconnected state, current uploads, form values, chat history.
- Process global: one active Teradata SDK context. Interactive operations and the background runner share one runtime lock; jobs execute one at a time and clean the context after every Teradata operation.
- External: vector stores and BookRAG tables in Teradata; Unstructured workflow execution in its API.

## Extension rules

1. Add schema changes only as a new numbered migration; never rewrite an applied migration.
2. Put new SQLite queries in a repository, not in templates or JavaScript.
3. Put external SDK calls behind an integration/service boundary.
4. Register generated files with `ArtifactLifecycle`; destructive cleanup remains disabled by default.
5. Use persistent jobs for work that must survive a web request. FastAPI owns the single background runner; HTTP routes only validate/enqueue and render progress.
6. Do not add another application process until Teradata execution has a distributed context-safe boundary.

## Durable workflow boundary

Document parsing, JSON-to-CSV generation, CSV table loading, and Vector Store creation use stable JSON command payloads and browser polling. Payloads contain connection-profile IDs, not passwords, PATs, PEM contents, or external API keys. The background runner decrypts credentials only when a handler needs them. Queued/running/succeeded/failed/cancelled state and progress survive web restarts; stale running jobs are recovered on application startup.

Recovery reclaims a job; it does **not** guarantee transactionally resumable external operations. An interrupted CSV load must be inspected after confirming its previous loader has stopped; the application refuses automatic destructive retry. Start a new run explicitly after resolving the target tables. A monitoring timeout does not cancel a remote Vector Store operation; subsequent creation first checks the existing store and verifies its index.

CSV load manifests bind to the selected connection-profile ID and a non-secret target fingerprint (host, username, UES URL). Cached load success cannot be reused for a different profile or a changed target on the same profile; password/PAT/PEM rotation alone does not invalidate it. Legacy load records without that binding must be inspected and replaced with an explicit new run, since their database identity cannot be proven. Atomic job claims and stale-attempt fencing protect each job, while the single application runner prevents concurrent jobs from targeting the same SDK context.
