from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from fastapi import UploadFile


def save_pem_upload(pem_file: UploadFile, pem_upload_dir: Path, project_dir: Path) -> str:
    safe_name = Path(pem_file.filename or "uploaded.pem").name
    target = pem_upload_dir / safe_name
    payload = pem_file.file.read()
    target.write_bytes(payload)
    return str(target.relative_to(project_dir))


def latest_uploaded_pem_relative(pem_upload_dir: Path, project_dir: Path) -> str:
    try:
        files = [item for item in pem_upload_dir.iterdir() if item.is_file()]
    except FileNotFoundError:
        return ""
    if not files:
        return ""
    latest = max(files, key=lambda item: item.stat().st_mtime)
    return str(latest.relative_to(project_dir))


def collect_upload_files(form_data, field_name: str = "files") -> list[UploadFile]:
    files: list[UploadFile] = []
    for key, value in form_data.multi_items():
        if key != field_name:
            continue
        if hasattr(value, "filename") and hasattr(value, "read"):
            files.append(value)
    return files


async def save_document_uploads(
    files: list[UploadFile],
    document_upload_dir: Path,
    project_dir: Path,
    now_ts: Callable[[], str],
) -> tuple[list[dict], list[str]]:
    uploaded_items: list[dict] = []
    notices: list[str] = []
    for file in files:
        if not file.filename:
            continue

        safe_name = Path(file.filename).name
        if not safe_name:
            continue

        target = document_upload_dir / safe_name
        relative_path = str(target.relative_to(project_dir))
        existed_before = target.exists()

        payload = await file.read()
        target.write_bytes(payload)
        uploaded_items.append(
            {
                "name": safe_name,
                "saved_path": relative_path,
                "size": len(payload),
                "time": now_ts(),
                "status": "overwritten" if existed_before else "uploaded",
            }
        )

    return uploaded_items, notices


def resolve_path_hint(path_hint: str, project_dir: Path, vs_basics_dir: Path) -> str:
    hint = path_hint.strip()
    if not hint:
        return ""
    candidate = Path(hint)
    candidates = []
    if candidate.is_absolute():
        candidates.append(candidate)
    else:
        candidates.append(project_dir / candidate)
        candidates.append(project_dir.parent / candidate)
        candidates.append(vs_basics_dir / candidate)
    for item in candidates:
        if item.exists():
            return str(item.resolve())
    return hint


def normalize_pem_filename_for_auth(resolved_pem_path: str) -> str:
    if not resolved_pem_path:
        return resolved_pem_path
    path_obj = Path(resolved_pem_path)
    if not path_obj.exists() or not path_obj.is_file():
        return resolved_pem_path
    import re

    match = re.match(r"^\d{8}_\d{6}_\d+_(.+)$", path_obj.name)
    if not match:
        return resolved_pem_path
    normalized_name = match.group(1)
    normalized_path = path_obj.parent / normalized_name
    if normalized_path.exists() and normalized_path.is_file():
        return str(normalized_path.resolve())
    shutil.copyfile(path_obj, normalized_path)
    return str(normalized_path.resolve())
