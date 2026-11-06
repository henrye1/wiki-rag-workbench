"""Offline tests of the report-build batch (failures-by-cause.md, fixes 1-17): no database, no AI call. Run from Wiki/:
.venv/bin/python -m unittest discover tests

The words each rule uses (kinds, openers, bracket forms, page-turn text, note markers, the no-content length) are read
from the schema file, so the tests hold whatever words a schema gives."""
import pathlib
import re
import unittest

from app import prompts
from app.ops import fixpass, pagecheck
from app.ops.ingest import (_covers, _deciding, _failing_pieces, _footnote_of, _index_md, _pieces_together, _quoted,
                            _with_openers)
from app.sources import extract
from app.sources.models import Chunk
from app.wiki import checks

_DIR = pathlib.Path(__file__).resolve().parent.parent / "schemas"
SCHEMA = max(_DIR.glob("ifrs9-schema-3.1[6-9].md"), key=lambda x: int(x.stem.rsplit(".", 1)[1]))  # the newest schema here
CHK = checks.load(SCHEMA.read_text())
covers = lambda label, ref: _covers(label, ref, True)
# a reader kind of each sort the schema names
NOTE_KIND = next(k for k, v in CHK.kinds.items() if v in CHK.note_kinds)  # a kind filed with its clause
GUIDE_KIND = next(k for k, v in CHK.kinds.items() if v not in CHK.note_kinds and v in CHK.openers
                  and "<" not in CHK.openers[v][0])  # a kind with a plain opener
GUIDE_OPENER = CHK.openers[CHK.kinds[GUIDE_KIND]][0]
NOTE_OPENER = CHK.openers[CHK.kinds[NOTE_KIND]][0]
ED = CHK.unlabelled_forms[CHK.kinds[NOTE_KIND]]  # its citation form, "<prefix><clause>"
TERM = CHK.defined_term_form
MARK = CHK.agenda_markers[0]
S = "source-a"


def ed(clause: str) -> str:
    return ED.replace("<clause>", clause)


class Settings(unittest.TestCase):
    """The new Checks lists are read from the schema, none missing or unreadable."""

    def test_lists(self):
        self.assertFalse(CHK.missing + CHK.unreadable + CHK.unknown)
        for x in (CHK.note_kinds, CHK.agenda_markers, CHK.bracket_notes, CHK.bracket_pointers, CHK.page_turn,
                  CHK.note_markers):
            self.assertTrue(x)
        self.assertTrue(CHK.no_content_words)
        self.assertIn(checks.AGENDA, CHK.openers)  # the openers an agenda decision takes, listed under its list's name


class Locations(unittest.TestCase):
    """Fix 2: a citation counts only where its label is a location the source holds, in every citation form."""
    LABELS = {"5.5.17", "B5.5.49", ed("2.1"), TERM.replace("<term>", "fair value"), "p3", "5B", "5D"}

    def test_each_form_counts(self):
        for lab in ("5.5.17", "5.5.17(a)", "B5.5.49", ed("2.1"), TERM.replace("<term>", "fair value"), "p3", "5B–5D"):
            self.assertTrue(checks.is_location(lab, self.LABELS), lab)

    def test_a_name_does_not(self):
        name = CHK.document_names[0].replace("<n>", "9")
        self.assertFalse(checks.is_location(name, self.LABELS))
        self.assertFalse(checks.is_location("paragraphs 33–42", self.LABELS))

    def test_opener_check_reads_only_locations(self):
        name = CHK.document_names[0].replace("<n>", "9")
        page = f"{GUIDE_OPENER} that X applies [[{S}|B1]] [[{S}|{name}]]."
        fails = checks.section_failures(page, [], {"B1": GUIDE_KIND}, S, CHK, covers, {"B1"})
        self.assertEqual(fails, [])  # the name is not read as a clause of the source's own text: no mixed kinds

    def test_index_lists_only_locations(self):
        name = CHK.document_names[0].replace("<n>", "9")
        sub = {"slug": "x-1", "title": "X: one", "content_md": f"## H\n\nA rule [[{S}|5.5.17]] [[{S}|{name}]]."}
        content, _ = _index_md("X", [sub], {S: "Source A"}, None, {S: {"5.5.17"}})
        self.assertIn("5.5.17", content)
        self.assertNotIn(name, content)


class Messages(unittest.TestCase):
    """Fixes 3, 4, 7, 14: what a failure says, and that it names its paragraph's source."""

    def test_source_named(self):
        page = f"X applies [[{S}|B1]]."
        f = checks.section_failures(page, [], {"B1": GUIDE_KIND}, S, CHK, covers, {"B1"})
        self.assertEqual(len(f), 1)
        self.assertEqual(fixpass._failing_paragraphs(f), {("B1", S): f})

    def test_wrong_citation_said(self):
        other = next(k for k, v in CHK.kinds.items() if v in CHK.openers and v != CHK.kinds[GUIDE_KIND]
                     and "<" not in CHK.openers[v][0])
        page = f"{GUIDE_OPENER} that X applies [[{S}|N1]]."  # opens as guidance, cites another kind the page was not given
        f = checks.section_failures(page, ["[B1] Guidance."], {"N1": other, "B1": GUIDE_KIND}, S, CHK, covers, {"N1", "B1"})
        self.assertEqual(len(f), 1)
        self.assertIn("not one of this page's own", f[0])
        self.assertEqual(fixpass.named_paragraphs(f), {("N1", S)})

    def test_mixed_kinds_says_split(self):
        page = f"{GUIDE_OPENER} that X applies [[{S}|B1]] [[{S}|1.1]]."
        f = checks.section_failures(page, [], {"B1": GUIDE_KIND, "N1": NOTE_KIND}, S, CHK, covers, {"B1", "1.1"})
        self.assertEqual(f, [])  # the guidance part opens as guidance; the source's own text needs none
        page = f"X applies [[{S}|N1]] [[{S}|B1]]."
        f = checks.section_failures(page, [], {"B1": GUIDE_KIND, "N1": NOTE_KIND}, S, CHK, covers, {"B1", "N1"})
        self.assertTrue(f and "one sentence per clause" in f[0])

    def test_agenda_decision_opener(self):
        ag = [o for o in CHK.openers[checks.AGENDA] if "<" in o][0]
        said = checks.PLACEHOLDER.sub("The Committee", ag).replace("The The", "The")
        page = f"{said} that X [[{S}|{ed('2.1')}]]."
        kinds = {ed("2.1"): NOTE_KIND}
        self.assertEqual(checks.section_failures(page, [], kinds, S, CHK, covers, {ed("2.1")}, agenda={ed("2.1")}), [])
        self.assertTrue(checks.section_failures(page, [], kinds, S, CHK, covers, {ed("2.1")}))  # a note, not an agenda decision
        both = f"{NOTE_OPENER} that X [[{S}|{ed('2.1')}]]."
        self.assertEqual(checks.section_failures(both, [], kinds, S, CHK, covers, {ed("2.1")}, agenda={ed("2.1")}), [])

    def test_agenda_labels(self):
        by = {ed("2.1"): [f"[{ed('2.1')}] E1 [Update, {MARK}, x]"], ed("2.4"): [f"[{ed('2.4')}] A note."]}
        self.assertEqual(checks.agenda_labels(by, CHK), {ed("2.1")})


class Quote(unittest.TestCase):
    """Fix 7 and 13: the quote step quotes only the passage of a label the failures are about."""
    PARTS = [f"[{ed('2.1')}] E1 [first note about leases and derecognition]", f"[{ed('2.1')}] E2 [second note on hedges]"]

    def test_failing_piece_by_sentence(self):
        fail = f'The sentence citing {ed("2.1")} of [[{S}]] ("Hedges are second note material...") comes from x but does not open'
        self.assertEqual(_failing_pieces(self.PARTS, [fail]), [self.PARTS[1]])

    def test_failing_piece_by_part(self):
        parts = ["[1] Lead (a) one (b) two", "[1] more (c) three (d) four"]
        fail = "Paragraph 1 of [[s]] has lettered or numbered parts (a), (b), (c), (d); (c), (d) do not appear on the page."
        self.assertEqual(_failing_pieces(parts, [fail]), [parts[1]])

    def test_quote_keeps_the_other_piece(self):
        text = (f"{NOTE_OPENER} that leases and derecognition are covered [[{S}|{ed('2.1')}]].\n\n"
                f"Hedges second note [[{S}|{ed('2.1')}]].")
        fail = f'The sentence citing {ed("2.1")} of [[{S}]] ("Hedges second note...") comes from x but does not open'
        new = _quoted(text, ed("2.1"), S, {ed("2.1"): self.PARTS}, CHK, {ed("2.1"): NOTE_KIND}, {}, "", [fail])
        self.assertIn("leases and derecognition are covered", new)  # the first note's write-up stays
        self.assertIn('"E2 [second note on hedges]"', new)  # only the second is quoted
        self.assertNotIn('"E1', new)


class Routing(unittest.TestCase):
    """Fix 10: a note goes with its clause, unless it is an agenda decision or sits beside a page label."""

    def test_notes_follow_their_clause(self):
        paras = ["[1.1] A rule.", f"[{ed('1.1')}] A plain note.", f"[{ed('1.1')}] {MARK} of the committee.",
                 "[p3] Front matter.", f"[{ed('p3')}] A note before the first clause."]
        kinds = ["standard", NOTE_KIND, NOTE_KIND, "intro", NOTE_KIND]
        got = _footnote_of(paras, ED, kinds, CHK, {"p3"})
        self.assertEqual(got, {1: 0})

    def test_without_the_list_footnotes_only(self):
        chk = checks.load(SCHEMA.read_text().replace("- Notes filed with their clause", "- Notes filed with their x"))
        paras = ["[1.1] A rule.", f"[{ed('1.1')}] A note.", f"[{ed('1.1')}] A footnote."]
        self.assertEqual(_footnote_of(paras, ED, ["standard", "note", "footnote"], chk), {2: 0})


class Pieces(unittest.TestCase):
    """Fix 11: the pieces of one passage go to one subtopic page."""

    def test_together(self):
        paras = ["[IG E.3] a", "[IG E.3] b", "[IG E.3] c", "[X] d"]
        fixed, named = {0: "page-5", 1: "page-5"}, {2: ["E.3"], 3: ["Other"]}
        _pieces_together(paras, fixed, named)
        self.assertEqual((fixed, named), ({0: "page-5", 1: "page-5", 2: "page-5"}, {3: ["Other"]}))


class Holds(unittest.TestCase):
    """Fix 5: the last record of each check on a page decides; a page checked as saved is not held for its draft."""

    def test_last_record(self):
        recs = [{"page": "overview", "kind": "no claims", "still": 16}, {"page": "overview", "kind": "no claims", "still": 0}]
        self.assertEqual([r["still"] for r in _deciding(recs, set())], [0])

    def test_saved_check_supersedes(self):
        recs = [{"page": "p", "kind": "section", "still": 1}]
        self.assertEqual(_deciding(recs, {"p"}), [])
        self.assertEqual(len(_deciding(recs, set())), 1)


class AsSaved(unittest.TestCase):
    """Fixes 1 and 5: the page the checks see is the page as saved."""
    CTX = {"labels": {S: {"45"}, "source-b": {"1.1"}}, "doc_names": None, "matchers": {}}

    def test_made_up_source_resolved(self):
        self.assertEqual(fixpass.resolve_sources("A [[source-made-up|45]].", self.CTX, S), f"A [[{S}|45]].")
        self.assertEqual(fixpass.resolve_sources("A [[source-made-up|9.9]].", self.CTX, S), "A [[source-made-up|9.9]].")


class Reader(unittest.TestCase):
    """Fixes 12 and 13: the reader's asides read from the schema."""
    R = checks.reader_settings(CHK)

    def test_brackets(self):
        note, ptr = self.R["note_re"], self.R["pointer_re"]
        one = "[Note: for the reasons refer to paragraphs BC1–BC2]"
        two = "[Note: It says this. Readers should refer to paragraph 2.]"
        self.assertTrue(note.search(one) and ptr.search(one))
        self.assertTrue(note.search(two) and not ptr.search(two))  # a pointer only as one sentence
        self.assertEqual(ptr.sub("", "x [Refer: paragraph 1] y"), "x  y")
        self.assertFalse(ptr.search("[nowhere]"))

    def test_page_turn_and_markers(self):
        turn = CHK.page_turn[0]
        self.assertEqual(" ".join(self.R["page_turn_re"].sub(" ", f"assets and {turn} liabilities").split()), "assets and liabilities")
        mk = CHK.note_markers[0].replace("<n>", "{}")
        text = f"{mk.format(1)}first] {mk.format(2)}second] Example E3 table"
        self.assertEqual(len(list(self.R["marker_re"].finditer(text))), 2)

    def test_no_content(self):
        n = CHK.no_content_words
        short = Chunk(None, "intro", 62, None, " ".join(["word"] * n), 0, ())
        kept = Chunk(None, "intro", 63, None, " ".join(["word"] * (n + 1)), 0, ())
        pointer = Chunk("21A", NOTE_KIND, 30, None, "[Note: for the reasons refer to paragraphs BC1–BC2]", 0, ())
        out = extract._kept([short, kept, pointer], [], checks.label_forms(CHK), self.R)
        self.assertEqual([c.page for c in out], [63])


class Writer(unittest.TestCase):
    """Fix 15: each passage shown with its kind's openers, as the schema's Openers list gives them."""

    def test_openers_shown(self):
        out = _with_openers(["[B1] Guidance.", "[1.1] A rule."], CHK, {"B1": GUIDE_KIND, "1.1": "standard"}, set())
        self.assertEqual(out[0], f'[B1] {prompts.opens_note(CHK.openers[CHK.kinds[GUIDE_KIND]])} Guidance.')
        self.assertEqual(out[1], "[1.1] A rule.")


class SourcePage(unittest.TestCase):
    """Fix 17: the authority text from where its sentence starts; no open questions under fixed sections."""

    def test_authority_context(self):
        form = next(a for a in CHK.authority if "..." not in a)
        text = f"[IG intro] (Some kind) This guidance {form} the rules."
        got = checks.authority_context(text, CHK)
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].startswith("[IG intro] This guidance"), got[0])

    def test_no_open_questions(self):  # every schema has fixed sections, and those record no open questions
        self.assertNotIn("open_questions", prompts.NOTES_SCHEMA["properties"])
        self.assertNotIn("open_questions", prompts.NOTES_SCHEMA["required"])
        self.assertNotIn("open questions", prompts.notes_prompt("T", 1, 1, "x"))
        self.assertNotIn("open questions", prompts.plan_prompt("T", "source-t", "n", "i", "c", 5))


RAW = pathlib.Path("/Users/henrymac/Desktop/Wiki Project/LLM-Wiki-IFRS9/challenger/05_Technical_Build/raw")


@unittest.skipUnless((RAW / "13 - IFRS 9 Financial Instruments.pdf").exists(), "the source PDFs are not on this machine")
class RealSources(unittest.TestCase):
    """Fixes 6, 12, 13 on the real sources: the glossary's closing text, page-turn text, note markers, empty passages."""

    @classmethod
    def setUpClass(cls):
        opts = extract.schema_options(CHK)
        cls.text = {fn: extract.from_upload(fn, (RAW / fn).read_bytes(), 3000, **opts).text
                    for fn in ("13 - IFRS 9 Financial Instruments.pdf", "11 - IFRS 7 Financial Instruments Disclosures.pdf",
                               "08 - IFRS 9 Financial Instruments.pdf")}

    def blocks(self, fn, lab):
        return [b for b in self.text[fn].split("\n\n") if b.startswith(f"[{lab}]")]

    def test_definition_ends_before_the_closing_text(self):
        fn = "13 - IFRS 9 Financial Instruments.pdf"
        term = self.blocks(fn, TERM.replace("<term>", "transaction costs"))[0]
        self.assertNotIn("(g)", term)
        self.assertTrue(any("(g)" in b for b in self.blocks(fn, "p100")))

    def test_page_turn_gone(self):
        turn = sorted(CHK.page_turn, key=len)[0]
        for t in self.text.values():
            self.assertNotIn(turn, t)

    def test_notes_split_at_markers(self):
        fn = "13 - IFRS 9 Financial Instruments.pdf"
        mk = re.compile(re.escape(CHK.note_markers[0]).replace(re.escape("<n>"), r"\d+"))
        for b in self.blocks(fn, ed("2.1")):
            self.assertLessEqual(len(mk.findall(b)), 1)

    def test_empty_passages_gone(self):
        self.assertFalse(self.blocks("11 - IFRS 7 Financial Instruments Disclosures.pdf", ed("21A")))
        self.assertFalse(self.blocks("08 - IFRS 9 Financial Instruments.pdf", "p62"))


if __name__ == "__main__":
    unittest.main()


class ParagraphFixes(unittest.TestCase):
    """A sentence citing one paragraph several times names it once; fix rounds rewrite only the paragraphs that fail."""

    def test_repeated_citation_named_once(self):
        page = (f"X includes: (a) one [[{S}|B1]](a); (b) two [[{S}|B1]](b); (c) three [[{S}|B1]](c).")
        f = checks.section_failures(page, [], {"B1": GUIDE_KIND}, S, CHK, covers, {"B1"})
        self.assertEqual(len(f), 1)
        self.assertIn("citing B1 of", f[0])
        self.assertEqual(list(fixpass._failing_paragraphs(f)), [("B1", S)])  # so the quote step can quote it

    def test_failure_blocks(self):
        blocks = [f"## H\n\n", f"{GUIDE_OPENER} that A [[{S}|B1]].", f"B says this [[{S}|B2]].", f"C [[{S}|1.1]] (a) x (b) y."]
        blocks = [b for b in blocks if b.strip()]
        f = checks.section_failures("\n\n".join(blocks), [], {"B1": GUIDE_KIND, "B2": GUIDE_KIND}, S, CHK, covers, {"B1", "B2"})
        self.assertEqual([fixpass.failure_blocks(blocks, x) for x in f], [{2}])
        part = f"Paragraph 1.1 of [[{S}]] has lettered or numbered parts (a), (b), (c); (c) do not appear on the page."
        self.assertEqual(fixpass.failure_blocks(blocks, part), {3})

    def test_only_failing_paragraphs_rewritten(self):
        import asyncio
        blocks = [f"{GUIDE_OPENER} that A [[{S}|B1]].", f"B says this [[{S}|B2]].", f"C [[{S}|B3]]."]
        kinds = {"B1": GUIDE_KIND, "B2": GUIDE_KIND, "B3": GUIDE_KIND}
        chk = lambda x: checks.section_failures(x, [], kinds, S, CHK, covers, set(kinds))
        sent = []

        async def fake(system, prompt, schema):  # the writer: puts the opener on the paragraph it is sent
            part = re.search(r"<paragraph>\n(.*)\n</paragraph>", prompt, re.S).group(1)
            sent.append(part)
            return {"content_md": f"{GUIDE_OPENER} that {part[0].lower()}{part[1:]}"}
        real = fixpass.llm.generate_json
        fixpass.llm.generate_json = fake
        try:
            rec = []
            out = asyncio.run(fixpass.fix_rounds(schema="", slug="p", title="P", text="\n\n".join(blocks), check=chk,
                                                 sources_text="", linkable="", parse=lambda r: r, kind="section", record=rec))
        finally:
            fixpass.llm.generate_json = real
        self.assertEqual(sorted(sent), sorted(blocks[1:]))  # the passing paragraph is not sent
        self.assertEqual(chk(out), [])
        self.assertTrue(out.startswith(blocks[0]))
        self.assertEqual(rec[0]["rounds"][0]["paragraphs_kept"], 2)


class SharedFailuresAndQuotes(unittest.TestCase):
    """The keep rule for a paragraph's rewrite; the quote step choosing passages by the whole failing sentence; a
    citation naming no location and no clause number made plain text, real citation forms never."""

    def test_shared_failure_does_not_block(self):
        cond = f"Paragraph 1 of [[{S}]] states the condition(s) 'a', 'b', which do not appear where the page writes it up."
        less = f"Paragraph 1 of [[{S}]] states the condition(s) 'a', which do not appear where the page writes it up."
        more = f"Paragraph 1 of [[{S}]] states the condition(s) 'a', 'b', 'c', which do not appear where the page writes it up."
        self.assertFalse(fixpass._worse([cond], [cond], {cond}))  # a shared failure left as it was
        self.assertFalse(fixpass._worse([cond], [less], {cond}))  # ... or finding less missing
        self.assertFalse(fixpass._worse([cond], [], {cond}))
        self.assertTrue(fixpass._worse([cond], [more], {cond}))  # finding more missing is worse
        self.assertTrue(fixpass._worse([cond], [cond, "A new failure"], {cond}))

    def test_rewrite_kept_with_shared_failure_left(self):
        import asyncio
        kinds = {"N1": GUIDE_KIND}
        blocks = [f"A says [[{S}|N1]]. B says [[{S}|N1]].", f"C says [[{S}|N1]]."]
        given = ["[N1] Text " + CHK.conditions[0] + " it applies."]
        chk = lambda x: checks.section_failures(x, given, kinds, S, CHK, covers, {"N1"})
        self.assertEqual(sum("states the condition" in f for f in chk("\n\n".join(blocks))), 1)  # shared by both

        async def fake(system, prompt, schema):  # puts the opener on each sentence, leaves the condition out
            part = re.search(r"<paragraph>\n(.*)\n</paragraph>", prompt, re.S).group(1)
            return {"content_md": re.sub(r"(^|\. )([A-C]) says", lambda m: f"{m.group(1)}{GUIDE_OPENER} that {m.group(2)} says", part)}
        real = fixpass.llm.generate_json
        fixpass.llm.generate_json = fake
        try:
            rec = []
            out = asyncio.run(fixpass.fix_rounds(schema="", slug="p", title="P", text="\n\n".join(blocks), check=chk,
                                                 sources_text="", linkable="", parse=lambda r: r, kind="section", record=rec))
        finally:
            fixpass.llm.generate_json = real
        self.assertEqual([f for f in chk(out) if "open with" in f], [])  # both rewrites kept: the openers are there
        self.assertEqual(rec[0]["rounds"][0]["paragraphs_kept"], 2)

    def test_pieces_from_whole_sentence(self):
        parts = [f"[{ed('3.2.3')}] alpha beta gamma delta epsilon", f"[{ed('3.2.3')}] zeta eta theta iota kappa lambda mu"]
        page = f"Alpha beta zeta eta theta iota kappa lambda mu [[{S}|{ed('3.2.3')}]]."
        fail = f'The sentence citing {ed("3.2.3")} of [[{S}]] ("Alpha beta...") comes from x but does not open'
        self.assertEqual(_failing_pieces(parts, [fail]), [parts[0]])  # its opening words alone point to the first
        self.assertEqual(_failing_pieces(parts, [fail], page), [parts[1]])  # the whole sentence, to the second

    def test_no_location_is_text(self):
        ctx = {"labels": {S: {"36", "B23", ed("2.1"), TERM.replace("<term>", "fair value"), "p3", "5B", "5D"}}}
        self.assertEqual(fixpass.names_no_location(f"For the purpose of this [[{S}|IFRS]], x.", ctx, CHK),
                         "For the purpose of this IFRS, x.")
        for lab in ("36", "36(a)", "B23", ed("2.1"), TERM.replace("<term>", "fair value"), "p3", "5B–5D",
                    TERM.replace("<term>", "a term it lacks"), ed("9.9")):  # real forms, and forms the checks judge
            link = f"[[{S}|{lab}]]"
            self.assertEqual(fixpass.names_no_location(f"A {link}.", ctx, CHK), f"A {link}.", lab)
        self.assertEqual(fixpass.names_no_location("A [[other-page|Some words]].", ctx, CHK), "A [[other-page|Some words]].")


class FailureOnTheCitation(unittest.TestCase):
    """A failure quoting a source passage (not the page) points to the paragraph holding the citation it names."""

    def test_falls_through_to_the_citation(self):
        blocks = ["## H", f"In Scenario 3, X [[{S}|IE111|(a)]].", f"Other [[{S}|IE110]]."]
        f = (f"The citation [[{S}|IE111|(a)]] does not name a paragraph of that source: cite the paragraph's own label. "
             f'The sentence rests on the passage under "IE111" ("(Illustrative example) Scenario 3: Reclassification '
             f'out of ..."): cite [[{S}|IE111]].')
        self.assertEqual(fixpass.failure_blocks(blocks, f), {1})


class LabelsAndKeptCitations(unittest.TestCase):
    """A label written with a second separator takes its first part; a dropped citation is named in the next round."""

    def test_second_separator(self):
        ctx = {"labels": {S: {"IE111"}}}
        self.assertEqual(fixpass.normalise_labels(f"X [[{S}|IE111|(a)]].", ctx), f"X [[{S}|IE111]](a).")
        self.assertEqual(fixpass.normalise_labels(f"X [[{S}|IE999|(a)]].", ctx), f"X [[{S}|IE999|(a)]].")  # not its label

    def test_dropped_citation_named_next_round(self):
        import asyncio
        kinds = {"B1": GUIDE_KIND}
        page = f"X says [[{S}|B1]] and more [[{S}|36]]."
        chk = lambda x: checks.section_failures(x, [], kinds, S, CHK, covers, {"B1", "36"})
        prompts_seen = []

        async def fake(system, prompt, schema):  # drops 36 the first time; keeps it once told to
            prompts_seen.append(prompt)
            told = "Keep the citation" in prompt
            return {"content_md": f"{GUIDE_OPENER} that X says [[{S}|B1]]." + (f" More [[{S}|36]]." if told else "")}
        real = fixpass.llm.generate_json
        fixpass.llm.generate_json = fake
        try:
            rec = []
            out = asyncio.run(fixpass.fix_rounds(schema="", slug="p", title="P", text=page, check=chk, sources_text="",
                                                 linkable="", parse=lambda r: r, kind="section", record=rec,
                                                 clause=lambda c: True))
        finally:
            fixpass.llm.generate_json = real
        self.assertIn(f"[[{S}|36]]", out)
        self.assertIn("Keep the citation", prompts_seen[-1])
        self.assertEqual(chk(out), [])
