"""Offline tests of the page checks: no database, no AI call. Run from Wiki/: .venv/bin/python -m unittest discover tests

What a check looks for comes from the schema (the kinds, their openers, the condition phrases), read here from the
schema file, so the tests hold whatever words a schema uses."""
import pathlib
import re
import unittest

from app.ops import fixpass, pagecheck
from app.ops.ingest import _covers
from app.wiki import checks
from app.wiki.store import Op

SCHEMA = pathlib.Path(__file__).resolve().parent.parent / "schemas" / "ifrs9-schema-3.16.md"
CHK = checks.load(SCHEMA.read_text())
# a paragraph kind whose opener has no placeholder, and that opener
KIND, OPENER = next((k, CHK.openers[v][0]) for k, v in CHK.kinds.items() if v in CHK.openers and "<" not in CHK.openers[v][0])
COND = CHK.conditions[0]
A, B = "source-a", "source-b"
SRCS = {A: {"by_label": {"1": ["[1] An entity does this."], "2": [f"[2] An entity does that {COND} it has done this."]}, "kinds": {}},
        B: {"by_label": {"B1": ["[B1] Guidance on this."]}, "kinds": {"B1": KIND}}}
CTX = {"labels": {}}
covers = lambda label, ref: _covers(label, ref, True)


def check(text: str, held: dict) -> list[str]:
    return pagecheck.section_check(chk=CHK, covers=covers, srcs=SRCS, held=held, cite_ctx=CTX, absence_allowed=True)(text)


class Base(unittest.TestCase):
    def setUp(self):  # the citation check reads the wiki's sources; it is not what these tests are about
        self._cite = fixpass.cite_failures
        fixpass.cite_failures = lambda *a, **k: []

    def tearDown(self):
        fixpass.cite_failures = self._cite


class SentencesAtLinks(unittest.TestCase):
    S = "[[source-x|1.1]]"
    CASES = {
        "The item is an asset " + S + ". It is measured " + S + ".": 2,  # punctuation after the link
        "It aims to allow insight. " + S + " An entity may choose " + S + ".": 2,  # punctuation before the link
        "It aims. " + S + ", [[source-x|1.2]] An entity may choose " + S + ".": 2,  # before a group of links
        "Paragraphs 23(a) and 28 of [[entity-x|Doc 21]] The Title Of It apply " + S + ".": 1,  # a name, then a title
        "An entity also shall apply [[p|paragraph 9.9.9]] (for the first case) or another " + S + ".": 1,
        "The hedged items are: (a) a layer " + S + "; (b) a part of a volume " + S + ".": 1,  # ";" before a list part
        "For the purposes of " + S + ": (a) an item that was " + S + ".": 1,  # ":" before a list part
        "No links here. Two sentences.": 1,
    }

    def test_cases(self):
        for text, n in self.CASES.items():
            got = checks.sentences_at_links(text)
            self.assertEqual(len(got), n, text)
            self.assertEqual("".join(got).replace(" ", ""), text.replace(" ", ""), text)  # nothing lost or added


class Openers(Base):
    def test_a_mid_sentence_link_does_not_cut_the_sentence(self):
        text = f"{OPENER} that the rate of [[entity-x|Doc 21]] The Title Of It applies [[{B}|B1]]."
        self.assertEqual([f for f in check(text, {}) if "B1" in f], [])

    def test_a_sentence_after_a_bracket_is_checked(self):
        # the old split cut at "]] (" and took the piece holding the citation for a list item, so it was never checked
        text = f"An entity applies [[p|paragraph 9.9.9]] (for the first case) as guided [[{B}|B1]]."
        self.assertTrue([f for f in check(text, {}) if "B1" in f])

    def test_every_source_the_page_cites(self):
        # the page holds source A's paragraphs; a sentence citing source B without its opener fails all the same
        text = f"An entity does this [[{A}|1]]. Guidance says this [[{B}|B1]]."
        self.assertTrue([f for f in check(text, {A: {"1"}}) if "B1" in f])
        self.assertEqual([f for f in check(f"An entity does this [[{A}|1]]. {OPENER} this [[{B}|B1]].", {A: {"1"}})
                          if "B1" in f], [])


class Conditions(Base):
    def test_a_held_paragraph_keeps_its_condition(self):
        text = f"An entity does that [[{A}|2]]."
        self.assertTrue([f for f in check(text, {A: {"2"}}) if "condition" in f])

    def test_a_paragraph_cited_in_passing_is_not_checked_for_it(self):
        text = f"An entity does that [[{A}|2]]."
        self.assertEqual([f for f in check(text, {A: {"1"}}) if "condition" in f], [])


class Passages(Base):
    SPLIT = {A: {"by_label": {"3": ["[3] The first part.", f"[3] The second part, {COND} it is so."]}, "kinds": {}}}

    def test_a_page_holding_one_passage_is_checked_for_that_passage(self):
        by = self.SPLIT[A]["by_label"]
        self.assertEqual([pagecheck.key_of(by, x) for x in by["3"]], ["3#0", "3#1"])
        run = lambda keys: pagecheck.section_check(chk=CHK, covers=covers, srcs=self.SPLIT, held={A: keys}, cite_ctx=CTX,
                                                   absence_allowed=True)(f"The first part [[{A}|3]].")
        self.assertEqual([f for f in run({"3#0"}) if "condition" in f], [])  # its condition is in the other passage
        self.assertTrue([f for f in run({"3#1"}) if "condition" in f])


class Held(unittest.TestCase):
    def test_pieces_hold_what_they_cite(self):
        held = {"p": {A: {"1", "2"}, B: {"B1"}}}
        pagecheck.pass_on(held, "p", {"p": f"x [[{A}|1]].", "q": f"y [[{A}|2]]. z [[{B}|B1]]."})
        self.assertEqual(held["p"], {A: {"1"}, B: set()})
        self.assertEqual(held["q"], {A: {"2"}, B: {"B1"}})

    def test_an_index_holds_nothing_and_routed_holds_stand(self):
        held = {"sec": {A: {"1"}, B: {"B1"}}, "sec-x": {A: {"2"}}}
        pagecheck.pass_on(held, "sec", {"sec-x": f"y [[{A}|1]]. z [[{B}|B1]]."}, keep={A})
        self.assertEqual(held["sec"], {A: set(), B: set()})
        self.assertEqual(held["sec-x"], {A: {"2"}, B: {"B1"}})

    def test_after_a_split(self):
        held = {"p": {A: {"1", "2"}}}
        pagecheck.held_after_split(held, [{"page": "p", "split": True, "into": ["p", "p-2"]}],
                                   {"p": f"x [[{A}|1]].", "p-2": f"y [[{A}|2]]."})
        self.assertEqual((held["p"], held["p-2"]), ({A: {"1"}}, {A: {"2"}}))


class AsSaved(Base):
    def test_a_later_pass_that_breaks_a_check_is_caught_before_saving(self):
        # the page passed its section check; a later pass (earlier citations put back) wrote a sentence without its opener
        ops = [Op(op="update", slug="sec-x", type="subtopic", title="Sec: X", content_md=f"Guidance says this [[{B}|B1]]."),
               Op(op="update", slug="other", type="topic", title="Other", content_md=f"{OPENER} this [[{B}|B1]].")]
        out = pagecheck.as_saved(ops, {}, {"sec-x": {B: {"B1"}}}, chk=CHK, covers=covers, srcs=SRCS, cite_ctx=CTX, body=lambda md: md)
        self.assertEqual([r["page"] for r in out], ["sec-x"])
        self.assertEqual(ops[0].holds, {B: ["B1"]})

    def test_an_index_is_not_checked_as_a_section_page(self):
        ops = [Op(op="update", slug="sec", type="topic", title="Sec", content_md=f"Guidance says this [[{B}|B1]]."),
               Op(op="create", slug="sec-x", type="subtopic", title="Sec: X", content_md="")]
        out = pagecheck.as_saved(ops, {}, {}, chk=CHK, covers=covers, srcs=SRCS, cite_ctx=CTX, body=lambda md: md)
        self.assertEqual([r["page"] for r in out if r["page"] == "sec"], [])


if __name__ == "__main__":
    unittest.main()
