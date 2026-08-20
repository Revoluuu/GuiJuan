import tempfile
import unittest
from pathlib import Path

from paper_folder.bibtex import export_bibtex
from paper_folder.metadata import PaperMetadata


class BibtexTests(unittest.TestCase):
    def test_exports_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "papers.bib"
            item = PaperMetadata(Path("p.pdf"), "Useful Paper", "Ada Lovelace; Alan Turing", "2024", "10.1/test", "complete")
            export_bibtex(output, [item])
            text = output.read_text(encoding="utf-8")
            self.assertIn("@article{lovelace2024useful", text)
            self.assertIn("Ada Lovelace and Alan Turing", text)


if __name__ == "__main__":
    unittest.main()
