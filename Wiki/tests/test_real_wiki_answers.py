"""The answer side and lint against a real wiki's pages and sources, read only: every query is a SELECT and nothing is
written. The wiki is ifrs9-wiki3 (env TEST_WIKI to choose another), checked with schema 3.17's Checks; skipped where the
database cannot be reached. No AI call. Run from Wiki/: .venv/bin/python -m unittest tests.test_real_wiki_answers"""
import os
import pathlib
import re
import unittest

from app.db import close_pool, get_pool, open_pool
from app.ops import answering, fixpass, lint, pagecheck, watchdog
from app.ops.query import standard_only
from app.wiki import checks, store

SCHEMA = (pathlib.Path(__file__).resolve().parent.parent / "schemas" / "ifrs9-schema-3.17.md").read_text()
CHK = checks.load(SCHEMA)
WIKI = os.environ.get("TEST_WIKI", "ifrs9-wiki3")
H, NONE = CHK.answer_headings, CHK.answer_none
OBLIGE = CHK.force_words[CHK.force_strict]
AG = "application guidance"


class RealWiki(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            await open_pool()
            async with get_pool().connection() as conn:
                self.wiki = await (await conn.execute("select id, slug, schema_md from wiki.wikis where slug = %s", (WIKI,))).fetchone()
        except Exception as e:  # no database here
            self.skipTest(f"database not reachable: {e}")
        if not self.wiki:
            self.skipTest(f"no wiki {WIKI}")
        self.srcs = await pagecheck.sources(self.wiki["id"])
        self.pages = await store.list_pages(self.wiki["id"], with_content=True)
        self.kind = lambda sl, lab: answering.kind_of(self.srcs, CHK, sl, lab)

    async def asyncTearDown(self):
        await close_pool()

    def paragraph(self, want_kind: str, has=(), lacks=()) -> tuple[str, str, str]:
        """A real paragraph of the given kind ("" the Standard's own text) whose text has the words has and none of lacks."""
        for sl, info in sorted(self.srcs.items()):
            for lab, ps in info["by_label"].items():
                text = " ".join(ps)
                if (self.kind(sl, lab) == want_kind and all(answering._has(text, w) for w in has)
                        and not any(answering._has(text, w) for w in lacks) and len(ps) == 1):
                    return sl, lab, text
        self.skipTest(f"no paragraph of kind {want_kind!r} with {has} and without {lacks}")

    def fails(self, text: str) -> list[str]:
        return answering.failures(text, CHK, self.srcs, {"labels": {}, "matchers": {}, "names": set()})

    def answer(self, main: str, apart: str = "") -> str:
        cited = sorted({f"[[{sl}|{lab}]]" for sl, lab in answering._source_cites(main + apart)})
        return (f"{H[0]}\n\n{main}\n\n{H[1]}\n\n" + "\n".join(f"- {c}" for c in cited)
                + f"\n\n{H[2]}\n\n{NONE}\n\n{H[3]}\n\n{apart or NONE}\n")

    async def test_standard_only_keeps_only_the_standards_own_text_by_kind(self):
        mixed = 0
        for p in self.pages:
            if p["type"] not in ("topic", "subtopic"):
                continue
            out = standard_only(p["content_md"], lambda sl, lab: self.kind(sl, lab) == "")
            left = answering._source_cites(out)
            self.assertTrue(all(self.kind(sl, lab) == "" for sl, lab in left), p["slug"])
            before = answering._source_cites(p["content_md"])
            same_file = {sl for sl, lab in before if self.kind(sl, lab) == ""} & {sl for sl, lab in before if self.kind(sl, lab) == AG}
            if same_file and left and not [1 for sl, lab in left if self.kind(sl, lab) == AG]:
                mixed += 1  # a page citing one source's own text and its application guidance keeps only the first
        self.assertGreater(mixed, 0)

    async def test_force_words_against_real_paragraphs(self):
        with_cite = lambda word, sl, lab: self.answer(f"An entity {word} apply this [[{sl}|{lab}]].")
        other = next(w for w in OBLIGE if w != OBLIGE[0])
        sl, lab, _ = self.paragraph("", has=(OBLIGE[0],), lacks=(other,))
        self.assertTrue([f for f in self.fails(with_cite(other, sl, lab)) if f'"{other}"' in f])
        self.assertFalse([f for f in self.fails(with_cite(OBLIGE[0], sl, lab)) if "force" in f or f'"{OBLIGE[0]}"' in f])
        sl, lab, _ = self.paragraph(AG, lacks=tuple(OBLIGE))
        opener = CHK.openers[AG][0]
        text = self.answer(f"{opener} that an entity {other} apply this [[{sl}|{lab}]].")
        self.assertTrue([f for f in self.fails(text) if "obligation" in f])

    async def test_application_guidance_stays_in_the_answer(self):
        sl, lab, _ = self.paragraph(AG)
        opener = CHK.openers[AG][0]
        line = f"{opener} that this applies [[{sl}|{lab}]]."
        own_sl, own_lab, _ = self.paragraph("")
        main = f"This applies [[{own_sl}|{own_lab}]]."
        self.assertTrue([f for f in self.fails(self.answer(main, line)) if lab in f and "authoritative" in f])
        self.assertFalse([f for f in self.fails(self.answer(main + " " + line)) if lab in f and "authoritative" in f])

    async def test_a_quote_from_a_real_paragraph(self):
        sl, lab, text = self.paragraph("")
        words = re.sub(r"^\[[^\]]+\]\s*", "", text).split()
        quote = " ".join(words[: min(12, len(words))])
        self.assertEqual(watchdog.quote_failures([{"citation": f"[[{sl}|{lab}]]", "quote": quote}], self.srcs, CHK), [])
        self.assertTrue(watchdog.quote_failures([{"citation": f"[[{sl}|{lab}]]", "quote": quote + " invented"}], self.srcs, CHK))

    async def test_lint_runs_the_checks_it_can_and_names_the_rest(self):
        report = await lint.maintain({"id": self.wiki["id"], "schema_md": SCHEMA})
        got = {c["check"]: c for c in report["checks"]}
        self.assertEqual(sorted(got), [1, 2, 3, 4, 5, 6, 7])
        for n in (1, 4, 6):
            self.assertFalse(got[n]["run"])
            self.assertTrue(got[n]["reason"])
        for n in (2, 3, 5, 7):
            self.assertTrue(got[n]["run"])
            self.assertIn("failures", got[n])

    async def test_a_page_holding_only_the_empty_text_is_not_thin(self):
        with_schema = {r["slug"] for r in (await lint.structural(self.wiki["id"], CHK))["thin_pages"]}
        without = {r["slug"] for r in (await lint.structural(self.wiki["id"], checks.Checks()))["thin_pages"]}  # a schema giving no empty text
        empty = {p["slug"] for p in self.pages if lint._only_empty_text(p["content_md"], CHK)}
        self.assertEqual(with_schema, without - empty)

    async def test_the_page_list_is_never_cut(self):
        index = await store.compact_index(self.wiki["id"])
        self.assertEqual(len(index.split("\n")), len(self.pages))


if __name__ == "__main__":
    unittest.main()
