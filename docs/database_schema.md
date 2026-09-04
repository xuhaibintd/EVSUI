# SQLite Control-Plane Schema

EVSUI schema version 9 is created and upgraded from `app/db/migrations.py`. The runtime file `data/evsui.db` is intentionally not committed: source control contains the reproducible schema, while each environment owns its users, sessions, encrypted credentials, jobs, and audit history.

| Table | Primary key | Main relationships and purpose |
|---|---|---|
| `schema_versions` | `version` | Records each applied numbered migration |
| `users` | `id` | Account, Argon2 password hash, role, enabled/lockout state, login timestamps |
| `sessions` | `session_id_hash` | `user_id → users.id`; server-side expiring/revocable sessions |
| `permissions` | `id` | `user_id → users.id`; resource-scoped read/write/admin grants |
| `audit_logs` | `id` | Optional `user_id → users.id`; security and administration events |
| `system_connection_profiles` | `id` | Reusable named Teradata profiles; one may be default |
| `external_service_configs` | `service_name` | Shared external service endpoint and encrypted API key |
| `jobs` | `id` | `owner_user_id → users.id`, `connection_profile_id → system_connection_profiles.id`; durable workflow state, progress, heartbeat, command/result JSON |
| `artifacts` | `id` | Optional `job_id → jobs.id`, `owner_user_id → users.id`; generated/uploaded file inventory and expiry |
| `connection_configs` | `user_id` | Legacy per-user connection compatibility table |
| `system_connection_config` | `config_id=1` | Legacy singleton connection compatibility table |

Sensitive columns are encrypted with the deployment Fernet key:

- `system_connection_profiles.password_ciphertext`, `pat_token_ciphertext`, and `pem_ciphertext`
- `external_service_configs.api_key_ciphertext`
- `jobs.secret_payload_ciphertext` for transient form secrets such as an optional VLM provider key

Job secret ciphertext is cleared when a job succeeds, fails, or is cancelled. PEM content is stored encrypted in SQLite and materialized into the ignored, restricted `pem_runtime/` directory when the SDK needs a file path. Back up the credential key with the database; the database alone cannot decrypt these values.

Create or upgrade a database and inspect migration state with:

```powershell
python -m app.db migrate
python -m app.db status
```

Use the online backup command for a live database:

```powershell
python -m app.db backup
```
