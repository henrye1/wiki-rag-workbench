"""The source map's mechanics on made-up text: sections in document order, labels found in them, closing citations only."""
import unittest

from app.ops import sourcemap
from app.wiki import checks

TEXT = "\n\n".join([
    "[Front] A paper",
    "[1] First rule.",
    "[2] Second rule.",
    "[2(a)] A sub-item.",
    "[Part Two > Topic] Words.",
    "[Part Two > Topic > Table 1] a | b",
])
PATHS = [[], [[1, "Part One"]], [[1, "Part One"], [2, "Detail"]], [[1, "Part One"], [2, "Detail"]],
         [[1, "Part Two"], [2, "Topic"]], [[1, "Part Two"], [2, "Topic"]]]


class Sections(unittest.TestCase):
    def test_order_and_labels(self):
        order, of = sourcemap.sections(TEXT, PATHS)
        self.assertEqual(order, ["Front", "Part One", "Part One > Detail", "Part Two > Topic"])
        self.assertEqual(of["2(a)"], "Part One > Detail")
        self.assertEqual(of["Part Two > Topic > Table 1"], "Part Two > Topic")

    def test_paths_that_do_not_line_up_are_not_used(self):
        order, _ = sourcemap.sections(TEXT, PATHS[:2])
        self.assertEqual(order[1], "1")  # each label is then a section of its own

    def test_section_of(self):
        _, of = sourcemap.sections(TEXT, PATHS)
        self.assertEqual(sourcemap.section_of("1(b)", of), "Part One")  # sub-item letters
        self.assertEqual(sourcemap.section_of("1-2", of), "Part One")  # a range: its first label
        self.assertEqual(sourcemap.section_of("Part Two > Topic > Figure 9", of), "Part Two > Topic")  # longest start
        self.assertIsNone(sourcemap.section_of("Part Twelve", of))
        self.assertIsNone(sourcemap.section_of("9", of))


class Shown(unittest.TestCase):
    def test_page_labels_and_schema_forms(self):
        c = checks.Checks(unlabelled_forms={"side remark": "SR:<clause>", "opening": "<page label>"})
        self.assertEqual(sourcemap.shown("p74", c), "Page 74")
        self.assertEqual(sourcemap.shown("SR:p79", c), "Page 79 (side remark)")  # the kind's name comes from the schema
        self.assertEqual(sourcemap.shown("SR:12", c), "12 (side remark)")
        self.assertEqual(sourcemap.shown("Part One > Detail", c), "Part One > Detail")
        self.assertEqual(sourcemap.shown("SR:p79", None), "SR:p79")  # no schema form: as it is


class SchemaLine(unittest.TestCase):
    BASE = "## Checks\n- Openers: note = \"The note states\"\n"

    def test_on_off_and_missing(self):
        on = checks.load(self.BASE + "- Source map with each page read: yes. What it does.\n")
        off = checks.load(self.BASE + "- Source map with each page read: none\n")
        missing = checks.load(self.BASE)
        self.assertTrue(on.source_map)
        self.assertFalse(off.source_map)
        self.assertFalse(missing.source_map)
        self.assertNotIn("source map with each page read", missing.missing + missing.answer_missing + missing.unknown)


class AsText(unittest.TestCase):
    def test_page_and_contents(self):
        page = sourcemap.page_map_md([{"slug": "source-x", "title": "Paper X", "not_in_source": [],
                                       "sections": [{"name": "Part One", "cite": "1", "sentences": 2}]}])
        self.assertIn("- [[source-x|Paper X]]\n  - [[source-x|1]] Part One (2)", page)
        con = sourcemap.contents_md({"slug": "source-x", "title": "Paper X", "unused": [{"name": "Front", "cite": "Front"}],
                                     "sections": [{"name": "Part One", "cite": "1", "pages": [{"slug": "a", "title": "A", "sentences": 3}]}]})
        self.assertIn("- [[source-x|1]] Part One: [[a|A]] (3)", con)
        self.assertIn("Sections no page draws on:\n- [[source-x|Front]] Front", con)
        self.assertEqual(sourcemap.cite_of({"1": "Part One", "2": "Part One", "F": "Front"}), {"Part One": "1", "Front": "F"})


class Cited(unittest.TestCase):
    def test_closing_citations_only(self):
        md = ("- As [[source-x|9]] says, a rule applies [[source-x|1]]. Another rule [[source-x|2]], [[source-y|3]].\n"
              "## Heading [[source-x|7]]")
        self.assertEqual(sourcemap.cited(md), [{("source-x", "1")}, {("source-x", "2"), ("source-y", "3")}])


if __name__ == "__main__":
    unittest.main()
