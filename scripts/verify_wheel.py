from __future__ import annotations

import sys
import zipfile
from pathlib import Path


FORBIDDEN_RUNTIME_CONFIGS = {
    "app/config/auth_users.json",
    "app/config/local_dev.json",
    "app/config/unstructured.json",
    "app/config/unstructured_models.json",
}
REQUIRED_RUNTIME_FILES = {
    "app/routers/jobs.py",
    "app/templates/partials/job_progress.html",
    "app/worker.py",
}


def verify_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
    forbidden = sorted(names & FORBIDDEN_RUNTIME_CONFIGS)
    missing = sorted(REQUIRED_RUNTIME_FILES - names)
    if forbidden:
        raise RuntimeError(f"Wheel contains local runtime configuration: {', '.join(forbidden)}")
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
