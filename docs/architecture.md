# teradataevsui Architecture

## Design constraints

teradataevsui is a server-rendered FastAPI application around Teradata Vector Store. The Teradata Python SDK uses process-global context, so this release intentionally supports one web worker per application instance. `TeradataRuntimeManager` serializes interactive SDK operations and reactivates the selected connection profile before work. Long document and vector workflows run in a separate, single-concurrency worker process, which owns its own SDK context. Increasing `WEB_CONCURRENCY` is rejected at startup instead of silently mixing user contexts.

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
| Worker | `app/worker.py`, `app/services/workflow_jobs.py` | Durable command execution, heartbeat, restart recovery |

Dependencies point inward: routers call workflows/services, which call repositories and integration adapters. Templates do not access SQLite directly. Secrets are decrypted only when a runtime operation requires them and are never rendered back into password fields.

## Runtime state

- Persisted: users, roles, session hashes, database connection profiles, Unstructured configuration, jobs, artifacts, audit events.
- Per browser session: selected connection, connected/disconnected state, current uploads, form values, chat history.
- Process global: one active Teradata SDK context per process. Interactive web operations are serialized; the durable worker executes one job at a time and cleans its context after every Teradata job.
- External: vector stores and BookRAG tables in Teradata; Unstructured workflow execution in its API.

## Extension rules

1. Add schema changes only as a new numbered migration; never rewrite an applied migration.
2. Put new SQLite queries in a repository, not in templates or JavaScript.
3. Put external SDK calls behind an integration/service boundary.
4. Register generated files with `ArtifactLifecycle`; destructive cleanup remains disabled by default.
5. Use persistent jobs for work that must survive a web request or process restart. The separate worker process owns those handlers; HTTP routes only validate/enqueue and render progress.
6. Do not add a second web worker until Teradata execution has been moved to isolated worker processes or another context-safe boundary.

## Durable workflow boundary

Document parsing, JSON-to-CSV generation, CSV table loading, and Vector Store creation use stable JSON command payloads and browser polling. Payloads contain connection-profile IDs, not passwords, PATs, PEM contents, or external API keys. The worker decrypts credentials only when a handler needs them. Queued/running/succeeded/failed/cancelled state and progress survive web restarts; stale running jobs are recovered on worker startup.

Recovery reclaims a job; it does **not** guarantee transactionally resumable external operations. An interrupted CSV load must be inspected after confirming its previous loader has stopped; the application refuses automatic destructive retry. Start a new run explicitly after resolving the target tables. A monitoring timeout does not cancel a remote Vector Store operation; subsequent creation first checks the existing store and verifies its index.

CSV load manifests bind to the selected connection-profile ID and a non-secret target fingerprint (host, username, UES URL). Cached load success cannot be reused for a different profile or a changed target on the same profile; password/PAT/PEM rotation alone does not invalidate it. Legacy load records without that binding must be inspected and replaced with an explicit new run, since their database identity cannot be proven. Continue to run **one workflow worker**: atomic job claims and stale-attempt fencing protect a job, but do not provide a distributed lock across different jobs targeting the same CSV run or remote table.
