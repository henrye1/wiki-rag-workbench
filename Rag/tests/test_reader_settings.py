"""The RAG reader takes its publisher words from the wiki's Wiki/reader-settings.md: one file for both readers.
Run from Rag/: python -m unittest tests.test_reader_settings"""
import pathlib
import unittest

from app.ingest import pdf_ifrs, reader_settings

WIKI_FILE = pathlib.Path(__file__).resolve().parents[2] / "Wiki" / "reader-settings.md"


class ReaderSettings(unittest.TestCase):
    def test_same_file_as_the_wiki(self):
        self.assertEqual(reader_settings.FILE, WIKI_FILE)
        self.assertTrue(WIKI_FILE.exists())

    def test_paragraph_numbers_from_the_settings(self):
        for label in ("5.5.3", "B5.5.17", "BA.1", "AG14A", "102Z", "102Z1", "42AA", "D1", "E8", "C2", "A1"):
            self.assertTrue(pdf_ifrs.PARA_RE.match(label), label)
        for label in ("Appendix", "2025a", "DO1", "B5.5.17x"):
            self.assertFalse(pdf_ifrs.PARA_RE.match(label), label)

    def test_parts_of_a_standard_from_the_settings(self):
        self.assertEqual(pdf_ifrs._section_for_heading("International Accounting Standard 32", "intro"), "standard")
        self.assertEqual(pdf_ifrs._section_for_heading("Application guidance", "standard"), "appendix_b")
        self.assertEqual(pdf_ifrs._section_for_heading("Approval by the Board of IAS 32", "appendix_b"), "back_matter")
        self.assertEqual(pdf_ifrs.accompanying_kind("BCZ4"), "basis_for_conclusions")
        self.assertEqual(pdf_ifrs.accompanying_kind("IE12"), "example")


if __name__ == "__main__":
    unittest.main()
