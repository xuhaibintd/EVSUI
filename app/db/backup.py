from __future__ import annotations

import sqlite3
import time
from pathlib import Path


def backup_database(database_path: Path, destination: Path | None = None) -> Path:
    """Create a transactionally consistent SQLite backup, including WAL state."""

    source_path = Path(database_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if destination is None:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        destination = source_path.parent / "backups" / f"{source_path.stem}_{stamp}.db"
    target_path = Path(destination).expanduser().resolve()
    if target_path == source_path:
        raise ValueError("Backup destination must differ from the source database.")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        raise FileExistsError(target_path)

    source = sqlite3.connect(source_path)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
        integrity = target.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or str(integrity[0]).lower() != "ok":
            raise RuntimeError(f"SQLite backup integrity check failed: {integrity}")
        target.commit()
    except Exception:
        target.close()
        target_path.unlink(missing_ok=True)
        raise
    finally:
        source.close()
        try:
            target.close()
        except Exception:
            pass
    return target_path
