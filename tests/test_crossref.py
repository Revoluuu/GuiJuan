import unittest
from pathlib import Path

from paper_folder.crossref import CrossrefRecord, enrich_from_crossref, record_from_message
from paper_folder.metadata import PaperMetadata


class StubClient:
    def lookup(self, doi):
        return CrossrefRecord("Canonical title", "Ada Lovelace; Alan Turing", "2024", doi)


class CrossrefTests(unittest.TestCase):
    def test_parses_crossref_message(self):
        record = record_from_message({
            "title": ["A paper"],
            "author": [{"given": "Ada", "family": "Lovelace"}],
            "published-print": {"date-parts": [[2020, 5, 1]]},
            "DOI": "10.1234/example",
        })
        self.assertEqual(record.authors, "Ada Lovelace")
        self.assertEqual(record.year, "2020")

    def test_verified_record_replaces_local_guesses(self):
        local = PaperMetadata(Path("paper.pdf"), "Bad title", "", "", "10.1234/example", "partial")
        result = enrich_from_crossref(local, StubClient())
        self.assertEqual(result.title, "Canonical title")
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.source, "crossref")


if __name__ == "__main__":
    unittest.main()
