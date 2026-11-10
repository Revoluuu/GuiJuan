import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyPDF2 import PdfWriter
from PyPDF2.generic import DecodedStreamObject, NameObject

from paper_folder.metadata import (
    _appendix_fields,
    _journal_from_page,
    _title_from_page,
    _year_from_filename,
    extract_paper_metadata,
    find_doi,
    journal_from_citation,
)


class MetadataHelpersTests(unittest.TestCase):
    def test_finds_and_cleans_doi(self):
        self.assertEqual(
            find_doi(["Published as doi:10.1126/science.aay3444."]),
            "10.1126/science.aay3444",
        )

    def test_doi_ends_before_a_glued_publisher_citation(self):
        self.assertEqual(
            find_doi(["https://doi.org/10.1234/exampleCiteThis:J.Phys.Chem.C2025,129,17539−17547"]),
            "10.1234/example",
        )
        self.assertEqual(find_doi(["10.1234/citethis:publication"]), "10.1234/citethis:publication")

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

    def test_extracts_names_from_structured_citations(self):
        for text, expected in (
            ("Nature Communications | (2024) 15:9251 1", "Nature Communications"),
            ("Nature | Vol 618 | 22 June 2023 | 533", "Nature"),
            ("Cite This: ACS Catal. 2025, 15, 10029−10046", "ACS Catal."),
            ("Cite this: Chem. Sci., 2024, 15, 4197", "Chem. Sci."),
            ("CiteThis:J.Phys.Chem.C2025,129,17539−17547", "J. Phys. Chem. C"),
            ("CiteThis:ACSCatal.2022,12,11682−11691", "ACS Catal."),
            ("10.1234/articleCite this: RSC Adv. ,2 0 1 6 , 6,5 1 5 0 3", "RSC Adv."),
            ("Chem. Rec. 2025 ,25, e202500079 (1 of 24) © 2025 The Chemical Society", "Chem. Rec."),
            ("Frontiers in Chemistry | www.frontiersin.org September 2021 | Volume 9 | Article 753617 1ORIGINAL RESEARCH",
             "Frontiers in Chemistry"),
            ("Phys. Rev. D 89, 042001 (2014)", "Phys. Rev. D"),
            ("Journal of Catalysis, 435 (2024) 115558. doi:10.1234/article", "Journal of Catalysis"),
        ):
            with self.subTest(text=text):
                self.assertEqual(journal_from_citation(text), expected)

    def test_reads_wrapped_citation_and_labeled_masthead(self):
        for text, expected in (
            ("Cite this: Chem. Sci., 2024, 15,\n4197", "Chem. Sci."),
            ("Journal Name: Applied Surface Science", "Applied Surface Science"),
            ("Contents lists available at ScienceDirect\nCatalysis Today\njournal homepage: https://example.test",
             "Catalysis Today"),
        ):
            with self.subTest(text=text):
                self.assertEqual(_journal_from_page(text, ""), expected)

    def test_ignores_unstructured_mentions_and_references(self):
        text = (
            "An investigation of surfaces\n"
            "Our previous work appeared in the Journal of Catalysis.\n"
            "Figure 2 (2024) 12345\n"
            "References\n"
            "Smith et al., Journal of Catalysis 435 (2024) 115558\n"
        )
        self.assertEqual(_journal_from_page(text, "An investigation of surfaces"), "")

    def test_uses_journal_and_doi_from_xmp(self):
        xmp = b"""<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
          <rdf:Description rdf:about=""
             xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"
             prism:publicationName="Nature Communications">
            <prism:doi>10.1234/canonical</prism:doi>
          </rdf:Description>
        </rdf:RDF>"""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "10.1234@incorrect.pdf"
            self._write_pdf(path, {"/Title": "Catalysts under realistic conditions"}, xmp)
            result = extract_paper_metadata(path)
        self.assertEqual(result.title, "Catalysts under realistic conditions")
        self.assertEqual(result.journal, "Nature Communications")
        self.assertEqual(result.doi, "10.1234/canonical")

    def test_invalid_xmp_falls_back_to_explicit_document_info(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "paper.pdf"
            self._write_pdf(path, {"/JournalTitle": "Catalysis Today"}, b"<malformed")
            result = extract_paper_metadata(path)
        self.assertEqual(result.journal, "Catalysis Today")
        self.assertNotEqual(result.status, "error")

    def test_reads_later_page_only_for_missing_doi_or_year(self):
        for first_text, expect_second_page in (
            ("Published 2025. DOI: 10.1234/front", False),
            ("DOI: 10.1234/front", True),
            ("© 2022", True),
        ):
            with self.subTest(first_text=first_text):
                second = Mock()
                second.extract_text.return_value = "Published 2025. DOI: 10.1234/second"
                reader = SimpleNamespace(
                    metadata={}, xmp_metadata=None,
                    pages=[SimpleNamespace(extract_text=lambda: first_text), second],
                )
                with patch("paper_folder.metadata.PdfReader", return_value=reader):
                    result = extract_paper_metadata(Path("paper.pdf"))
                self.assertEqual(result.year, "2025")
                self.assertEqual(second.extract_text.called, expect_second_page)
                self.assertEqual(
                    result.doi,
                    "10.1234/front" if "front" in first_text else "10.1234/second",
                )

    @staticmethod
    def _write_pdf(path, metadata, xmp=None):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_metadata(metadata)
        if xmp is not None:
            stream = DecodedStreamObject()
            stream.set_data(xmp)
            writer._root_object[NameObject("/Metadata")] = stream
        with path.open("wb") as output:
            writer.write(output)


if __name__ == "__main__":
    unittest.main()
