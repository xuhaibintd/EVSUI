"""Opt-in read-only SDK smoke check using a disposable SQLite snapshot.

No login sessions, application records, remote objects, or source uploads are
created/updated/deleted. SDK connections and SELECT 1/list/health are exercised.
Raw SDK output is suppressed because third-party diagnostics may contain secrets.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def check_snapshot(snapshot: Path, profile_id: int | None) -> dict:
    from app.auth_store import AuthStore
    from app.core.settings import Settings
    from app.integrations.teradata import activated_connection
    from app.teradata_runtime import VSManager

    settings = Settings.from_env()
    store = AuthStore(snapshot, credential_key=settings.credential_key,
                      credential_key_file=settings.credential_key_file,
                      pem_runtime_dir=snapshot.parent / "pem",
                      allow_generated_credential_key=False)
    profiles = store.list_connection_profiles()
    selected = next((item for item in profiles if item["id"] == profile_id), None) if profile_id else next(iter(profiles), None)
    if selected is None:
        return {"status": "blocked", "stage": "configuration", "reason": "No matching saved connection profile."}
    result = {"profile_id": selected["id"], "checks": {}}
    stage = "connect_and_authenticate"
    try:
        with activated_connection(store, selected["id"]) as runtime:
            result["checks"][stage] = "passed"
            stage = "select_constant"
            cursor = runtime["execute_sql"]("SELECT 1")
            row = cursor.fetchone()
            if not row or int(row[0]) != 1:
                raise RuntimeError("Unexpected constant query result")
            result["checks"][stage] = "passed"
            stage = "vector_store_list"
            VSManager.list()
            result["checks"][stage] = "passed"
            stage = "vector_store_health"
            VSManager.health()
            result["checks"][stage] = "returned_without_exception"
        result["status"] = "passed"
    except Exception as error:
        # Intentionally omit raw exception text: SDK errors can echo credentials.
        result.update(status="failed", stage=stage, error_type=type(error).__name__)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only-live", action="store_true", help="Explicitly allow remote read-only SDK requests")
    parser.add_argument("--profile-id", type=int)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--snapshot-worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.read_only_live:
        parser.error("--read-only-live is required; default test runs never contact external services")
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    if args.snapshot_worker:
        logging.disable(logging.CRITICAL)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                result = check_snapshot(args.snapshot_worker, args.profile_id)
            except Exception as error:
                result = {"status": "failed", "stage": "snapshot_configuration", "error_type": type(error).__name__}
        print(json.dumps(result))
        return 0 if result["status"] == "passed" else 1

    from app.core.settings import Settings
    settings = Settings.from_env()
    with tempfile.TemporaryDirectory(prefix="evsui-live-readonly-") as directory:
        snapshot = Path(directory) / "snapshot.db"
        source = sqlite3.connect(settings.database_path.as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(snapshot)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        command = [sys.executable, str(Path(__file__).resolve()), "--read-only-live", "--snapshot-worker", str(snapshot)]
        if args.profile_id is not None:
            command += ["--profile-id", str(args.profile_id)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout, check=False)
            try:
                result = json.loads(completed.stdout)
            except (TypeError, ValueError):
                result = {"status": "failed", "stage": "sdk_process", "reason": "No safe structured result returned."}
        except subprocess.TimeoutExpired:
            result = {"status": "timeout", "stage": "sdk_process", "timeout_seconds": args.timeout}
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
