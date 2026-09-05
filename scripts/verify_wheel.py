from __future__ import annotations

import sys
import zipfile
from pathlib import Path


FORBIDDEN_RUNTIME_CONFIGS = {
    "app/config/auth_users.json",
    "app/config/local_dev.json",
    "app/config/unstructured.json",
    "app/config/unstructured_models.json",
    "app/core/process_lock.py",
    "app/worker.py",
}
REQUIRED_RUNTIME_FILES = {
    "app/main.py",
    "app/core/single_instance.py",
    "app/routers/jobs.py",
    "app/services/job_worker.py",
    "app/templates/partials/job_progress.html",
}
FORBIDDEN_RUNTIME_PREFIXES = ("data/", "local-notes/", "pem_runtime/", "test-results/", "uploads/")
PACKAGED_CONFIGS = {
    "app/config/bookrag_retrieval_policy.json",
    "app/config/bookrag_section_rules.json",
    "app/config/local_dev.example.json",
    "app/config/unstructured_models.example.json",
}


def expected_application_files() -> set[str]:
    expected: set[str] = set()
    for path in (Path.cwd() / "app").rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(Path.cwd()).as_posix()
        if (
            path.suffix == ".py"
            or relative.startswith(("app/static/", "app/templates/"))
            or relative in PACKAGED_CONFIGS
        ):
            expected.add(relative)
    return expected


def verify_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    expected = expected_application_files()
    packaged = {name for name in names if name.startswith("app/")}
    forbidden = sorted(names & FORBIDDEN_RUNTIME_CONFIGS)
    forbidden.extend(sorted(name for name in names if name.startswith(FORBIDDEN_RUNTIME_PREFIXES)))
    unexpected = sorted(packaged - expected)
    missing = sorted((expected | REQUIRED_RUNTIME_FILES) - names)
    if forbidden:
        raise RuntimeError(f"Wheel contains local runtime configuration: {', '.join(forbidden)}")
    if unexpected:
        raise RuntimeError(f"Wheel contains stale or undeclared application files: {', '.join(unexpected)}")
    if missing:
        raise RuntimeError(f"Wheel is missing required runtime files: {', '.join(missing)}")


def main() -> int:
    # Ignore old evsui wheels retained locally after the project rename.
    candidates = sorted(Path("dist").glob("teradataevsui-*.whl"))
    if len(candidates) != 1:
        raise RuntimeError(f"Expected exactly one teradataevsui wheel in dist/, found {len(candidates)}.")
    verify_wheel(candidates[0])
    print(f"Verified safe wheel: {candidates[0].name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
