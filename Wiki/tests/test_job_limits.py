"""Formulas through the line-break step, the fix rounds' limits (per page in a job; none after a round that fixes
nothing) and a job's spending cap. No model call.
Run from Wiki/: python -m unittest tests.test_job_limits"""
import asyncio
import unittest
from unittest import mock

from app import llm
from app.config import get_settings
from app.ops import fixpass
from app.ops.ingest import _fix_breaks

SENTENCE = ("$\\rho_{ij}$: Pairwise loss correlation coefficient between counterparts $i$ and $j$ ($\\rho_{ii} = 1$, "
            "$\\rho_{ij} \\lt 1$ for $i \\neq j$).")


class Formulas(unittest.TestCase):
    def test_the_sentence_keeps_its_backslashes(self):
        self.assertEqual(_fix_breaks(SENTENCE), SENTENCE)
        self.assertIn("$i \\neq j$", _fix_breaks(SENTENCE + "\\n\\nNext paragraph."))

    def test_nu_and_nabla(self):
        for f in ("$\\nu$", "$\\nabla f$", "$$\\sum_{k} \\nu_k \\neq 0$$"):
            self.assertEqual(_fix_breaks(f"The term {f} is used."), f"The term {f} is used.")

    def test_an_escaped_line_break_outside_a_formula_still_breaks(self):
        self.assertEqual(_fix_breaks("First line.\\nSecond line."), "First line.\nSecond line.")

    def test_money_is_no_formula(self):
        self.assertEqual(_fix_breaks("It costs $5 and $10.\\nNext."), "It costs $5 and $10.\nNext.")


def run(coro):
    return asyncio.run(coro)


class FixRounds(unittest.TestCase):
    def rounds(self, slug, check, fixed_text):
        calls = []

        async def fake_fix(**kw):
            calls.append(kw["failures"])
            return fixed_text(kw["text"]), {}

        record = []
        with mock.patch.object(fixpass, "_fix_blocks", fake_fix):
            text = run(fixpass.fix_rounds(schema="", slug=slug, title="t", text="bad", check=check, sources_text="",
                                          linkable="", parse=lambda x: x, kind="section", record=record))
        return text, calls, record

    def test_stops_when_failures_do_not_go_down(self):
        _, calls, record = self.rounds("p", lambda t: ["fails"], lambda t: t)
        self.assertEqual(len(calls), 1)
        self.assertEqual(record[0]["rounds"][0]["stopped"], "failures did not go down")

    def test_two_rounds_when_each_improves(self):
        steps = {"bad": "better", "better": "good"}
        check = lambda t: {"bad": ["a", "b"], "better": ["a"], "good": []}[t]
        text, calls, _ = self.rounds("p", check, lambda t: steps[t])
        self.assertEqual((text, len(calls)), ("good", 2))

    def test_at_most_two_per_page_over_all_its_checks(self):
        async def job():
            fixpass.track_rounds()
            steps = {"bad": "better", "better": "best", "best": "best"}
            check = lambda t: {"bad": ["a", "b", "c"], "better": ["a", "b"], "best": ["a"]}[t]
            used = []

            async def fake_fix(**kw):
                used.append(kw["slug"])
                return steps[kw["text"]], {}

            with mock.patch.object(fixpass, "_fix_blocks", fake_fix):
                for kind in ("section", "page as saved"):
                    await fixpass.fix_rounds(schema="", slug="p", title="t", text="bad", check=check, sources_text="",
                                             linkable="", parse=lambda x: x, kind=kind, record=[])
                await fixpass.fix_rounds(schema="", slug="q", title="t", text="bad", check=check, sources_text="",
                                         linkable="", parse=lambda x: x, kind="section", record=[])
            return used

        self.assertEqual(run(job()), ["p", "p", "q", "q"])  # p's second check has no round left


class SpendCap(unittest.TestCase):
    def setUp(self):
        s = get_settings()
        self.patch = mock.patch.object(s, "model_prices", "carbon=2/10, hydrogen=1.5/7.5")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_cost_counts_thinking_as_output(self):
        calls = [{"step": "json", "model": "carbon", "input_tokens": 1_000_000, "output_tokens": 100_000,
                  "thinking_tokens": 900_000}, {"step": "embed", "model": "e", "texts": 3}]
        self.assertAlmostEqual(llm.cost_usd(calls), 2 + 10)

    def test_stops_once_the_cap_is_reached(self):
        async def job():
            llm.track_usage(cap_usd=1.0)
            llm._within_cap("carbon")  # nothing spent yet
            llm._record({"step": "json", "model": "carbon", "input_tokens": 0, "output_tokens": 100_000, "thinking_tokens": 0})
            try:
                try:
                    llm._within_cap("carbon")
                except Exception:  # a step that carries on past a failed call does not catch it
                    return "caught by except Exception"
            except llm.SpendCapReached as e:
                return str(e)

        self.assertEqual(run(job()), "Spending cap reached: $1.00 of $1.00")

    def test_a_model_with_no_price_is_refused_under_a_cap(self):
        async def job():
            llm.track_usage(cap_usd=5)
            with self.assertRaises(llm.SpendCapReached):
                llm._within_cap("unpriced")
            llm.track_usage()  # no cap: no price needed
            llm._within_cap("unpriced")

        run(job())


if __name__ == "__main__":
    unittest.main()
