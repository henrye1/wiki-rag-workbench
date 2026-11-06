"""Offline tests of the answer side, lint and the schema's new Checks lists: no database, no AI call. Run from Wiki/:
.venv/bin/python -m unittest discover tests

Every word the checks look for is read from schema 3.17's Checks section, so the tests hold whatever words it uses."""
import pathlib
import unittest

from app.ops import answering, fixpass, lint, watchdog
from app.ops.query import standard_only
from app.wiki import checks, citecheck, store

SCHEMAS = pathlib.Path(__file__).resolve().parent.parent / "schemas"
SCHEMA = (SCHEMAS / "ifrs9-schema-3.17.md").read_text()
CHK = checks.load(SCHEMA)
H = CHK.answer_headings
NONE = CHK.answer_none
OBLIGE = CHK.force_words[CHK.force_strict]  # the strict force's words, e.g. "shall", "must"
# reader kinds by the schema's name for them
READER = {v: k for k, v in CHK.kinds.items()}
AG, IG = "application guidance", "implementation guidance"
BRIEF, LIMIT = next(iter(CHK.brief_kinds.items()))  # a kind the schema keeps brief, and its most sentences
A, B = "source-a", "source-b"
SRCS = {
    A: {"by_label": {"1.1": [f"[1.1] An entity {OBLIGE[0]} recognise the item."],
                     "1.2": ["[1.2] An entity may measure it at cost."],
                     "B1.1": ["[B1.1] The item reflects the expected amount."]},
        "kinds": {"1.1": "standard", "1.2": "standard", "B1.1": READER[AG]}},
    B: {"by_label": {"IG1": ["[IG1] An entity applies this in a simple case."], "p1": ["The project began."]},
        "kinds": {"IG1": READER[IG], "p1": READER[BRIEF]}},
}
CTX = {"labels": {A: {"1.1", "1.2", "B1.1"}, B: {"IG1", "p1"}}, "matchers": {}, "names": set()}
OPEN = {k: v[0] for k, v in CHK.openers.items()}


def answer(main: str, apart: str = NONE, gaps: str = NONE, refs: str | None = None) -> str:
    cited = sorted({f"[[{sl}|{lab}]]" for sl, lab in answering._source_cites(main + "\n" + apart)})
    refs = refs if refs is not None else ("\n".join(f"- {c}" for c in cited) or NONE)
    return f"{H[0]}\n\n{main}\n\n{H[1]}\n\n{refs}\n\n{H[2]}\n\n{gaps}\n\n{H[3]}\n\n{apart}\n"


class Base(unittest.TestCase):
    def setUp(self):  # the citation check reads the wiki's sources; it is not what these tests are about
        self._cite = fixpass.cite_failures
        fixpass.cite_failures = lambda *a, **k: []

    def tearDown(self):
        fixpass.cite_failures = self._cite

    def fails(self, text: str) -> list[str]:
        return answering.failures(text, CHK, SRCS, CTX)


class SchemaLists(unittest.TestCase):
    def test_3_17_gives_every_list(self):
        self.assertEqual((CHK.missing, CHK.answer_missing, CHK.unreadable, CHK.unknown), ([], [], [], []))
        self.assertTrue(answering.ready(CHK))

    def test_an_older_schema_is_answered_as_before_and_holds_no_upload_for_the_answer_lists(self):
        old = checks.load((SCHEMAS / "ifrs9-schema-3.16.md").read_text())
        self.assertFalse(answering.ready(old))
        self.assertIn("answer layout", answering.checks_off(old))
        self.assertNotIn("answer layout", old.missing)  # only what an upload uses holds it

    def test_kind_ranking_is_the_schemas_full_order(self):
        ranks = [r for r in CHK.kind_ranking]
        own = answering.own_text_name(CHK)
        self.assertEqual(ranks[0], [own])
        self.assertEqual(ranks[1:4], [[AG], [IG], ["example"]])
        self.assertIn("editorial note", ranks[4])

    def test_application_guidance_is_not_kept_apart(self):
        self.assertNotIn(AG, CHK.non_authoritative)
        self.assertIn(IG, CHK.non_authoritative)


class Layout(Base):
    def test_a_good_answer_passes(self):
        main = f"An entity {OBLIGE[0]} recognise the item [[{A}|1.1]]. {OPEN[AG]} that the item reflects the expected amount [[{A}|B1.1]]."
        apart = f"{OPEN[IG]} that an entity applies this in a simple case [[{B}|IG1]]."
        self.assertEqual(self.fails(answer(main, apart)), [])

    def test_a_missing_heading_text_before_and_an_empty_part_fail(self):
        text = answer(f"An entity may measure it at cost [[{A}|1.2]].").replace(H[2] + "\n\n" + NONE, H[2] + "\n\n")
        self.assertTrue(any("empty" in f for f in self.fails(text)))
        self.assertTrue(any("appears 0 times" in f for f in self.fails(text.replace(H[1], "## Sources"))))
        self.assertTrue(any("before the first heading" in f for f in self.fails("In short, yes.\n\n" + text)))


class Placement(Base):
    """Application guidance is authoritative: it stays in the answer with its opener, never under the non-authoritative
    heading, which holds only the kinds the schema lists there."""

    def test_application_guidance_under_non_authoritative_fails(self):
        apart = f"{OPEN[AG]} that the item reflects the expected amount [[{A}|B1.1]]."
        fails = self.fails(answer(f"An entity may measure it at cost [[{A}|1.2]].", apart))
        self.assertTrue(any("B1.1" in f and "authoritative" in f and H[0] in f for f in fails))

    def test_application_guidance_in_the_answer_with_its_opener_passes(self):
        main = f"{OPEN[AG]} that the item reflects the expected amount [[{A}|B1.1]]."
        self.assertEqual(self.fails(answer(main)), [])

    def test_application_guidance_in_the_answer_without_its_opener_fails(self):
        self.assertTrue([f for f in self.fails(answer(f"The item reflects the expected amount [[{A}|B1.1]].")) if "opener" in f])

    def test_implementation_guidance_in_the_answer_fails(self):
        main = f"{OPEN[IG]} that an entity applies this in a simple case [[{B}|IG1]]."
        self.assertTrue(any("IG1" in f and "non-authoritative" in f for f in self.fails(answer(main))))

    def test_the_standards_own_text_under_non_authoritative_fails(self):
        apart = f"An entity may measure it at cost [[{A}|1.2]]."
        self.assertTrue(any("1.2" in f and "authoritative" in f for f in self.fails(answer(f"Yes [[{A}|1.1]].", apart))))


class Force(Base):
    def test_another_word_of_the_same_force_fails(self):
        other = next(w for w in OBLIGE if w != OBLIGE[0])
        fails = self.fails(answer(f"An entity {other} recognise the item [[{A}|1.1]]."))
        self.assertTrue(any(f'"{other}"' in f and f'"{OBLIGE[0]}"' in f for f in fails))

    def test_an_obligation_the_paragraph_does_not_state_fails(self):
        fails = self.fails(answer(f"{OPEN[AG]} that the item {OBLIGE[1]} reflect the expected amount [[{A}|B1.1]]."))
        self.assertTrue(any("obligation" in f for f in fails))

    def test_the_paragraphs_own_word_passes(self):
        self.assertEqual(self.fails(answer(f"An entity {OBLIGE[0]} recognise the item [[{A}|1.1]].")), [])


class Citations(Base):
    """The schema's Workflow: Answer and check: a paragraph is cited only by the group of citations that ends the
    sentence it supports; a link inside a sentence is a pointer, not a citation."""

    def test_a_sentence_without_a_clause_and_a_page_in_the_citations_place_fail(self):
        fails = self.fails(answer(f"The item is recognised. An entity may measure it at cost [[{A}|1.2]]. See [[some-page]]."))
        self.assertTrue(any("cites no clause" in f for f in fails))
        self.assertTrue(any("[[some-page]]" in f and "a page is not a clause" in f for f in fails))

    def test_a_page_link_inside_a_sentence_is_a_pointer_and_passes(self):
        main = (f"An entity may measure the [[concept-item|item]] at cost [[{A}|1.2]]. It becomes "
                f"[[concept-due|due]] [[{A}|1.2]]. Parts: (a) one; (b) [[concept-grade|grades]]; (c) two [[{A}|1.2]].")
        self.assertEqual(self.fails(answer(main)), [])

    def test_a_paragraph_link_in_passing_is_not_a_citation(self):
        self.assertEqual(answering._source_cites(f"An entity may measure the item [[{A}|1.1]] at cost [[{A}|1.2]]."),
                         [(A, "1.2")])
        fails = self.fails(answer(f"The item [[{A}|1.1]] is recognised."))
        self.assertTrue(any("cites no clause" in f for f in fails))  # the link in passing does not cite it

    def test_a_sentence_opening_with_a_quotation_ends_the_one_before_it(self):
        main = f'"Cost" is "The amount paid" [[{A}|1.1]]. "Value" is "The amount received" [[{A}|1.2]].'
        self.assertEqual(answering._source_cites(main), [(A, "1.1"), (A, "1.2")])

    def test_the_clause_references_are_built_from_the_citations_that_end_sentences(self):
        main = (f"An entity may measure the [[concept-item|item]] [[{A}|1.1]] at cost [[{A}|1.2]]. "
                f"{OPEN[AG]} that the item reflects the expected amount [[{A}|B1.1]] [[{A}|1.2]].")
        apart = f"{OPEN[IG]} that an entity applies this in a simple case [[{B}|IG1]]."
        built = answering.with_references(answer(main, apart, refs=f"[[{A}|1.1]]\n[[{A}|9.9]]"), CHK)
        refs = answering.split_parts(built, CHK)[1][1]
        self.assertEqual(refs.split(), [f"[[{A}|1.2]]", f"[[{A}|B1.1]]", f"[[{B}|IG1]]"])
        self.assertIn("[[concept-item|item]]", built)  # the page link stays as it is
        self.assertEqual(answering.split_parts(answering.with_references(answer(f"Yes {NONE}"), CHK), CHK)[1][1].strip(), NONE)


class NotAddressed(Base):
    def test_a_point_not_addressed_says_what_was_searched_for(self):
        main = f"An entity may measure it at cost [[{A}|1.2]]."
        line = answering.searched_line(CHK, ["fee", "charge"], "Definitions")
        self.assertIn('"fee", "charge"', line)
        self.assertIn("Definitions", line)
        self.assertEqual(self.fails(answer(main, gaps=f"- How fees are taxed. {line}")), [])
        self.assertTrue(any("searched for" in f for f in self.fails(answer(main, gaps="- How fees are taxed."))))
        self.assertEqual(answering.not_addressed_points(f"- One.\n- Two.\n{NONE}", CHK), ["One.", "Two."])


class Instruction(unittest.TestCase):
    def test_the_instruction_carries_the_schemas_words(self):
        text = answering.instruction(CHK)
        for h in H:
            self.assertIn(h, text)
        for w in OBLIGE:
            self.assertIn(repr(w), text)
        self.assertIn(f"Material from {AG}", text)  # application guidance stays in the answer
        self.assertIn(f"{AG}; then {IG}; then example", text)
        self.assertNotIn("Cite pages", text)

    def test_the_instruction_takes_the_answer_rules_word_for_word_from_the_schema(self):
        rules = checks.section_using(SCHEMA, checks.ANSWER_LISTS["answer_headings"])
        self.assertTrue(rules.startswith("## "))
        self.assertIn(rules, answering.instruction(CHK, SCHEMA))
        code = pathlib.Path(answering.__file__).read_text()
        for line in rules.splitlines()[1:]:  # no rule of the schema's is restated in the code, so the two cannot drift
            for sentence in checks.sentences(line.lstrip("- ")):
                if len(sentence.split()) > 6:
                    self.assertNotIn(sentence.strip(), code)


class Brief(Base):
    """The schema's Brief kinds, and the kinds kept under the non-authoritative heading."""

    def test_the_schema_gives_the_brief_kinds(self):
        self.assertIn(BRIEF, CHK.non_authoritative)
        self.assertGreater(LIMIT, 0)

    def test_a_brief_kind_in_the_answer_itself_fails(self):
        main = f"{OPEN.get(BRIEF, '')} that the project began [[{B}|p1]]."
        self.assertTrue(any("p1" in f and "non-authoritative" in f for f in self.fails(answer(main))))

    def test_more_sentences_than_the_schema_allows_fail(self):
        say = lambda n: " ".join(f"{OPEN.get(BRIEF, '')} that step {i} happened [[{B}|p1]]." for i in range(n))
        main = f"An entity may measure it at cost [[{A}|1.2]]."
        self.assertFalse([f for f in self.fails(answer(main, say(LIMIT))) if "at most" in f])
        self.assertTrue([f for f in self.fails(answer(main, say(LIMIT + 1))) if f"at most {LIMIT}" in f])


class SearchTerms(unittest.TestCase):
    """The not-addressed search looks for separate terms taken from each point, and the answer lists those terms."""

    def test_each_term_is_searched_on_its_own_and_the_answer_lists_the_terms_searched(self):
        import asyncio
        from app.ops import answering as ans
        tail = answering.searched_line(CHK, ["made-up"], "Definitions")
        points = [f"1. The fee is not addressed. {tail}", "Tax is not covered."]
        asked, searched = [], []

        async def generate_json(system, prompt, schema):
            asked.append(prompt)
            return {"points": [{"n": 2, "terms": ["tax", "levy"]}, {"n": 1, "terms": ["fee", "charge"]}]}

        async def shortlist(wiki_id, text, size):
            searched.append(text)
            return [{"slug": "sec-a"}]

        async def list_pages(wiki_id, with_content=False):
            return [{"slug": "sec-a", "type": "topic", "title": "A", "content_md": ""}]

        async def get_pages(wiki_id, slugs):
            return [{"slug": x} for x in slugs]

        async def restrict(ps):
            return ps

        saved = (ans.llm.generate_json, ans.search.shortlist, ans.store.list_pages, ans.store.get_pages)
        ans.llm.generate_json, ans.search.shortlist, ans.store.list_pages, ans.store.get_pages = (
            generate_json, shortlist, list_pages, get_pages)
        try:
            found, more = asyncio.run(ans.search_not_addressed({"id": 1}, CHK, points, set(), restrict))
        finally:
            ans.llm.generate_json, ans.search.shortlist, ans.store.list_pages, ans.store.get_pages = saved
        self.assertNotIn("made-up", asked[0])  # the draft's own searched line is not part of the point
        self.assertEqual(searched, ["fee", "charge", "tax", "levy"])  # matched by number, each term alone
        self.assertEqual([f["terms"] for f in found], [["fee", "charge"], ["tax", "levy"]])
        draft = answer(f"Yes [[{A}|1.1]].", gaps=f"- 1. The fee is not addressed. {tail}\n- Tax is not covered.")
        gaps = answering.split_parts(answering.with_searched(draft, CHK, found), CHK)[1][2]
        self.assertIn('"fee", "charge"', gaps)
        self.assertIn('"tax", "levy"', gaps)
        self.assertNotIn("made-up", gaps)
        self.assertEqual(answering.not_addressed_points(gaps, CHK)[1].split(found[1]["searched"])[0].strip(), "Tax is not covered.")


class StandardOnly(unittest.TestCase):
    def test_by_paragraph_kind_not_by_file(self):
        md = (f"## Heading\n\nAn entity {OBLIGE[0]} recognise the item [[{A}|1.1]]. {OPEN[AG]} that it reflects the "
              f"expected amount [[{A}|B1.1]].\n\n## Other\n\n{OPEN[IG]} that it applies [[{B}|IG1]].")
        keep = lambda sl, lab: answering.kind_of(SRCS, CHK, sl, lab) == ""
        out = standard_only(md, keep)
        self.assertIn("1.1]]", out)
        self.assertNotIn("B1.1", out)  # same source document, other kind
        self.assertNotIn("IG1", out)
        self.assertNotIn("## Other", out)  # a heading left with nothing under it goes

    def test_unlabelled_text_takes_its_kinds_form(self):
        self.assertEqual(answering.kind_of(SRCS, CHK, A, "ED:1.1"), CHK.kinds["note"])
        self.assertEqual(answering.kind_of(SRCS, CHK, A, "1.1–1.2"), "")
        self.assertIsNone(answering.kind_of(SRCS, CHK, "source-x", "1.1"))

    def test_a_passage_labelled_with_a_range(self):
        srcs = {B: {"by_label": {"IE1–IE3": ["[IE1–IE3] An example."]}, "kinds": {"IE1–IE3": READER["example"]}}}
        self.assertEqual(answering.passages_cited(srcs, B, "IE1–IE3"), ["[IE1–IE3] An example."])
        self.assertEqual(answering.kind_of(srcs, CHK, B, "IE1–IE3"), "example")


class ReferenceWords(unittest.TestCase):
    def test_pointers_and_filler_come_from_the_schema(self):
        pat = checks.reference_re(CHK)
        self.assertEqual(pat.findall("as in paragraphs 42A–42H and (paragraph 34)"), ["42A", "34"])  # as before
        self.assertIsNone(checks.reference_re(None))
        matcher = citecheck._matcher("[5.5.1] One.\n\n[5.5.2] Two.", None)
        self.assertTrue(citecheck._covered("paragraphs 5.5.1 and 5.5.2", matcher, checks.reference_filler(CHK)))
        self.assertFalse(citecheck._covered("paragraphs 5.5.1 and 5.5.2", matcher, checks.reference_filler(None)))
        self.assertTrue(checks.bare_number_re(CHK).fullmatch("paragraph 34(a)"))


class Lint(unittest.TestCase):
    def test_a_page_holding_only_the_empty_text_is_not_thin(self):
        self.assertTrue(lint._only_empty_text(f"## Section\n\n{CHK.empty_text}\n", CHK))
        self.assertFalse(lint._only_empty_text("## Section\n\nA short page.", CHK))
        self.assertFalse(lint._only_empty_text(f"{CHK.empty_text}", None))

    def test_the_maintain_checks_lint_runs_and_those_it_cannot(self):
        self.assertEqual(sorted(CHK.lint_checks.values()), ["citations", "coverage", "headings", "openers"])
        self.assertTrue(CHK.lint_not_run and all(CHK.lint_not_run.values()))  # each with its reason

    def test_saved_answers_are_not_material(self):
        self.assertIn("synthesis", lint.MATERIAL)


class PageList(unittest.TestCase):
    def test_every_page_is_in_one_part(self):
        index = "\n".join(f"page-{i} | topic | Page {i} | summary {i}" for i in range(500))
        parts = store.index_parts(index, 2000)
        self.assertGreater(len(parts), 1)
        self.assertEqual("\n".join(parts), index)
        self.assertTrue(all(len(p) <= 2000 for p in parts))


class Verdicts(unittest.TestCase):
    def test_the_verdict_is_held_to_the_schemas_list(self):
        self.assertEqual(watchdog.verdict_schema(CHK)["properties"]["verdict"]["enum"], CHK.verdicts)
        self.assertEqual(len(CHK.verdicts), 6)

    def test_a_quote_must_be_word_for_word(self):
        ok = [{"citation": f"[[{A}|1.1]]", "quote": f"An entity {OBLIGE[0]}  recognise the item."}]
        self.assertEqual(watchdog.quote_failures(ok, SRCS, CHK), [])
        bad = [{"citation": f"[[{A}|1.1]]", "quote": "An entity recognises the item."}]
        self.assertTrue(watchdog.quote_failures(bad, SRCS, CHK))
        self.assertTrue(watchdog.quote_failures([], SRCS, CHK))
        self.assertTrue(watchdog.quote_failures([{"citation": f"[[{A}|9.9]]", "quote": "x"}], SRCS, CHK))


if __name__ == "__main__":
    unittest.main()
