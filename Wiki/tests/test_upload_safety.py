"""Upload safety: uploads to a wiki take turns, a changeset written against an older wiki is never half applied, and an
upload can be run again from the passages it saved."""
import asyncio
import unittest
import uuid
from unittest import mock

from app import jobs
from app.ops import ingest
from app.wiki import store
from app.wiki.store import Op

W = uuid.uuid4()


def row(op, slug, base=None):
    return {"op": op, "slug": slug, "title": slug, "type": "topic", "summary": "", "content_md": "x", "tags": [],
            "base_version": base, "change_note": "", "holds": None}


class ConflictRule(unittest.TestCase):
    def test_rules(self):
        self.assertIsNone(store._conflict(Op(op="create", slug="a"), None))
        self.assertIn("created elsewhere", store._conflict(Op(op="create", slug="a"), {"version": 1}))
        self.assertIn("v3, op written against v2", store._conflict(Op(op="update", slug="a", base_version=2), {"version": 3}))
        self.assertIsNone(store._conflict(Op(op="update", slug="a", base_version=3), {"version": 3}))

    def test_stale_ops(self):
        pages = [{"slug": "a", "version": 2}, {"slug": "b", "version": 1}]
        with mock.patch.object(store, "get_pages", mock.AsyncMock(return_value=pages)):
            out = asyncio.run(store.stale_ops(W, [row("update", "a", 1), row("update", "b", 1), row("create", "c")]))
        self.assertEqual([x["slug"] for x in out], ["a"])


class ApplyAllOrNothing(unittest.TestCase):
    def test_conflicting_changeset_is_refused_before_anything_is_paid_for(self):
        cs = {"id": uuid.uuid4(), "status": "pending", "wiki_id": W}
        embed = mock.AsyncMock()
        with mock.patch.object(store, "get_changeset", mock.AsyncMock(return_value=(cs, [row("update", "a", 1)]))), \
             mock.patch.object(store, "get_pages", mock.AsyncMock(return_value=[{"slug": "a", "version": 2}])), \
             mock.patch.object(store.llm, "embed", embed):
            with self.assertRaises(store.Conflicts) as e:
                asyncio.run(store.apply_changeset(cs["id"]))
        self.assertEqual(e.exception.conflicts[0]["slug"], "a")
        embed.assert_not_called()

    def test_auto_commit_with_conflicts_stays_pending(self):
        cs_id = uuid.uuid4()
        with mock.patch.object(store, "create_changeset", mock.AsyncMock(return_value=cs_id)), \
             mock.patch.object(store, "apply_changeset", mock.AsyncMock(side_effect=store.Conflicts([{"slug": "a", "reason": "r"}]))):
            res = asyncio.run(store.commit(W, "ingest", "s", [Op(op="update", slug="a", base_version=1)], "auto"))
        self.assertEqual(res["status"], "pending")
        self.assertEqual(res["conflicts"], [{"slug": "a", "reason": "r"}])


class UploadsTakeTurns(unittest.TestCase):
    def test_waits_while_blocked_and_starts_when_released(self):
        async def go():
            wiki = uuid.uuid4()
            blocked = {"on": True}
            ran, waits = [], []
            blocker = mock.AsyncMock(side_effect=lambda w, j: {"message": "pending"} if blocked["on"] else None)
            run = mock.AsyncMock(side_effect=lambda j, w, fn: ran.append(j))
            with mock.patch.object(jobs, "_blocker", blocker), mock.patch.object(jobs, "_run", run), \
                 mock.patch.object(jobs, "_waiting", mock.AsyncMock(side_effect=lambda j, why: waits.append((j, why)))), \
                 mock.patch.object(jobs, "WAIT_S", 60):
                a = asyncio.create_task(jobs._turn("a", wiki, None))
                b = asyncio.create_task(jobs._turn("b", wiki, None))
                await asyncio.sleep(0.05)
                self.assertEqual(ran, [])  # a waits for the pending changeset, b waits behind a
                self.assertIn(("b", {"message": "Waiting: an earlier upload to this wiki goes first."}), waits)
                blocked["on"] = False
                jobs.release(wiki)  # the changeset was applied or discarded: no 60 s wait
                await asyncio.wait_for(asyncio.gather(a, b), 2)
            self.assertEqual(ran, ["a", "b"])  # in the order they were made
        asyncio.run(go())


class SavedUpload(unittest.TestCase):
    def test_rebuilt_from_saved_passages_without_the_stored_file(self):
        src = {"id": uuid.uuid4(), "slug": "source-x", "title": "X", "kind": "docx", "text": "a\n\nb",
               "meta": {"document": {"issuer": "I"}, "file": {"path": "p"}}, "sections": ["a", "b"]}
        conn = mock.MagicMock()
        conn.execute = mock.AsyncMock(return_value=mock.Mock(fetchone=mock.AsyncMock(return_value=src)))
        pool = mock.MagicMock()
        pool.connection.return_value.__aenter__ = mock.AsyncMock(return_value=conn)
        pool.connection.return_value.__aexit__ = mock.AsyncMock(return_value=False)
        with mock.patch.object(ingest, "get_pool", return_value=pool):
            source, ex = asyncio.run(ingest.saved_upload(W, "source-x"))
        self.assertEqual(source["slug"], "source-x")
        self.assertEqual((ex.title, ex.kind, ex.sections), ("X", "docx", ["a", "b"]))
        self.assertEqual(ex.meta, {"document": {"issuer": "I"}})
        src["sections"] = None  # saved before passages were kept
        with mock.patch.object(ingest, "get_pool", return_value=pool):
            self.assertIsNone(asyncio.run(ingest.saved_upload(W, "source-x")))


if __name__ == "__main__":
    unittest.main()
