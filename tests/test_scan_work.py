import io
import json
import tempfile
import unittest
from concurrent.futures import CancelledError
from pathlib import Path
from threading import Event
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from paper_folder.metadata import PaperMetadata
from paper_folder.scan_work import scan_papers


def paper(path, doi=""):
    return PaperMetadata(path, "Local title", "Local author", "2024", doi, "partial")


class ScanWorkTests(unittest.TestCase):
    def test_deduplicates_identifiers_and_preserves_folder_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            filenames = ["z.pdf", "2201.00002.pdf", "2201.00001v2.pdf", "a.pdf", "b.pdf"]
            for name in filenames:
                (root / name).touch()

            def extract(path):
                dois = {"a.pdf": "10.1234/ABC", "b.pdf": "10.1234/abc"}
                return paper(path, dois.get(path.name, ""))

            crossref_response = io.BytesIO(json.dumps({"message": {
                "title": ["Crossref title"], "type": "journal-article",
                "container-title": ["Crossref Journal"],
            }}).encode())
            arxiv_response = io.BytesIO(b"""
                <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
                    <entry><id>https://arxiv.org/abs/2201.00002v1</id><title>Second article</title></entry>
                    <entry><id>https://arxiv.org/abs/2201.00001v3</id><title>First article</title>
                        <arxiv:journal_ref>Phys. Rev. D 89, 042001 (2014)</arxiv:journal_ref></entry>
                </feed>
            """)
            progress = []
            with patch("paper_folder.scan_work.extract_paper_metadata", side_effect=extract), \
                    patch("paper_folder.crossref.urlopen", return_value=crossref_response) as crossref, \
                    patch("paper_folder.arxiv_api.urlopen", return_value=arxiv_response) as arxiv:
                items = scan_papers(root, False, True, "", lambda *event: progress.append(event), Event())

            self.assertEqual([item.path.name for item in items], sorted(filenames))
            self.assertEqual([item.title for item in items], [
                "First article", "Second article", "Crossref title", "Crossref title", "Local title",
            ])
            self.assertEqual(items[0].journal, "Phys. Rev. D")
            self.assertEqual(items[2].journal, "Crossref Journal")
            crossref.assert_called_once()
            arxiv.assert_called_once()
            params = parse_qs(urlsplit(arxiv.call_args.args[0].full_url).query)
            self.assertEqual(params["id_list"], ["2201.00001,2201.00002"])
            self.assertEqual(progress[0], ("discover", 0, 0))
            self.assertIn(("local", 5, 5), progress)
            self.assertEqual(progress[-1], ("online", 4, 4))

    def test_cancellation_during_local_phase_never_starts_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.pdf").touch()
            (root / "b.pdf").touch()
            cancel = Event()

            def report(phase, completed, total):
                if phase == "local" and completed == 1:
                    cancel.set()

            with patch("paper_folder.scan_work.extract_paper_metadata", side_effect=paper) as extract, \
                    patch("paper_folder.scan_work.CrossrefClient") as crossref:
                with self.assertRaises(CancelledError):
                    scan_papers(root, True, True, "", report, cancel)
            extract.assert_called_once()
            crossref.assert_not_called()

    def test_rate_limit_preserves_local_results_and_pauses_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("a.pdf", "b.pdf"):
                (root / name).touch()

            def extract(path):
                return paper(path, "10.1234/" + path.stem)

            response = HTTPError("https://api.crossref.org", 429, "Limited", {"Retry-After": "30"}, None)
            with patch("paper_folder.scan_work.extract_paper_metadata", side_effect=extract), \
                    patch("paper_folder.crossref.urlopen", side_effect=response) as crossref:
                items = scan_papers(root, False, True, "", lambda *_: None, Event())
            crossref.assert_called_once()
            self.assertEqual([item.title for item in items], ["Local title", "Local title"])


if __name__ == "__main__":
    unittest.main()
