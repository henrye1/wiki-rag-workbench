"""The LLM reader's marks turned into paragraphs: text word for word from the lines, labels kept only where printed,
unknown kinds and lines counted, headings as a trail, a paragraph running over into the next pages. No model call.
Run from Wiki/: python -m unittest tests.test_llm_reader"""
import unittest

from app.sources import llm_reader

L = lambda i, t, p=1: {"id": f"{p}.{i}", "page": p, "text": t, "size": 10.0, "bold": False}


class Build(unittest.TestCase):
    def test_marks_to_paragraphs(self):
        lines = [L(1, "Running header"), L(2, "1 Scope"), L(3, "1.1 This applies to"), L(4, "every entity."),
                 L(5, "Example of a thing"), L(6, "An example passage."), L(7, "2")]
        marks = [{"line": "1.1", "role": "drop"}, {"line": "1.2", "role": "heading", "level": 1},
                 {"line": "1.3", "role": "paragraph", "label": "1.1"}, {"line": "1.5", "role": "heading", "level": 2},
                 {"line": "1.6", "role": "paragraph", "label": "9.9", "kind": "example"},
                 {"line": "1.7", "role": "drop"}, {"line": "1.99", "role": "paragraph"}]
        chunks, trail, rep, ends = llm_reader.build(lines, marks, {"example"})
        self.assertEqual([(c.para_ref, c.source_type, c.content, c.heading) for c in chunks], [
            ("1.1", "text", "This applies to every entity.", "1 Scope"),
            (None, "example", "An example passage.", "Example of a thing")])  # 9.9 is not printed: no label
        self.assertEqual(trail, [(1, "1 Scope"), (2, "Example of a thing")])
        self.assertEqual((rep["lines_dropped"], rep["labels_not_printed"], rep["marks_unknown_line"]), (2, 1, 1))
        self.assertEqual(rep["dropped"], [{"page": 1, "text": "Running header"}, {"page": 1, "text": "2"}])
        self.assertIs(ends, chunks[-1])

    def test_unknown_kind_is_own_text(self):
        chunks, *_ = llm_reader.build([L(1, "Text.")], [{"line": "1.1", "role": "paragraph", "kind": "made-up"}], {"example"})
        self.assertEqual(chunks[0].source_type, llm_reader.OWN_TEXT)

    def test_runs_over_into_the_next_pages(self):
        first, trail, _, ends = llm_reader.build([L(1, "Starts here and")], [{"line": "1.1", "role": "paragraph"}], set())
        more, _, _, _ = llm_reader.build([L(1, "ends here.", 2), L(2, "Next one.", 2)], [{"line": "2.2", "role": "paragraph"}],
                                         set(), trail, ends)
        self.assertEqual(first[0].content, "Starts here and ends here.")
        self.assertEqual([c.content for c in more], ["Next one."])

    def test_text_is_never_changed(self):
        lines = [L(i, f"Line {i} text,") for i in range(1, 6)]
        chunks, *_ = llm_reader.build(lines, [{"line": "1.1", "role": "paragraph"}, {"line": "1.4", "role": "paragraph"}], set())
        self.assertEqual(" ".join(c.content for c in chunks), " ".join(x["text"] for x in lines))


class Lists(unittest.TestCase):
    def test_a_list_belongs_to_its_paragraph(self):
        lines = [L(1, "The types are:"), L(2, "- one"), L(3, "- two, which runs"), L(4, "over a line"), L(5, "Next.")]
        marks = [{"line": "1.1", "role": "paragraph"}, {"line": "1.2", "role": "item"}, {"line": "1.3", "role": "item"},
                 {"line": "1.5", "role": "paragraph"}]
        chunks, _, rep, _ = llm_reader.build(lines, marks, set())
        self.assertEqual([c.content for c in chunks], ["The types are: - one - two, which runs over a line", "Next."])
        self.assertEqual(rep["items"], 2)

    def test_a_list_with_no_lead_in(self):
        chunks, *_ = llm_reader.build([L(1, "Head"), L(2, "- a"), L(3, "- b")],
                                      [{"line": "1.1", "role": "heading", "level": 1}, {"line": "1.2", "role": "item"},
                                       {"line": "1.3", "role": "item"}], set())
        self.assertEqual([c.content for c in chunks], ["- a - b"])

    def test_a_long_list_is_split_between_items(self):
        lines = [L(1, "Lead in.")] + [L(i, f"- item {i} " + "word " * 8) for i in range(2, 12)]
        marks = [{"line": "1.1", "role": "paragraph", "label": "Lead"}] + [{"line": f"1.{i}", "role": "item"} for i in range(2, 12)]
        chunks, _, rep, ends = llm_reader.build(lines, marks, set(), max_words=35)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c.content.split()) <= 35 for c in chunks))
        self.assertEqual({c.para_ref for c in chunks}, {"Lead"})  # the parts keep the paragraph's label
        self.assertEqual(" ".join(c.content for c in chunks).split(), " ".join(x["text"] for x in lines).split()[1:])  # word for word
        self.assertEqual([c.part for c in chunks], list(range(len(chunks))))
        self.assertIs(ends, chunks[-1])
        self.assertEqual(rep["split_paragraphs"], 1)

    def test_a_split_list_runs_over_into_the_next_pages(self):
        lines = [L(1, "Lead in.")] + [L(i, "- item " + "word " * 10) for i in range(2, 6)]
        marks = [{"line": "1.1", "role": "paragraph"}] + [{"line": f"1.{i}", "role": "item"} for i in range(2, 6)]
        first, trail, _, ends = llm_reader.build(lines, marks, set(), max_words=30)
        more, *_ = llm_reader.build([L(1, "and its end.", 2)], [], set(), trail, ends, max_words=30)
        self.assertTrue(first[-1].content.endswith("and its end."))
        self.assertEqual(more, [])


class Kinds(unittest.TestCase):
    def test_a_schema_without_the_optional_lists(self):
        from app.wiki import checks
        c = checks.load("## Checks\n- Paragraph kinds (as the PDF reader names them): note = editorial note\n")
        self.assertIsNone(c.kinds_left_out)  # the schema gives no Kinds left out
        self.assertEqual(llm_reader.kinds_listed(c), [("note", "editorial note")])
        self.assertEqual(llm_reader.kinds_listed(None), [])


if __name__ == "__main__":
    unittest.main()
