from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from starlette.datastructures import UploadFile

from app.utils.uploads import save_document_uploads


class UploadLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def make_upload(self, filename: str, payload: bytes) -> UploadFile:
        stream = tempfile.SpooledTemporaryFile(max_size=4, mode="w+b")
        self.addCleanup(stream.close)
        stream.write(payload)
        stream.seek(0)
        return UploadFile(stream, filename=filename)

    async def test_saved_duplicate_empty_and_oversize_uploads_all_close(self):
        files = [
            self.make_upload("saved.txt", b"save"), self.make_upload("saved.txt", b"duplicate"),
            self.make_upload("", b"no filename"), self.make_upload("large.txt", b"too large"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows, notices = await save_document_uploads(files, root / "uploads", root, lambda: "now", max_upload_bytes=4)
            self.assertEqual([row["filename"] for row in rows], ["saved.txt"])
            self.assertEqual(len(notices), 2)
        self.assertTrue(all(item.file.closed for item in files))

    async def test_read_failure_closes_current_and_remaining_uploads(self):
        failed = self.make_upload("failed.txt", b"first")
        remaining = self.make_upload("remaining.txt", b"second")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.object(failed, "read", side_effect=OSError("fixture read failure")):
                with self.assertRaises(OSError):
                    await save_document_uploads([failed, remaining], root / "uploads", root, lambda: "now")
        self.assertTrue(failed.file.closed)
        self.assertTrue(remaining.file.closed)
