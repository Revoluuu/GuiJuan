import tempfile
import unittest
from pathlib import Path

from paper_folder.metadata import PaperMetadata
from paper_folder.naming import build_rename_previews, sanitize_filename


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
            build_rename_previews([], "{journal} - {title}")

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
