"""Validate the intentionally small, locked Python dependency policy."""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_RUNTIME = {
    "argon2-cffi>=25.1.0,<26",
    "cryptography>=50.0.1,<51",
    "fastapi>=0.141.1,<0.142",
    "httpx>=0.28.1,<0.29",
    "jinja2>=3.1.6,<4",
    "pydantic>=2.13.5,<3",
    "pypdf>=6.17.0,<7",
    "python-multipart>=0.0.32,<0.1",
    "starlette>=0.52.1,<0.53",
    "teradatagenai==20.0.0.9",
    "teradataml>=20.0.0.11,<20.1",
    "unstructured-client==0.46.2",
    "uvicorn>=0.52.4,<0.53",
}
EXPECTED_DEV = {"ruff>=0.16.6,<0.17"}
EXPECTED_OPTIONAL = {"browser": {"playwright>=1.62,<1.63"}}
EXPECTED_BUILD = {"setuptools==84.0.0", "wheel==0.48.0"}
EXPECTED_ENVIRONMENTS = {
    "sys_platform == 'win32' and platform_machine == 'AMD64'",
    "sys_platform == 'linux' and platform_machine == 'x86_64'",
}
EXPECTED_LOCKED = {
    "aiofiles",
    "annotated-doc",
    "annotated-types",
    "anyio",
    "argon2-cffi",
    "argon2-cffi-bindings",
    "certifi",
    "cffi",
    "charset-normalizer",
    "click",
    "cryptography",
    "fastapi",
    "greenlet",
    "h11",
    "httpcore",
    "httpx",
    "idna",
    "jinja2",
    "markupsafe",
    "numpy",
    "oauthlib",
    "packaging",
    "pandas",
    "playwright",
    "psutil",
    "pycparser",
    "pycryptodome",
    "pydantic",
    "pydantic-core",
    "pyee",
    "pyjwt",
    "pypdf",
    "pypdfium2",
    "python-dateutil",
    "python-dotenv",
    "python-multipart",
    "pyyaml",
    "requests",
    "requests-oauthlib",
    "requests-toolbelt",
    "ruff",
    "six",
    "sqlalchemy",
    "starlette",
    "teradataevsui",
    "teradatagenai",
    "teradataml",
    "teradatasql",
    "teradatasqlalchemy",
    "typing-extensions",
    "typing-inspection",
    "tzdata",
    "unstructured-client",
    "urllib3",
    "uvicorn",
}


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def compare(label: str, actual: set[str], expected: set[str], problems: list[str]) -> None:
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing:
        problems.append(f"{label} dependencies missing from pyproject.toml: {', '.join(missing)}")
    if unexpected:
        problems.append(f"{label} dependencies require policy review: {', '.join(unexpected)}")


def main() -> int:
    problems: list[str] = []
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    compare("runtime", set(project["project"]["dependencies"]), EXPECTED_RUNTIME, problems)
    compare("development", set(project["dependency-groups"]["dev"]), EXPECTED_DEV, problems)
    compare("build-system", set(project["build-system"]["requires"]), EXPECTED_BUILD, problems)

    optional = project["project"].get("optional-dependencies", {})
    if set(optional) != set(EXPECTED_OPTIONAL):
        problems.append("optional dependency groups require policy review")
    for group, expected in EXPECTED_OPTIONAL.items():
        compare(group, set(optional.get(group, [])), expected, problems)

    if project["project"].get("requires-python") != ">=3.11,<3.12":
        problems.append("supported Python range must remain >=3.11,<3.12 unless CI coverage is expanded")
    uv_config = project.get("tool", {}).get("uv", {})
    if uv_config.get("required-version") != "==0.12.10":
        problems.append("tool.uv.required-version must match the reviewed uv version")
    if uv_config.get("no-build") is not True:
        problems.append("tool.uv.no-build must prevent undeclared source builds")
    if uv_config.get("python-downloads") != "never":
        problems.append("tool.uv.python-downloads must not install an undeclared interpreter")
    if set(uv_config.get("required-environments", [])) != EXPECTED_ENVIRONMENTS:
        problems.append("tool.uv.required-environments must cover supported Windows and Linux targets")
    if any(ROOT.glob("requirements*.txt")):
        problems.append("requirements*.txt duplicates the pyproject.toml/uv.lock source of truth")

    lock_path = ROOT / "uv.lock"
    if not lock_path.is_file():
        problems.append("uv.lock is missing")
        locked_names: set[str] = set()
    else:
        lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
        packages = lock.get("package", [])
        locked_names = {normalize(item["name"]) for item in packages}
        compare("locked closure", locked_names, EXPECTED_LOCKED, problems)
        for package in packages:
            name = normalize(package["name"])
            source = package.get("source", {})
            if name == "teradataevsui":
                if source != {"editable": "."}:
                    problems.append("project lock source must remain the local editable checkout")
            elif source != {"registry": "https://pypi.org/simple"}:
                problems.append(f"non-PyPI source requires policy review: {name}")
            if name != "teradataevsui" and not package.get("wheels"):
                problems.append(f"locked dependency has no wheel: {name}")

    if problems:
        print("Dependency policy check failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    print(
        "Dependency policy passed: "
        f"{len(EXPECTED_RUNTIME)} runtime, {len(EXPECTED_DEV)} development, "
        f"{sum(map(len, EXPECTED_OPTIONAL.values()))} optional, {len(locked_names)} locked distributions."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
