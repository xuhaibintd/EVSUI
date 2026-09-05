"""OS-owned local process locks; lock files must never be deleted while in use."""
from __future__ import annotations

import os
from pathlib import Path


class ProcessLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if self.handle.seek(0, 2) == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.handle.close()
            self.handle = None
            raise RuntimeError(f"Another process holds the lock: {self.path}") from error
        return self

    def __exit__(self, *_exc):
        if self.handle is not None:
            self.handle.close()  # OS releases the lock, including after a crash.
            self.handle = None


def lock_is_held(path: Path) -> bool:
    try:
        with ProcessLock(path):
            return False
    except RuntimeError:
        return True
