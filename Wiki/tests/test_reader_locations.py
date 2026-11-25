"""Labels the LLM reader gives text printed without a paragraph label, where the schema cites a document by its
locations (no page-label form): the full heading path, with a table's or figure's own label; and the checks reading
those citations. A table's label line the model marked as furniture is kept. No model call.
Run from Wiki/: python -m unittest tests.test_reader_locations"""
import unittest

from app.sources import llm_reader
from app.sources.models import Chunk
from app.wiki import checks, citecheck

L = lambda i, t, p=1: {"id": f"{p}.{i}", "page": p, "text": t, "size": 10.0, "bold": False}
TOP, EL = "Module 1: Introduction to Credit Risk", "Expected Loss vs. Unexpected Loss"


def chunk(text, path, page=1, ref=None, part=0):
    return Chunk(para_ref=ref, source_type=llm_reader.OWN_TEXT, page=page, heading=path[-1][1] if path else None,
                 content=text, part=part, heading_path=tuple(path))


class Locations(unittest.TestCase):
    def test_heading_paths_tables_and_pages(self):
        path = [(1, TOP), (2, EL)]
        chunks = [chunk("Expected loss is the mean.", path), chunk("[Table 1.2] External Ratings | AAA |", path),
                  chunk("[Figure 1.7 description] A curve.", path), chunk("rest of the table", path, part=1),
                  chunk("Before any heading.", [], page=3), chunk("Printed label.", path, ref="1.4"),
                  chunk("Numbered.", [(1, TOP), (2, "2.3 Ratings")])]
        chunks[3] = chunk("rest of the figure", path, part=1)
        self.assertEqual(llm_reader.locations(chunks), [
            f"{TOP} > {EL}", f"{TOP} > {EL} > Table 1.2", f"{TOP} > {EL} > Figure 1.7",
            f"{TOP} > {EL} > Figure 1.7", "page 3", "1.4", "2.3 Ratings"])

    def test_blocks_by_location_or_by_page(self):
        chunks = [chunk("Expected loss is the mean of the loss distribution.", [(1, TOP), (2, EL)], page=7)]
        rec = {"pages": 1, "model": "m", "headings": 2, "lines_dropped": 0}
        ex = llm_reader.extracted("m1.pdf", list(chunks), rec, 500, 1)
        self.assertTrue(ex.text.startswith(f"[{TOP} > {EL}] Expected loss"))
        self.assertEqual(ex.meta["para_kinds"], {f"{TOP} > {EL}": llm_reader.OWN_TEXT})
        self.assertEqual(ex.meta["page_labels"], [])
        # a schema with a page-label form (as the IFRS schemas give one): the page label, as before
        ex = llm_reader.extracted("m1.pdf", list(chunks), rec, 500, 1, label_forms={"text": "<page label>"})
        self.assertTrue(ex.text.startswith("[p7] Expected loss"))


class CaptionsInsideAPassage(unittest.TestCase):
    def test_a_passage_takes_the_label_of_the_caption_line_it_holds(self):
        lines = [L(1, EL), L(2, "The following table shows the matrix:"), L(3, "[Table 1.2] External Ratings"),
                 L(4, "| AAA | 90.8 |"), L(5, "Density f(z) Threshold"), L(6, "[Figure 1.4 description] A bell curve."),
                 L(7, "Figure 1.4: Latent-variable default model"), L(8, "Figure 1.4 shows that the threshold sits left of"
                   " the peak of the curve, so a borrower defaults when the latent variable falls below it.")]
        marks = [{"line": "1.1", "role": "heading", "level": 1}, {"line": "1.2", "role": "paragraph"},
                 {"line": "1.4", "role": "item"}, {"line": "1.5", "role": "paragraph"}, {"line": "1.8", "role": "paragraph"}]
        chunks, *_ = llm_reader.build(lines, marks, set())
        self.assertEqual(llm_reader.locations(chunks), [f"{EL} > Table 1.2", f"{EL} > Figure 1.4", EL])  # a sentence naming it is not its label


class ChecksReadThem(unittest.TestCase):
    def setUp(self):
        self.text = (f"[{TOP} > {EL}] Expected loss is the mean.\n\n[{TOP} > Stand alone credit risk – EAD (1/2)] EAD is"
                     f" the exposure.\n\n[{TOP} > {EL} > Table 1.2] External Ratings")
        self.labels = {"source-m1": {x.split("]")[0][1:] for x in self.text.split("\n\n")}}
        self.chk = checks.Checks()

    def page(self, label):
        return f"Expected loss is the mean [[source-m1|{label}]]."

    def failures(self, label):
        md = self.page(label)
        _, _, flagged = citecheck.check(md, {"source-m1": citecheck._matcher(self.text)})
        return (checks.label_failures(md, self.labels, self.chk)
                + checks.citation_failures(md, self.labels, set(), self.chk) + [str(k) for k in flagged])

    def test_heading_path_citations_pass(self):
        for lab in (f"{TOP} > {EL}", f"{TOP} > Stand alone credit risk – EAD (1/2)", f"{TOP} > {EL} > Table 1.2"):
            self.assertEqual(self.failures(lab), [], lab)

    def test_text_the_source_does_not_have_fails(self):
        self.assertTrue(self.failures(f"{TOP} > Stand alone credit risk – EAD (2/2)"))
        self.assertTrue(self.failures("p7"))


class KeptLabelLine(unittest.TestCase):
    def test_table_label_kept_box_markers_dropped(self):
        lines = [L(1, "[Box: Worked Illustration 1: EL]"), L(2, "Worked Illustration 1: EL"), L(3, "[End of box]"),
                 L(4, "External Ratings"), L(5, "[Table 1.2] External Ratings"), L(6, "| Initial Rating | AAA |"),
                 L(7, "[End of table]")]
        marks = [{"line": "1.1", "role": "drop"}, {"line": "1.2", "role": "heading", "level": 3},
                 {"line": "1.3", "role": "drop"}, {"line": "1.4", "role": "heading", "level": 3},
                 {"line": "1.5", "role": "drop"}, {"line": "1.6", "role": "item"}, {"line": "1.7", "role": "drop"}]
        chunks, _, rep, _ = llm_reader.build(lines, marks, set())
        self.assertEqual([c.content for c in chunks], ["[Table 1.2] External Ratings | Initial Rating | AAA |"])
        self.assertEqual(rep["drops_kept"], [{"page": 1, "text": "[Table 1.2] External Ratings"}])
        self.assertEqual([d["text"] for d in rep["dropped"]],
                         ["[Box: Worked Illustration 1: EL]", "[End of box]", "[End of table]"])

    def test_label_printed_again_on_the_next_line_is_dropped(self):
        lines = [L(1, "[Figure 1.1] Types"), L(2, "Figure 1.1: Credit risk types")]
        chunks, _, rep, _ = llm_reader.build(lines, [{"line": "1.1", "role": "drop"}, {"line": "1.2", "role": "paragraph"}], set())
        self.assertEqual((rep["drops_kept"], rep["lines_dropped"]), ([], 1))


if __name__ == "__main__":
    unittest.main()
