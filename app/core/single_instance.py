"""Cross-platform lock enforcing one application process per SQLite database."""
from __future__ import annotations

import os
from pathlib import Path


class SingleInstanceLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+b")
        if self._handle.seek(0, 2) == 0:
            self._handle.write(b"0")
            self._handle.flush()
        self._handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._handle.close()
            self._handle = None
            raise RuntimeError(
                "Another teradataevsui process is already using this application database."
            ) from error
        return self

    def __exit__(self, *_exc):
        if self._handle is not None:
            self._handle.close()
            self._handle = None
