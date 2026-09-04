# EVSUI Operations

## Local development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m app.db migrate
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

Run the same verification used by CI:

```powershell
.\.venv\Scripts\ruff.exe check app tests
.\.venv\Scripts\python.exe -m compileall -q app
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

## Database lifecycle

`data/evsui.db` is runtime state and is intentionally ignored by Git. A fresh checkout creates it from numbered migrations. Existing installations are upgraded idempotently at startup or explicitly with:

```powershell
.\.venv\Scripts\python.exe -m app.db status
.\.venv\Scripts\python.exe -m app.db migrate
```

Current schema version 8 contains:

| Table | Purpose |
|---|---|
| `schema_versions` | Applied migration history |
| `users`, `sessions`, `permissions`, `audit_logs` | Identity, access, opaque server sessions, and audit events |
| `system_connection_profiles` | Reusable Teradata profiles with encrypted password, PAT, and PEM |
| `external_service_configs` | Shared service endpoints and encrypted API keys, currently Unstructured IO |
| `jobs` | Durable queued/running/completed job state and progress |
| `artifacts` | Tracked file metadata and retention state |
| `connection_configs`, `system_connection_config` | Compatibility tables retained for migration from older releases |

Back up a live SQLite database with its online backup API:

```powershell
.\.venv\Scripts\python.exe -m app.db backup
```

The default destination is `data/backups/`. Back up the credential key together with the database. Without the same Fernet key, encrypted database passwords, PATs, PEM contents, and external API keys cannot be recovered.

## Artifacts and persistent maintenance jobs

Inventory is read-only. Cleanup is also a dry run unless both the environment flag and `--apply` are present.

```powershell
.\.venv\Scripts\python.exe -m app.ops inventory
.\.venv\Scripts\python.exe -m app.ops cleanup-artifacts
$env:EVSUI_ARTIFACT_CLEANUP_ENABLED = "true"
.\.venv\Scripts\python.exe -m app.ops cleanup-artifacts --apply
```

The same cleanup can run through the durable job table:

```powershell
.\.venv\Scripts\python.exe -m app.ops enqueue-artifact-cleanup
.\.venv\Scripts\python.exe -m app.ops run-jobs
.\.venv\Scripts\python.exe -m app.ops jobs
```

Only tracked, expired files below `uploads/` are eligible. Existing untracked files are never automatically registered or deleted.

## Production requirements

- Set `EVSUI_ENVIRONMENT=production`.
- Set `WEB_CONCURRENCY=1`.
- Provide `EVSUI_CREDENTIAL_KEY` or an explicit, pre-created `EVSUI_CREDENTIAL_KEY_FILE`.
- Mount persistent storage for `data/`, `uploads/`, and `pem_runtime/`.
- Terminate HTTPS at a trusted reverse proxy and preserve `Host`, `Origin`, and `X-Forwarded-Proto` correctly.
- Enable the external API only when needed with `EVSUI_EXTERNAL_API_ENABLED=true` and a strong `EVSUI_API_TOKEN`.
- Schedule online database backups and dry-run artifact inventory before enabling cleanup.

Do not run multiple replicas against this process-global Teradata context. Scale by moving Teradata work to isolated worker processes first.
