"""The reader's publisher settings come from Wiki/reader-settings.md: a made-up file is read into the values the reader
uses, and the real file gives the reader its patterns."""
import pathlib
import tempfile
import unittest

from app.sources import pdf_ifrs, reader_settings

MADE_UP = """# Settings
## Where a Standard's own text starts
- Rulebook Part
## Appendices of a Standard
- Annex One = appendix_a
## Where a Standard's own text ends
- Notes of the Committee
## Paragraph numbers in a Standard
- Q<letter>.
- Q
## Paragraph numbers in documents published with a Standard
- EX = example
- RS<up to 3 letters> = basis_for_conclusions
## Kind shown before each paragraph of a document published with a Standard
- example = Worked case
## Implementation guidance
- Title begins: How to apply
- Question letters: A-C
- Question label prefix: HA
- Introduction label: HA introduction
## Publisher fonts and page layout
- Body font begins: Serif
- Heading font begins: Sans
- Smallest heading size: 10
- Editorial font contains: Narrow
- Editorial box heading font: Sans-Bold
- Editorial box heading smaller than: 8
- Editorial box heading left of: 170
- Header and footer font contains: Light
- Smallest header and footer size: 8
- Header above: 100
- Footer below: 700
- Paragraph numbers left of: 140
"""


class Load(unittest.TestCase):
    def test_made_up_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "s.md"
            p.write_text(MADE_UP, encoding="utf-8")
            r = reader_settings.load(p)
        self.assertEqual(r["starts"], ["rulebook part"])
        self.assertEqual(r["appendices"], {"annex one": "appendix_a"})
        self.assertEqual(r["para_prefixes"], ["Q[A-Z]\\.", "Q"])
        self.assertEqual(r["accompanying"], {"EX": "example", "RS[A-Z]{0,3}": "basis_for_conclusions"})
        self.assertEqual(r["kind_labels"], {"example": "Worked case"})
        self.assertEqual((r["ig_letters"], r["ig_prefix"], r["margin_x"]), ("[A-C]", "HA", 140.0))

    def test_reader_uses_the_file(self):
        self.assertTrue(pdf_ifrs.PARA_RE.match("B5.5.17") and pdf_ifrs.PARA_RE.match("BA.1"))
        self.assertEqual(pdf_ifrs.accompanying_kind("BCZ4.1"), "basis_for_conclusions")
        self.assertEqual(pdf_ifrs._section_for_heading("International Accounting Standard 32", "intro"), "standard")
        self.assertEqual(pdf_ifrs._section_for_heading("Appendix B", "standard"), "appendix_b")


if __name__ == "__main__":
    unittest.main()
