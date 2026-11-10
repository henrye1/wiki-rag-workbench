"""The upload speed changes: identical pages are not saved again, unless their checks fail or what they hold changed."""
import asyncio
import unittest
from unittest import mock

from app.ops import ingest
from app.wiki.store import Op

PAGE = {"slug": "a", "title": "A", "type": "topic", "summary": "s", "content_md": "Text [[source-x|1]].", "tags": ["t"]}


def run(ops, failing=None, held=None):
    with mock.patch.object(ingest.store, "list_pages", mock.AsyncMock(return_value=[PAGE])), \
         mock.patch.object(ingest.store, "held_paragraphs", mock.AsyncMock(return_value=held or {})):
        return asyncio.run(ingest._without_unchanged("w", ops, failing or {}))


class Unchanged(unittest.TestCase):
    def same(self, **kw):
        return Op(op="update", slug="a", title="A", type="topic", summary="s", content_md="Text [[source-x|1]].", tags=["t"], **kw)

    def test_identical_update_is_dropped(self):
        ops, skipped = run([self.same(), Op(op="create", slug="b", title="B", type="topic", content_md="x")])
        self.assertEqual([o.slug for o in ops], ["b"])
        self.assertEqual(skipped, ["a"])

    def test_changed_text_is_kept(self):
        o = self.same(); o.content_md += " More."
        self.assertEqual(run([o])[1], [])

    def test_failing_page_is_kept(self):
        self.assertEqual(run([self.same()], failing={"a": ["x"]})[1], [])

    def test_new_holdings_are_kept(self):
        self.assertEqual(run([self.same(holds={"source-y": ["2"]})])[1], [])
        self.assertEqual(run([self.same(holds={"source-y": ["2"]})], held={"a": {"source-y": {"2"}}})[1], ["a"])


if __name__ == "__main__":
    unittest.main()
