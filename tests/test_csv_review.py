import tempfile
import unittest
from pathlib import Path

from paper_folder.csv_review import export_review_csv, load_review_csv
from paper_folder.metadata import PaperMetadata
from paper_folder.naming import build_rename_previews


class CsvReviewTests(unittest.TestCase):
    def test_export_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paper = root / "paper.pdf"
            paper.touch()
            item = PaperMetadata(paper, "A title", "An Author", "2024", "10.1/test", "complete")
            csv_path = root / "papers.csv"
            export_review_csv(csv_path, root, [item], build_rename_previews([item]))
            loaded = load_review_csv(csv_path, root)
            self.assertEqual(loaded[0].title, "A title")
            self.assertEqual(loaded[0].source, "review-csv")

    def test_rejects_path_outside_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            csv_path = root / "bad.csv"
            csv_path.write_text("relative_path,title,authors,year,doi\n../bad.pdf,T,A,2024,D\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_review_csv(csv_path, root)


if __name__ == "__main__":
    unittest.main()
