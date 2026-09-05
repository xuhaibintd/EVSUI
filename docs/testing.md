# teradataevsui testing

Tests are split deliberately: unit/service regressions, actual HTTP route contracts,
actual browser actions, and an **opt-in read-only** external connection check.
A green unit suite alone is not acceptance of a working browser workflow.

## Run locally (PowerShell)

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pip install -e ".[browser]"
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m ruff check app tests scripts
.venv\Scripts\python.exe -m compileall -q app scripts
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Browser tests are skipped by default. They **must also be run** for UI changes:

```powershell
$env:EVSUI_BROWSER_TESTS = "1"
# Optional: use installed Microsoft Edge instead of downloaded Chromium.
$env:EVSUI_BROWSER_CHANNEL = "msedge"
.venv\Scripts\python.exe -m unittest tests.test_browser_actions tests.test_frontend_parameters -v
```

For all tests plus Python branch coverage in one process:

```powershell
$env:EVSUI_BROWSER_TESTS = "1"
$env:EVSUI_BROWSER_CHANNEL = "msedge"
.venv\Scripts\python.exe -m coverage run -m unittest discover -s tests -q
.venv\Scripts\python.exe -m coverage report
.venv\Scripts\python.exe -m coverage json -o test-results/coverage.json
```

CI runs both the non-browser suite and browser suites using installed Chromium.
Browser request status evidence and screenshots are written under `test-results/`
and uploaded by CI. Runtime data and reports from individual runs are not committed.
Tests fail on uncaught browser JavaScript errors, including CSP execution failures.

## What the browser tests actually exercise

`tests/e2e_support.py` starts a real local Uvicorn/FastAPI server on an ephemeral
port with production routers, middleware, Jinja templates, HTMX and JavaScript.
Users, encrypted profiles, sessions, jobs and uploaded files use disposable SQLite
and temporary directories. Teradata and Unstructured **service boundaries** are
deterministic fixtures; browser events, HTTP responses and authentication are not mocked.
Staged workflow tests complete real SQLite jobs with controlled service results,
then verify actual browser polling and the next form actions.

| Area | Browser actions | Backend/service checks |
|---|---|---|
| Authentication | Failed login, login, logout, role-specific navigation | Anonymous rejection, disabled users, password reset/import session revocation, last-admin protection |
| System Configuration | Connection create/edit/delete cancel+confirm, external key save/keep/clear, user create/role/disable/enable/reset | New profile does not inherit secrets, blank update preserves secrets, invalid PEM/import handling, admin-only mutations |
| Connection management | Connect/disconnect, health, list, row selection, delete cancel+confirm | Runtime activation, session isolation, disconnected and permission guards, destroy verification |
| Creation | Upload, three document modes, routes/providers/models/algorithms/chunking/enrichment, long keys, queue/poll/cancel | Seven job kinds, validation, encrypted commands, partial failures, index readiness, retry/timeout/corrupt-payload handling |
| Staged CSV workflows | Both parse → generate → load → selected loaded run | Manifest contracts, file parsing/conversion, connection binding, interrupted-load refusal |
| Retrieval | List/select, ask, similarity search, BookRAG API mode/top_k/send, clear | GET/POST API validation and response schema, authentication, missing context, session-specific history |
| Metadata governance | Empty-selection refresh, load, edit, CSV export/import, autofill, viewer read-only | Validate entire CSV before writes; invalid/empty/disconnected/unauthorized requests |
| Document relationships | Empty-selection refresh, initialize, add/edit/export/delete | Relation validation, CSV import, persistence/schema rules, permissions |
| JSON Inspector | Filtering, no-result detail clearing/restoration | Allowed roots, path traversal rejection, malformed documents |
| Layout/security | Desktop/laptop/tablet widths, disabled/hidden controls, CSP-safe confirmation and row selection | Origin validation, secret redaction, role downgrade taking effect immediately |
| Persistence/operations | SQLite job progress and cancellation in browser | Migrations/backup, worker claim races, stale-attempt fencing, artifact lifecycle, wheel exclusions |

## Read-only live check

This is **not run in CI or normal test discovery**. It reads a transactionally
consistent snapshot of the configured SQLite file, materializes PEM only in a
temporary directory, and starts a separate SDK process with a deadline:

```powershell
.venv\Scripts\python.exe scripts/check_live_connection.py --read-only-live --timeout 90
# Optional: --profile-id <saved profile ID>
```

Operations are limited to connection/authentication, `SELECT 1`, `VSManager.list()`
and `VSManager.health()`. Raw SDK output and errors are suppressed to avoid leaking
credentials. Health returning without exception is reported as such; it is not an
assertion that every listed store is healthy. Source application records/uploads
are not changed. The helper itself has opt-in, snapshot, timeout and output-safety tests.

## Limits of this acceptance baseline

- No automated test creates/destroys a real Vector Store, overwrites real tables,
  modifies real document metadata, or sends billable parsing/model requests.
- Real remote write acceptance requires a dedicated disposable Teradata database,
  separate test credentials and approved Unstructured/model quota.
- CSV rows are validated before the first write, but this does not guarantee an
  all-or-nothing remote transaction if SQL fails midway.
- Job recovery is not universal external-operation resumption. Inspect interrupted
  CSV loads; do not restart a second loader blindly. Run one workflow worker.
- Python coverage does not measure HTML/JavaScript coverage. Browser scenarios do
  not constitute load testing, penetration testing, or every browser/device combination.

Keep individual execution reports, screenshots, and environment-specific evidence
in ignored local directories or explicitly reviewed CI artifacts, not in public
documentation. See [Publication checks](publishing.md) before submitting changes.
