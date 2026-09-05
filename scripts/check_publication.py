"""Fail when the current Git tree contains material unsuitable for publication."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PATHS = {
    ".env",
    "app/config/auth_users.json",
    "app/config/local_dev.json",
    "app/config/unstructured.json",
    "app/config/unstructured_models.json",
}
PRIVATE_PREFIXES = ("data/", "local-notes/", "pem_runtime/", "test-results/", "uploads/")
PRIVATE_SUFFIXES = (".app.lock", ".db", ".key", ".p12", ".pem", ".pfx", ".sqlite", ".sqlite3")
DATED_INTERNAL_REPORT = re.compile(r"(?:^|/)(?:audit|review|report|testing)[-_]\d{4}", re.IGNORECASE)
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
MACHINE_PATH = re.compile(r"(?i)[A-Z]:[\\/]+(?:Documents and Settings|Users)[\\/]+")
SECRET_PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:EC |OPENSSH |RSA )?PRIVATE KEY-----"),
    "GitHub token": re.compile(rb"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "AWS access key": re.compile(rb"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])"),
    "OpenAI-style key": re.compile(rb"(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{40,}"),
    "JWT": re.compile(rb"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}"),
}
LOCAL_CONFIGS = (
    "app/config/auth_users.json",
    "app/config/local_dev.json",
    "app/config/unstructured.json",
)
SENSITIVE_LOCAL_KEYS = {
    "api_key", "host", "password", "pat_token", "pem_file", "secret", "token", "ues_url", "username"
}
REQUIRED_DOCKER_IGNORES = {
    ".env", ".venv", "*.app.lock", "*.db", "*.key", "*.pem", "data", "local-notes",
    "pem_runtime", "test-results", "uploads",
}


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [
        item
        for item in result.stdout.decode("utf-8").split("\0")
        if item and (ROOT / item).is_file()
    ]


def is_primary_document(path: str) -> bool:
    if path == "README.md":
        return True
    return path.startswith("docs/") and path.endswith(".md") and not re.search(
        r"_(?:ja|ko|zh(?:_[A-Za-z]+)?)\.md$", path, re.IGNORECASE
    )


def collect_json_values(value, *, key: str = "") -> set[bytes]:
    found: set[bytes] = set()
    if isinstance(value, dict):
        for child_key, child in value.items():
            found.update(collect_json_values(child, key=str(child_key).lower()))
    elif isinstance(value, list):
        for child in value:
            found.update(collect_json_values(child, key=key))
    elif key in SENSITIVE_LOCAL_KEYS and isinstance(value, str) and len(value.strip()) >= 8:
        found.add(value.strip().encode("utf-8"))
    return found


def local_private_values() -> set[bytes]:
    """Load local comparison values without displaying them or requiring them in CI."""
    found: set[bytes] = set()
    for name in ("EVSUI_API_TOKEN", "EVSUI_BOOTSTRAP_PASSWORD", "EVSUI_CREDENTIAL_KEY"):
        value = str(os.getenv(name, "")).strip()
        if len(value) >= 8:
            found.add(value.encode("utf-8"))
    for relative in LOCAL_CONFIGS:
        path = ROOT / relative
        if not path.is_file():
            continue
        try:
            found.update(collect_json_values(json.loads(path.read_text(encoding="utf-8-sig"))))
        except (OSError, ValueError):
            pass

    database = ROOT / "data" / "evsui.db"
    key_path = ROOT / "data" / "evsui.credentials.key"
    if not database.is_file():
        return found
    try:
        with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
            profile_rows = connection.execute(
                "SELECT host, username, ues_url, pem_filename, password_ciphertext, pat_token_ciphertext "
                "FROM system_connection_profiles"
            ).fetchall()
            service_rows = connection.execute(
                "SELECT api_key_ciphertext FROM external_service_configs"
            ).fetchall()
    except sqlite3.Error:
        return found

    for row in profile_rows:
        for value in row[:4]:
            if isinstance(value, str) and len(value.strip()) >= 8:
                found.add(value.strip().encode("utf-8"))
    if not key_path.is_file():
        return found
    try:
        from cryptography.fernet import Fernet, InvalidToken

        key = key_path.read_bytes().strip()
        if len(key) >= 8:
            found.add(key)
        cipher = Fernet(key)
        ciphertexts = [value for row in profile_rows for value in row[4:]]
        ciphertexts.extend(row[0] for row in service_rows)
        for value in ciphertexts:
            if not value:
                continue
            try:
                plaintext = cipher.decrypt(value.encode("ascii")).strip()
            except (InvalidToken, ValueError):
                continue
            if len(plaintext) >= 8:
                found.add(plaintext)
    except (ImportError, OSError, ValueError):
        pass
    return found


def main() -> int:
    problems: list[str] = []
    paths = tracked_files()
    private_values = local_private_values()

    for relative in paths:
        normalized = relative.replace("\\", "/")
        lowered = normalized.lower()
        if (
            lowered in PRIVATE_PATHS
            or lowered.startswith(PRIVATE_PREFIXES)
            or lowered.endswith(PRIVATE_SUFFIXES)
            or DATED_INTERNAL_REPORT.search(lowered)
        ):
            problems.append(f"private or internal path is tracked: {normalized}")
            continue
        path = ROOT / relative
        try:
            payload = path.read_bytes()
        except OSError as error:
            problems.append(f"cannot inspect tracked file {normalized}: {type(error).__name__}")
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(payload):
                problems.append(f"possible {label} in tracked file: {normalized}")
        if any(value in payload for value in private_values):
            problems.append(f"tracked file repeats a private local value: {normalized}")
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            continue
        if MACHINE_PATH.search(text):
            problems.append(f"machine-specific user path in tracked file: {normalized}")
        if is_primary_document(normalized) and CJK.search(text):
            problems.append(f"primary documentation is not English-only: {normalized}")

    dockerignore = {
        line.strip().rstrip("/")
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing = sorted(REQUIRED_DOCKER_IGNORES - dockerignore)
    if missing:
        problems.append(".dockerignore lacks publication exclusions: " + ", ".join(missing))

    if problems:
        print("Publication check failed:", file=sys.stderr)
        for problem in sorted(set(problems)):
            print(f"- {problem}", file=sys.stderr)
        return 1
    print(f"Publication check passed for {len(paths)} tracked files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
