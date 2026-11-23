"""Chat export: chosen sides only, each answer with its sources or pages read; wiki links read as their labels; the
answers' Markdown (headings, lists, tables, bold) carries into Word and the print page; text is escaped. Run from
UI/server: python -m unittest tests.test_chat_export"""
import io
import unittest

from docx import Document
from openpyxl import load_workbook

from app import chat_export as ce

ANSWER = """## ECL — IFRS 9 Compliance Assessment

**Compliance Status**

⚠️ Partially Compliant

1. Gap one <b>
2. Gap two

| Topic | Status |
|---|---|
| ECL | ✅ |
"""
MSGS = [
    {"seq": 1, "kind": "question", "question": "How is ECL calculated?", "rag_collection": "ifrs9", "wiki_slug": "w",
     "rag": {"answer": "RAG says [5.5.3].", "sources": [{"para_ref": "5.5.3"}, {"para_ref": "5.5.3"}, {"chunk_id": "c9"}]},
     "wiki": {"answer": ANSWER + "\nSee [[ecl-page|ECL page]] and [[other]].", "pages": [
         {"slug": "ecl-page", "title": "ECL page", "cited": True}, {"slug": "x", "title": "X", "cited": False}]}},
    {"seq": 2, "kind": "question", "question": "Only RAG?", "rag_collection": "ifrs9", "rag": {"answer": "", "error": "Stopped"}, "wiki": None},
    {"seq": 3, "kind": "summary", "question": "Summary: Eval", "wiki_slug": "w", "rag": None, "wiki": {"answer": "Verdict.", "pages": []}},
]
CHAT = {"title": "IFRS 9 / review: run"}


class Build(unittest.TestCase):
    def test_sides_and_numbering(self):
        d = ce.build(CHAT, MSGS, ["wiki"])
        self.assertEqual([i["heading"] for i in d["items"]], ["Q1. How is ECL calculated?", "Q2. Only RAG?", "Summary: Eval"])
        self.assertEqual([p["side"] for p in d["items"][0]["parts"]], ["wiki"])
        self.assertEqual(d["items"][1]["missing"], ["Wiki"])  # not asked on the wiki

    def test_links_and_sources(self):
        d = ce.build(CHAT, MSGS, ["rag", "wiki"])
        rag, wiki = d["items"][0]["parts"]
        self.assertEqual(rag["sources"], "Sources: 5.5.3, c9")
        self.assertIn("See ECL page and Other.", wiki["answer"])  # a bare [[slug]]: the page title, else the slug made readable
        self.assertEqual(ce.plain_links("[[ecl-page]]", {"ecl-page": "ECL page"}), "ECL page")
        self.assertEqual(wiki["sources"], "Pages read: ECL page; X (read, not cited)")
        self.assertEqual(d["items"][1]["parts"][0]["answer"], "(No answer: Stopped)")

    def test_filename(self):
        self.assertEqual(ce.filename(CHAT["title"], "docx"), "IFRS-9--review-run.docx")


class Formats(unittest.TestCase):
    doc = ce.build(CHAT, MSGS, ["rag", "wiki"])

    def test_markdown_shifts_answer_headings(self):
        md = ce.to_markdown(self.doc)
        self.assertIn("## Q1. How is ECL calculated?", md)
        self.assertIn("### Wiki · w", md)
        self.assertIn("##### ECL — IFRS 9 Compliance Assessment", md)
        self.assertIn("_Sources: 5.5.3, c9_", md)

    def test_blocks(self):
        kinds = [b[0] for b in ce.blocks(ANSWER)]
        self.assertEqual(kinds, ["h", "p", "p", "ol", "table"])

    def test_docx(self):
        d = Document(io.BytesIO(ce.to_docx(self.doc)))
        text = "\n".join(p.text for p in d.paragraphs)
        self.assertIn("Q1. How is ECL calculated?", text)
        self.assertIn("Pages read: ECL page", text)
        self.assertEqual(d.tables[0].cell(1, 1).text, "✅")
        bold = [r.text for p in d.paragraphs for r in p.runs if r.bold]
        self.assertIn("Compliance Status", bold)

    def test_xlsx_row_per_side(self):
        ws = load_workbook(io.BytesIO(ce.to_xlsx(self.doc))).active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        self.assertEqual([(r[0], r[2]) for r in rows], [(1, "RAG · ifrs9"), (1, "Wiki · w"), (2, "RAG · ifrs9"), ("Summary", "Wiki · w")])

    def test_line_breaks_kept(self):
        self.assertEqual(ce.blocks("**Status**\nNot documented."), [("p", "**Status**\nNot documented.")])
        self.assertIn("<strong>Status</strong><br>Not documented.", ce.to_print_html(ce.build(CHAT, [
            {"seq": 1, "question": "Q", "wiki": {"answer": "**Status**\nNot documented."}}], ["wiki"])).decode())

    def test_print_page_escapes(self):
        page = ce.to_print_html(self.doc).decode()
        self.assertIn("Gap one &lt;b&gt;", page)
        self.assertIn("<strong>Compliance Status</strong>", page)
        self.assertIn("<td>✅</td>", page)


if __name__ == "__main__":
    unittest.main()
