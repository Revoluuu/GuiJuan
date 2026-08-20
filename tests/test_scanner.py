from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from paper_folder.scanner import format_file_size, scan_pdf_files


class ScanPdfFilesTests(unittest.TestCase):
    def test_scans_pdf_files_case_insensitively(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "b.PDF").write_bytes(b"pdf-b")
            (root / "a.pdf").write_bytes(b"pdf-a")
            (root / "notes.txt").write_text("ignore me", encoding="utf-8")

            files = scan_pdf_files(root)

            self.assertEqual([item.name for item in files], ["a.pdf", "b.PDF"])
            self.assertEqual([item.size_bytes for item in files], [5, 5])

    def test_recursive_scan_includes_subfolders(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "nested"
            nested.mkdir()
            (nested / "paper.pdf").write_bytes(b"content")

            self.assertEqual(scan_pdf_files(root), [])
            recursive_files = scan_pdf_files(root, recursive=True)

            self.assertEqual(len(recursive_files), 1)
            self.assertEqual(recursive_files[0].relative_path, Path("nested/paper.pdf"))

    def test_missing_folder_raises_clear_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            scan_pdf_files("folder-that-does-not-exist")

    def test_file_path_is_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "paper.pdf"
            file_path.write_bytes(b"content")

            with self.assertRaises(NotADirectoryError):
                scan_pdf_files(file_path)


class FormatFileSizeTests(unittest.TestCase):
    def test_formats_common_sizes(self) -> None:
        self.assertEqual(format_file_size(0), "0 B")
        self.assertEqual(format_file_size(1024), "1.0 KB")
        self.assertEqual(format_file_size(1024 * 1024), "1.0 MB")


if __name__ == "__main__":
    unittest.main()
