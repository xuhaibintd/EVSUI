# teradataevsui Operations

## Windows: unified start / stop / restart / status

After creating `.venv` and installing `requirements.txt`, run these from the project root:

```powershell
.\start.cmd       # Start web + one worker; default http://127.0.0.1:8010
.\status.cmd      # Show readiness, actual PIDs, and log paths
.\stop.cmd        # Request graceful shutdown of both services
.\restart.cmd     # Stop successfully first, then start; preserve the saved web port
```

The scripts resolve their paths from their own location, so they also work when
called from another directory or when the project path contains spaces. Background
services do not open console windows. `.venv` must already exist; lifecycle commands
do not install dependencies, delete data, or pull code.

Advanced options are forwarded to `scripts/teradataevsui.ps1` (the old `scripts/evsui.ps1` forwards to it for compatibility):

```powershell
.\start.cmd -Component web               # Web only; do not consume the job queue
.\start.cmd -Component worker            # Worker only, using the same saved/environment configuration
.\stop.cmd -Component worker -Timeout 60
.\restart.cmd -Port 8011
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\teradataevsui.ps1 status
```

Parameters: `-Component all|web|worker` (default `all`), `-Port` (default 8010 for
first launch, then the saved port), `-BindAddress 127.0.0.1|0.0.0.0` (default loopback),
and `-Timeout` (default 30 seconds). Start timeout applies to each newly started
component; stop timeout covers the whole drain. Binding `0.0.0.0` exposes the service
to the network and should only be used with appropriate firewall/proxy controls.

### Queue and shutdown behavior

- **Starting Worker executes already queued jobs**, and may recover stale interrupted
  jobs under the existing recovery policy. Use `-Component web` when only inspecting data.
- Stop signals the web service and Worker cooperatively. Web closes its listener and
  drains active requests; Worker finishes its current job and does not claim the next.
- If work has not drained before the timeout, exit code **2** means “stop requested,
  still stopping.” The request remains effective after the script exits. Check status
  later. Restart does not launch a second instance while the old one is draining.
- No `taskkill`, process-name kill, PID-based force kill, queue cancellation, table deletion,
  or upload cleanup is performed. Even a stale/recycled PID is not a stop target.
- Repeating start/stop is safe. A busy/unmanaged web port is reported, never taken over.
  Stop a previously launched manual `uvicorn` process in its original terminal before
  switching to managed scripts. Status explicitly identifies an unmanaged listener.
- A database-scoped OS lock prevents a second updated `app.worker` process, including
  manual CLI launches. Old workers started before this lock was introduced must be
  stopped explicitly first. This is a local-process guard, not a distributed lock service.
- Failed startup requests shutdown only for components launched by that command;
  already-running components are preserved. A timed-out startup may briefly report
  `starting`/`stopping` while its shutdown completes.

### Configuration, logs and exit codes

Both processes inherit the same current terminal environment (`EVSUI_*`,
`WEB_CONCURRENCY=1`). These scripts do not parse `.env` or put secrets in command
arguments/status records. Set environment variables before launch; a settings hash
prevents starting a second component with a different database/key/configuration.
Stop **both** services before changing settings. Relative configured paths resolve
from the project root.

Runtime ownership records and token-specific stop requests are in `.run/`; per-launch
logs are in `.run/logs/`. They are excluded from Git. Do not delete `.run/`, database
worker lock files, or change the runtime directory while services are running.
Lock ownership is released by the OS on exit/crash; old files need not be removed.
Logs are retained for troubleshooting and are not automatically deleted.

Exit codes: **0** completed/status displayed, **1** startup/configuration/ownership
error, **2** graceful stop still pending. `status` is informational and returns 0;
read its component statuses to distinguish running, unhealthy, failed, stopped and
unmanaged listener states.

Verification: `python -m unittest tests.test_service_control -v` starts actual child
processes from an isolated source copy and disposable SQLite database. It covers
idempotent lifecycle, port conflicts, startup timeout/rollback, configuration
mismatch, paths with spaces, duplicate workers and graceful draining of an actual
queued fixture job. No real external work is performed by those tests.

Use the [testing guide](testing.md) to reproduce validation. Keep results from
individual runs separate from this maintained operations guide.

## Local development

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m app.db migrate
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

Run the durable workflow worker in a second terminal:

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

Document parsing, CSV generation/loading, and Vector Store creation remain queued until a worker is running. The web process never executes these long operations inline.

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

Current schema version 9 contains:

| Table | Purpose |
|---|---|
| `schema_versions` | Applied migration history |
| `users`, `sessions`, `permissions`, `audit_logs` | Identity, access, opaque server sessions, and audit events |
| `system_connection_profiles` | Reusable Teradata profiles with encrypted password, PAT, and PEM |
| `external_service_configs` | Shared service endpoints and encrypted API keys, currently Unstructured IO |
| `jobs` | Durable queued/running/completed state, progress, and transient encrypted job secrets |
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

The same cleanup can run through the durable job table. `app.ops run-jobs` is a bounded maintenance drain; the continuous application worker is `app.worker`:

```powershell
.\.venv\Scripts\python.exe -m app.ops enqueue-artifact-cleanup
.\.venv\Scripts\python.exe -m app.ops run-jobs
.\.venv\Scripts\python.exe -m app.ops jobs
.\.venv\Scripts\python.exe -m app.worker --once
```

The worker runs one job at a time because the Teradata SDK context is process-global. It records a heartbeat every 30 seconds even while an SDK call is blocking. On startup, jobs whose heartbeat is older than `EVSUI_JOB_STALE_SECONDS` are returned to the queue. Queued jobs can be cancelled from the UI; already-running external operations are not force-killed.

Vector Store readiness is polled every `EVS_VECTORSTORE_READY_POLL_SECONDS` (default 5 seconds) for at most `EVS_VECTORSTORE_READY_TIMEOUT_SECONDS` (default 7200 seconds). A timeout marks the job failed but does not cancel remote work that Teradata has already accepted, so verify remote status before retrying.

Only tracked, expired files below `uploads/` are eligible. Existing untracked files are never automatically registered or deleted.

## Production requirements

- Set `EVSUI_ENVIRONMENT=production`.
- Set `WEB_CONCURRENCY=1`.
- Provide `EVSUI_CREDENTIAL_KEY` or an explicit, pre-created `EVSUI_CREDENTIAL_KEY_FILE`.
- Mount persistent storage for `data/`, `uploads/`, and `pem_runtime/`.
- Run exactly one `app.worker` process against each deployment database unless job kinds are explicitly partitioned.
- Terminate HTTPS at a trusted reverse proxy and preserve `Host`, `Origin`, and `X-Forwarded-Proto` correctly.
- Enable the external API only when needed with `EVSUI_EXTERNAL_API_ENABLED=true` and a strong `EVSUI_API_TOKEN`.
- Schedule online database backups and dry-run artifact inventory before enabling cleanup.

`compose.yaml` starts both the web application and its durable worker with the same SQLite, upload, PEM-runtime mounts, and credential key. Do not scale the worker above one while Teradata handlers share process-global SDK state.
