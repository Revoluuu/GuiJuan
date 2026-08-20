import unittest

from paper_folder.arxiv_api import arxiv_id_from_filename


class ArxivTests(unittest.TestCase):
    def test_reads_modern_arxiv_filename(self):
        self.assertEqual(arxiv_id_from_filename("2102.06335v1"), "2102.06335")

    def test_ignores_regular_filename(self):
        self.assertEqual(arxiv_id_from_filename("hammer2000"), "")


if __name__ == "__main__":
    unittest.main()
