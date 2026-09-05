from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.check_doc_parity import (
    ROOT,
    MarkdownValidationError,
    check_license_pair,
    check_pair,
    check_repository,
    fenced_blocks,
    local_markdown_links,
    source_digest,
    structure_signature,
)


class DocumentationParityTests(unittest.TestCase):
    def _pair(
        self,
        root: Path,
        english_body: str,
        japanese_body: str,
    ) -> tuple[Path, Path]:
        docs = root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        source = docs / "guide.md"
        translation = docs / "guide_ja.md"
        source_text = (
            "# Guide\n\n"
            "> **Language:** English | [日本語](guide_ja.md)\n\n"
            f"{english_body.rstrip()}\n"
        )
        translation_text = (
            "# ガイド\n\n"
            "> **言語:** [English](guide.md) | 日本語\n"
            f"<!-- Source-SHA256: {source_digest(source_text)} -->\n\n"
            f"{japanese_body.rstrip()}\n"
        )
        source.write_text(source_text, encoding="utf-8")
        translation.write_text(translation_text, encoding="utf-8")
        return source, translation

    def _problems_for_pair(
        self,
        root: Path,
        english_body: str,
        japanese_body: str,
    ) -> list[str]:
        source, translation = self._pair(root, english_body, japanese_body)
        problems: list[str] = []
        check_pair(source, translation, problems, root)
        return problems

    def test_logical_structure_accepts_translated_reflow(self):
        english = (
            "# Title\n\n"
            "A paragraph split\nacross lines.\n\n"
            "> A quoted paragraph\n> across lines.\n\n"
            "- First\n"
            "  continuation\n"
            "- Second\n\n"
            "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
            "```text\nsame code\n```\n"
        )
        japanese = (
            "# 題名\n\n"
            "一行の段落。\n\n"
            "> 一行の引用。\n\n"
            "- 一番目\n"
            "- 二番目\n\n"
            "| 甲 | 乙 |\n|---|---|\n| 一 | 二 |\n\n"
            "```text\nsame code\n```\n"
        )
        self.assertEqual(structure_signature(english), structure_signature(japanese))
        self.assertEqual(fenced_blocks(english), fenced_blocks(japanese))

    def test_missing_paragraph_changes_structure(self):
        english = "# Title\n\nRequired paragraph.\n\n## Details\n"
        japanese = "# 題名\n\n## 詳細\n"
        self.assertNotEqual(structure_signature(english), structure_signature(japanese))

    def test_list_kind_and_table_shape_are_structural(self):
        unordered = "- One\n- Two\n\n| A | B |\n|---|---|\n"
        ordered = "1. 一\n2. 二\n\n| 甲 | 乙 | 丙 |\n|---|---|---|\n"
        self.assertNotEqual(structure_signature(unordered), structure_signature(ordered))

    def test_fence_closer_must_be_bare_and_balanced(self):
        valid = "```text\n```not-a-close\n```\n"
        self.assertEqual(fenced_blocks(valid), ["text\0```not-a-close"])
        with self.assertRaisesRegex(MarkdownValidationError, "unterminated"):
            fenced_blocks("```text\n```not-a-close\n")

    def test_fenced_commands_must_remain_identical(self):
        english = "Before\n```powershell\nuv sync --locked\n```\n"
        japanese = "前\n~~~powershell\nuv sync --locked\n~~~~\n"
        changed = "前\n```powershell\nuv sync\n```\n"
        self.assertEqual(fenced_blocks(english), fenced_blocks(japanese))
        self.assertNotEqual(fenced_blocks(english), fenced_blocks(changed))

    def test_source_hash_normalizes_bom_unicode_and_platform_newlines(self):
        composed = "\ufefffirst\r\ncaf\N{LATIN SMALL LETTER E WITH ACUTE}\r\n"
        decomposed = "first\ncafe\N{COMBINING ACUTE ACCENT}\n"
        self.assertEqual(source_digest(composed), source_digest(decomposed))
        self.assertNotEqual(source_digest("hard break  \n"), source_digest("hard break\n"))

    def test_missing_hash_reports_exact_expected_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, translation = self._pair(root, "Paragraph.", "段落。")
            text = translation.read_text(encoding="utf-8")
            translation.write_text(
                "\n".join(
                    line for line in text.splitlines() if "Source-SHA256" not in line
                )
                + "\n",
                encoding="utf-8",
            )
            problems: list[str] = []
            check_pair(source, translation, problems, root)
            expected = source_digest(source.read_text(encoding="utf-8"))
            self.assertTrue(any(expected in problem for problem in problems), problems)

    def test_hash_inside_fenced_code_is_not_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, translation = self._pair(root, "Paragraph.", "段落。")
            text = translation.read_text(encoding="utf-8")
            marker = next(line for line in text.splitlines() if "Source-SHA256" in line)
            translation.write_text(
                text.replace(marker, f"```text\n{marker}\n```"), encoding="utf-8"
            )
            problems: list[str] = []
            check_pair(source, translation, problems, root)
            self.assertTrue(
                any("exactly one top Source-SHA256" in item for item in problems),
                problems,
            )

    def test_duplicate_hash_and_nonexact_switch_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, translation = self._pair(root, "Paragraph.", "段落。")
            text = translation.read_text(encoding="utf-8")
            marker = next(line for line in text.splitlines() if "Source-SHA256" in line)
            translation.write_text(
                text.replace("# ガイド", f"# ガイド\n{marker}").replace(
                    "> **言語:**", "> **Language:**"
                ),
                encoding="utf-8",
            )
            problems: list[str] = []
            check_pair(source, translation, problems, root)
            self.assertTrue(any("exactly one top Source-SHA256" in item for item in problems))
            self.assertTrue(any("exactly one top language switch" in item for item in problems))

    def test_localized_ordered_links_and_images_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docs = root / "docs"
            docs.mkdir()
            (docs / "target.md").write_text("# Target\n\n## Details\n", encoding="utf-8")
            (docs / "target_ja.md").write_text("# 対象\n\n## 詳細\n", encoding="utf-8")
            (docs / "diagram image.png").write_bytes(b"image")
            english = (
                "See [details](target.md#details).\n\n"
                "![Diagram](<diagram image.png>)"
            )
            japanese = (
                "[詳細](target_ja.md#詳細)を参照。\n\n"
                "![図](<diagram image.png>)"
            )
            self.assertEqual(self._problems_for_pair(root, english, japanese), [])

    def test_missing_link_is_detected_even_when_paragraph_shape_matches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docs = root / "docs"
            docs.mkdir()
            (docs / "target.md").write_text("# Target\n", encoding="utf-8")
            (docs / "target_ja.md").write_text("# 対象\n", encoding="utf-8")
            problems = self._problems_for_pair(
                root,
                "See [target](target.md).",
                "対象を参照してください。",
            )
            self.assertTrue(any("ordered links differ" in item for item in problems), problems)

    def test_external_autolinks_are_part_of_the_ordered_link_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            problems = self._problems_for_pair(
                root,
                "Visit <HTTPS://Example.COM/help>.",
                "<https://example.com/help> を参照。",
            )
            self.assertEqual(problems, [])

    def test_cross_language_link_requires_an_explicit_language_label(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docs = root / "docs"
            docs.mkdir()
            (docs / "target.md").write_text("# Target\n", encoding="utf-8")
            (docs / "target_ja.md").write_text("# 対象\n", encoding="utf-8")
            problems = self._problems_for_pair(
                root,
                "See [target](target.md).",
                "[対象](target.md)を参照。",
            )
            self.assertTrue(
                any("without an English label" in item for item in problems), problems
            )

    def test_broken_english_link_is_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            problems = self._problems_for_pair(
                root,
                "See [missing](missing.md).",
                "[欠落](missing_ja.md)を参照。",
            )
            self.assertTrue(
                any("invalid local link in docs/guide.md" in item for item in problems),
                problems,
            )

    def test_case_mismatch_is_rejected_independently_of_host_os(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docs = root / "docs"
            docs.mkdir()
            (docs / "Target.md").write_text("# Target\n", encoding="utf-8")
            (docs / "Target_ja.md").write_text("# 対象\n", encoding="utf-8")
            problems = self._problems_for_pair(
                root,
                "See [target](target.md).",
                "[対象](Target_ja.md)を参照。",
            )
            self.assertTrue(any("wrong case" in item for item in problems), problems)

    def test_repository_escape_is_rejected_even_when_file_exists(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "repository"
            root.mkdir()
            (parent / "outside.md").write_text("private", encoding="utf-8")
            problems = self._problems_for_pair(
                root,
                "See [outside](../../outside.md).",
                "[外部](../../outside.md)を参照。",
            )
            self.assertTrue(any("escapes the repository" in item for item in problems), problems)

    def test_missing_markdown_fragment_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docs = root / "docs"
            docs.mkdir()
            (docs / "target.md").write_text("# Target\n", encoding="utf-8")
            (docs / "target_ja.md").write_text("# 対象\n", encoding="utf-8")
            problems = self._problems_for_pair(
                root,
                "See [target](target.md#missing).",
                "[対象](target_ja.md#欠落)を参照。",
            )
            self.assertTrue(any("fragment does not exist" in item for item in problems), problems)

    def test_angle_destination_with_spaces_is_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = root / "README.md"
            target = root / "file name.txt"
            document.write_text("[file](<file name.txt>)\n", encoding="utf-8")
            target.write_text("content", encoding="utf-8")
            links = local_markdown_links(document, document.read_text(), root)
            self.assertEqual(links, [("file", "file name.txt", target)])

    def test_reference_style_links_are_rejected_not_silently_skipped(self):
        with self.assertRaisesRegex(MarkdownValidationError, "reference-style"):
            local_markdown_links(
                ROOT / "README.md",
                "See [documentation][docs].\n\n[docs]: README.md\n",
                ROOT,
            )

    def test_license_sections_and_body_paragraphs_are_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            english = (
                "LICENSE\nVersion 1\n\nDRAFT\n\nIntroduction.\n\n"
                "1. FIRST\n\nFirst body.\n\n2. SECOND\n\nSecond body.\n"
            )
            (root / "LICENSE").write_text(english, encoding="utf-8")
            japanese = (
                "# ライセンス日本語参考訳\n\n"
                "> **言語:** [English](LICENSE) | 日本語\n>\n> 参考訳です。\n\n"
                f"<!-- Source-SHA256: {source_digest(english)} -->\n\n"
                "バージョン 1\n\n草案\n\n序文。\n\n"
                "## 1. 第一\n\n第一本文。\n\n## 2. 第二\n\n第二本文。\n"
            )
            translation = root / "LICENSE_ja.md"
            translation.write_text(japanese, encoding="utf-8")
            problems: list[str] = []
            check_license_pair(root, problems)
            self.assertEqual(problems, [])
            translation.write_text(
                japanese.replace("\n第二本文。", ""), encoding="utf-8"
            )
            problems = []
            check_license_pair(root, problems)
            self.assertTrue(any("body paragraphs differ" in item for item in problems), problems)

    def test_repository_document_pairs_pass(self):
        self.assertEqual(check_repository(ROOT), [])


if __name__ == "__main__":
    unittest.main()
