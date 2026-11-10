import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from paper_folder.metadata import PaperMetadata
from paper_folder.naming import build_rename_previews, sanitize_filename
from paper_folder.operations import apply_renames


class NamingTests(unittest.TestCase):
    def test_removes_windows_invalid_characters(self):
        self.assertEqual(sanitize_filename('A: title? "yes"'), "A- title- -yes-")

    def test_requires_title_and_year(self):
        item = PaperMetadata(Path("paper.pdf"), "", "A", "2024", "", "partial")
        result = build_rename_previews([item])[0]
        self.assertEqual(result.status, "needs review")

    def test_builds_preview_without_renaming(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "old.pdf"
            source.touch()
            item = PaperMetadata(source, "Useful: Paper", "A", "2024", "", "partial")
            result = build_rename_previews([item])[0]
            self.assertEqual(result.suggested_name, "2024 - Useful- Paper.pdf")
            self.assertEqual(result.status, "preview")
            self.assertTrue(source.exists())

    def test_rejects_unknown_template_field(self):
        with self.assertRaises(ValueError):
            build_rename_previews([], "{publisher} - {title}")

    def test_configured_fields_follow_selected_order(self):
        item = PaperMetadata(
            Path("paper.pdf"), "Useful Paper", "Ada Lovelace", "2024", "",
            "complete", journal="Nature Communications",
        )
        result = build_rename_previews(
            [item], fields=["journal", "year", "title"]
        )[0]
        self.assertEqual(
            result.suggested_name,
            "Nature Communications - 2024 - Useful Paper.pdf",
        )

    def test_missing_journal_is_skipped_with_note(self):
        item = PaperMetadata(
            Path("paper.pdf"), "Useful Paper", "Ada Lovelace", "2024", "",
            "complete",
        )
        result = build_rename_previews(
            [item], fields=["year", "journal", "title"]
        )[0]
        self.assertEqual(result.suggested_name, "2024 - Useful Paper.pdf")
        self.assertIn("期刊", result.note)

    def test_conflict_can_receive_numbered_suffix(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "old.pdf"
            source.touch()
            (root / "2024 - Useful Paper.pdf").touch()
            item = PaperMetadata(
                source, "Useful Paper", "Ada", "2024", "", "partial"
            )
            result = build_rename_previews(
                [item], fields=["year", "title"], conflict_strategy="suffix"
            )[0]
            self.assertEqual(result.suggested_name, "2024 - Useful Paper (2).pdf")
            self.assertEqual(result.status, "preview")
            self.assertIn("名称冲突", result.note)

    def test_suffix_avoids_another_files_original_name(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first, second = root / "first.pdf", root / "second.pdf"
            first.touch()
            second.touch()
            items = [
                PaperMetadata(first, "First", "", "2024", "", "partial", suggested_name="renamed.pdf"),
                PaperMetadata(second, "Second", "", "2024", "", "partial", suggested_name="first.pdf"),
            ]

            previews = build_rename_previews(items, conflict_strategy="suffix")

            self.assertEqual([preview.suggested_name for preview in previews], [
                "renamed.pdf", "first (2).pdf",
            ])
            self.assertEqual(apply_renames(previews, root).changed, 2)

    def test_suffix_avoids_a_directory_and_can_reuse_its_own_filename(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "old.pdf"
            source.touch()
            (root / "target.pdf").mkdir()
            item = PaperMetadata(source, "Title", "", "2024", "", "partial", suggested_name="target.pdf")

            previews = build_rename_previews([item], conflict_strategy="suffix")

            self.assertEqual(previews[0].suggested_name, "target (2).pdf")
            self.assertEqual(apply_renames(previews, root).changed, 1)
            renamed = replace(item, path=root / "target (2).pdf")
            rescanned = build_rename_previews([renamed], conflict_strategy="suffix")
            self.assertEqual(rescanned[0].suggested_name, renamed.path.name)

    def test_appendix_does_not_require_year(self):
        item = PaperMetadata(
            Path("appendix.pdf"), "Essential Statistical Thermodynamics",
            "Karl K. Irikura", "", "", "complete",
            document_type="appendix",
        )
        result = build_rename_previews([item])[0]
        self.assertEqual(
            result.suggested_name,
            "Appendix - Essential Statistical Thermodynamics.pdf",
        )

    def test_manual_filename_overrides_template(self):
        item = PaperMetadata(
            Path("old.pdf"), "Title", "Author", "2024", "", "partial",
            suggested_name="My chosen name.pdf",
        )
        self.assertEqual(
            build_rename_previews([item])[0].suggested_name,
            "My chosen name.pdf",
        )


if __name__ == "__main__":
    unittest.main()
