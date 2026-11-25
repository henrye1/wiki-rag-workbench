"""Backslashes in a JSON reply's text are kept as written: the model is told to write them twice, and a backslash
command JSON read as a control character ("\\neq" as a line break and "eq") is put back. Run from Wiki/:
python -m unittest tests.test_json_backslashes"""
import asyncio
import json
import unittest
from unittest import mock

from app import llm

RAW = (r'{"content_md": "for $i \neq j$, $\theta \times 2$, $\frac{a}{b}$ and $\beta$, $\rho$; '
       r'$$a \neq b$$.\nA new line. It costs $5 and\nnext $10.", "tags": ["x \neq y? no math here"]}')


class Restore(unittest.TestCase):
    def test_commands_put_back(self):
        got = llm._restored(json.loads(RAW))
        t = got["content_md"]
        for cmd in ("\\neq j", "\\theta", "\\times", "\\frac{a}", "\\beta", "\\rho", "a \\neq b"):
            self.assertIn(cmd, t)

    def test_real_line_breaks_kept(self):
        t = llm._restored(json.loads(RAW))["content_md"]
        self.assertIn(".\nA new line.", t)  # outside a formula
        self.assertIn("$5 and\nnext $10", t)  # money, not a formula
        self.assertNotIn("\\next", t)
        self.assertEqual(llm._restored(json.loads(RAW))["tags"], ["x \neq y? no math here"])  # no formula: as read

    def test_written_twice_stays(self):
        self.assertEqual(llm._restored(json.loads(r'{"t": "$i \\neq j$"}'))["t"], "$i \\neq j$")

    def test_told_with_every_json_call(self):
        sent = []

        async def gen(system, prompt, schema=None, job=None):
            sent.append(system)
            return RAW

        with mock.patch.object(llm, "generate", gen):
            out = asyncio.run(llm.generate_json("sys", "p", {"type": "object"}))
        self.assertIn(llm.JSON_BACKSLASHES, sent[0])
        self.assertIn("\\neq j", out["content_md"])


if __name__ == "__main__":
    unittest.main()
