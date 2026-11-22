"""Stale-claim check and contradiction list (Checks: Newer version, Contradiction callout): both optional lists, off
when a schema does not give them; reading them; finding an upload's earlier version; the pages citing what it changed;
and the callout lines lint lists. Reports only: nothing here writes. Run from Wiki/: python -m unittest tests.test_stale_claims"""
import asyncio
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.ops import lint, stale
from app.wiki import checks

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"
FORM = "> [!warning] Contradiction: <location A> says <claim A>; <location B> says <claim B>."
NEWER = ("- Newer version: a source with the same issuer and part as an earlier source of the wiki, where both are given, "
         "and a different content hash; it is compared with the most recent such source. Its paragraphs are matched to the "
         "earlier source's by paragraph label: a paragraph whose text differs (ignoring spacing) is changed, and one whose "
         "label the newer source does not hold is removed.")
CALLOUT = f'- Contradiction callout: "{FORM}" Lint lists every line in this form on the pages: the page, the two locations and what each says.'


def with_lines(schema: str, *lines: str) -> str:
    """The schema with lines added at the end of its Checks section."""
    head, rest = schema.split("## Checks", 1)
    body, *after = rest.split("\n## ", 1)
    return head + "## Checks" + body.rstrip("\n") + "\n" + "\n".join(lines) + "\n" + ("\n## " + after[0] if after else "")


class Optional(unittest.TestCase):
    def test_existing_schemas_load_as_before(self):
        for name in ("ifrs9-schema-3.17.md", "ifrs9-schema-3.19.md"):
            c = checks.load((SCHEMAS / name).read_text())
            with self.subTest(name):
                self.assertEqual((c.missing, c.unreadable, c.unknown, c.answer_missing), ([], [], [], []))
                self.assertEqual(checks.schema_errors(c), [])
                self.assertEqual((c.newer_version, c.contradiction_form), ({}, ""))  # both off

    def test_read_when_given(self):
        c = checks.load(with_lines((SCHEMAS / "ifrs9-schema-3.19.md").read_text(), NEWER, CALLOUT))
        self.assertEqual(checks.schema_errors(c), [])
        self.assertEqual(c.newer_version, {"same": ["issuer", "part"], "given": True, "spacing": True})
        self.assertEqual(c.contradiction_form, FORM)

    def test_unreadable_or_none(self):
        base = (SCHEMAS / "ifrs9-schema-3.19.md").read_text()
        c = checks.load(with_lines(base, "- Newer version: whenever it looks newer", '- Contradiction callout: "> [!warning] no parts"'))
        self.assertEqual(c.unreadable, ["newer version", "contradiction callout"])
        c = checks.load(with_lines(base, "- Newer version: none", "- Contradiction callout: none"))
        self.assertEqual((checks.schema_errors(c), c.newer_version, c.contradiction_form), ([], {}, ""))

    def test_off_reads_nothing(self):  # no list: no report and no database read
        c = checks.load((SCHEMAS / "ifrs9-schema-3.19.md").read_text())
        self.assertIsNone(asyncio.run(stale.report(None, {"id": None}, "", {}, c)))


class Callout(unittest.TestCase):
    def test_lines_in_the_form(self):
        text = "\n".join([
            "Some claim.",
            '> [!warning] Contradiction: [[source-a|1.2]] says "x; y says z"; [[source-b|3]] says "w".',
            "> [!warning] Contradiction: [[source-a|4]] says “p”; [[source-b|5]] says “q”",  # no full stop
            "> [!warning] Contradiction: nothing in the form",
        ])
        self.assertEqual(checks.form_lines(text, FORM), [
            {"location A": "[[source-a|1.2]]", "claim A": '"x; y says z"', "location B": "[[source-b|3]]", "claim B": '"w"'},
            {"location A": "[[source-a|4]]", "claim A": "“p”", "location B": "[[source-b|5]]", "claim B": "“q”"}])

    def test_lint_list(self):
        pages = [{"slug": "a", "title": "A", "content_md": f'> [!warning] Contradiction: [[s|1]] says "x"; [[t|2]] says "y".'},
                 {"slug": "b", "title": "B", "content_md": "No callout."}]
        got = lint.contradictions(pages, FORM)
        self.assertEqual([(x["slug"], x["parts"]["location B"], x["parts"]["claim B"]) for x in got], [("a", "[[t|2]]", '"y"')])


RULE = {"same": ["issuer", "part"], "given": True, "spacing": True}
T = lambda d: datetime(2026, 11, d, tzinfo=timezone.utc)
doc = lambda **kw: {"document": kw}


class Earlier(unittest.TestCase):
    OTHERS = [{"slug": "s-1", "title": "Old", "meta": doc(issuer="Body", part="Std A", edition="2024"), "created_at": T(1)},
              {"slug": "s-2", "title": "Older edit", "meta": doc(issuer="body ", part="Std  A", edition="2025"), "created_at": T(5)},
              {"slug": "s-3", "title": "Other part", "meta": doc(issuer="Body", part="Std B"), "created_at": T(9)},
              {"slug": "s-4", "title": "No part", "meta": doc(issuer="Body"), "created_at": T(9)}]

    def test_most_recent_same_issuer_and_part(self):
        got = stale.earlier_version(doc(issuer="Body", part="Std A", edition="2026"), self.OTHERS, RULE)
        self.assertEqual(got["slug"], "s-2")  # case and spacing aside

    def test_both_must_be_given(self):
        self.assertIsNone(stale.earlier_version(doc(issuer="Body"), self.OTHERS, RULE))
        self.assertIsNone(stale.earlier_version(doc(issuer="Body", part="Std C"), self.OTHERS, RULE))
        self.assertIsNone(stale.earlier_version(None, self.OTHERS, RULE))


class Compare(unittest.TestCase):
    OLD = stale.by_label("[1.1] Keep this.\n\n[1.2] Old wording.\n\n[1.3] Gone soon.\n\n[1.4] Spacing  only.")
    NEW = stale.by_label("[1.1] Keep this.\n\n[1.2] New wording.\n\n[1.4] Spacing only.\n\n[1.5] Added.")
    PAGES = [{"slug": "p", "title": "P", "content_md": "A [[source-old|1.2(a)]] and [[source-old|1.1]] and [[source-old|1.3]]."},
             {"slug": "q", "title": "Q", "content_md": "Only [[source-old|1.4]] and [[source-new|1.2]]."},
             {"slug": "r", "title": "R", "content_md": "Another source: [[source-x|1.2]]."}]

    def test_pages_citing_what_changed(self):
        got = stale.compare(self.OLD, self.NEW, self.PAGES, "source-old", spacing=True)
        self.assertEqual((got["changed"], got["removed"]), (1, 1))
        self.assertEqual([p["slug"] for p in got["pages"]], ["p"])
        self.assertEqual(got["pages"][0]["paragraphs"], [
            {"label": "1.2", "status": "changed", "old": "Old wording.", "new": "New wording."},
            {"label": "1.3", "status": "removed", "old": "Gone soon.", "new": None}])

    def test_spacing_counts_when_the_schema_does_not_say_to_ignore_it(self):
        got = stale.compare(self.OLD, self.NEW, self.PAGES, "source-old", spacing=False)
        self.assertEqual(got["changed"], 2)
        self.assertEqual([p["slug"] for p in got["pages"]], ["p", "q"])


if __name__ == "__main__":
    unittest.main()
