from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import check_publication
from scripts.check_publication import has_non_english_primary_content


class PublicationCheckTests(unittest.TestCase):
    def test_standard_japanese_language_switch_is_allowed(self) -> None:
        text = (
            "# English guide\n\n"
            "> **Language:** English | [日本語](guide_ja.md)\n\n"
            "English body.\n"
        )

        self.assertFalse(has_non_english_primary_content(text))

    def test_japanese_heading_is_rejected(self) -> None:
        text = (
            "# 日本語の見出し\n\n"
            "> **Language:** English | [日本語](guide_ja.md)\n"
        )

        self.assertTrue(has_non_english_primary_content(text))

    def test_japanese_body_is_rejected(self) -> None:
        text = (
            "# English guide\n\n"
            "> **Language:** English | [日本語](guide_ja.md)\n\n"
            "This paragraph is English. 日本語の本文です。\n"
        )

        self.assertTrue(has_non_english_primary_content(text))

    def test_extra_japanese_on_language_switch_line_is_rejected(self) -> None:
        text = (
            "# English guide\n\n"
            "> **Language:** English | [日本語](guide_ja.md) | 説明\n"
        )

        self.assertTrue(has_non_english_primary_content(text))

    def test_nonstandard_language_switch_is_rejected(self) -> None:
        text = "# English guide\n\nLanguage: English / 日本語\n"

        self.assertTrue(has_non_english_primary_content(text))

    def test_language_switch_does_not_disable_secret_scanning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text(
                "# English guide\n\n"
                "> **Language:** English | [日本語](README_ja.md)\n\n"
                f"Accidental token: ghp_{'A' * 30}\n",
                encoding="utf-8",
            )
            (root / ".dockerignore").write_text(
                "\n".join(sorted(check_publication.REQUIRED_DOCKER_IGNORES)) + "\n",
                encoding="utf-8",
            )
            error = io.StringIO()
            with (
                patch.object(check_publication, "ROOT", root),
                patch.object(check_publication, "tracked_files", return_value=["README.md"]),
                patch.object(check_publication, "local_private_values", return_value=set()),
                contextlib.redirect_stderr(error),
            ):
                result = check_publication.main()

        self.assertEqual(result, 1)
        self.assertIn("possible GitHub token", error.getvalue())


if __name__ == "__main__":
    unittest.main()
