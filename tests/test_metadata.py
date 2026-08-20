import unittest
from pathlib import Path

from paper_folder.metadata import (
    _appendix_fields,
    _title_from_page,
    _year_from_filename,
    find_doi,
)


class MetadataHelpersTests(unittest.TestCase):
    def test_finds_and_cleans_doi(self):
        self.assertEqual(
            find_doi(["Published as doi:10.1126/science.aay3444."]),
            "10.1126/science.aay3444",
        )

    def test_year_from_regular_filename(self):
        self.assertEqual(_year_from_filename("hammer2000"), "2000")

    def test_year_from_arxiv_filename(self):
        self.assertEqual(_year_from_filename("2102.06335v1"), "2021")

    def test_title_skips_journal_heading(self):
        text = "Physical Review Letters\nA useful scientific paper title\nAbstract\n"
        self.assertEqual(
            _title_from_page(text, "paper"), "A useful scientific paper title"
        )

    def test_reads_appendix_heading(self):
        title, author = _appendix_fields(
            "Appendix B\nEssential Statistical Thermodynamics\nKarl K. Irikura\n"
        )
        self.assertEqual(title, "Essential Statistical Thermodynamics")
        self.assertEqual(author, "Karl K. Irikura")


if __name__ == "__main__":
    unittest.main()
