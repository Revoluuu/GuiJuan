import unittest
from pathlib import Path

from paper_folder.duplicates import find_duplicates
from paper_folder.metadata import PaperMetadata


class DuplicateTests(unittest.TestCase):
    def test_groups_same_doi_case_insensitively(self):
        items = [
            PaperMetadata(Path("a.pdf"), "A", "X", "2020", "10.1/ABC", "complete"),
            PaperMetadata(Path("b.pdf"), "B", "Y", "2021", "10.1/abc", "complete"),
        ]
        groups = find_duplicates(items)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].reason, "same DOI")

    def test_uses_title_and_year_without_doi(self):
        items = [
            PaperMetadata(Path("a.pdf"), "A useful-paper", "", "2020", "", "partial"),
            PaperMetadata(Path("b.pdf"), "A useful paper", "", "2020", "", "partial"),
        ]
        self.assertEqual(len(find_duplicates(items)), 1)


if __name__ == "__main__":
    unittest.main()
