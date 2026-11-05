"""Offline tests of the routing rounds: no database, no AI call (the router is a stand-in). Run from Wiki/:
.venv/bin/python -m unittest discover tests"""
import asyncio
import unittest

from app import prompts
from app.ops.ingest import _route_rounds

NUMS = {1, 2, 3}  # the sections offered; 4 is a section the schema has but does not offer (its examples section)


def router(answer):
    """A stand-in router: answer(batch, call number) -> its assignments, or None for a failed call. Records each batch."""
    calls = []

    async def ask(batch):
        calls.append(list(batch))
        return answer(batch, len(calls))
    return ask, calls


def rounds(todo, ask, sizes=(4, 2, 1)):
    return asyncio.run(_route_rounds(todo, ask, NUMS, sizes))


class RouteRounds(unittest.TestCase):
    def test_a_passage_left_out_of_a_large_batch_is_placed_by_a_smaller_one(self):
        ask, calls = router(lambda b, n: [{"id": i, "section": 1} for i in b if len(b) < 4 or i != 3])
        owner, left = rounds([0, 1, 2, 3], ask)
        self.assertEqual((owner, left), ({0: 1, 1: 1, 2: 1, 3: 1}, {}))
        self.assertEqual(calls, [[0, 1, 2, 3], [3]])  # the next round asks only for what was missed

    def test_a_section_not_offered_is_not_taken(self):
        ask, _ = router(lambda b, n: [{"id": i, "section": 4 if len(b) > 1 else 2} for i in b])
        owner, left = rounds([0, 1], ask)
        self.assertEqual((owner, left), ({0: 2, 1: 2}, {}))

    def test_what_every_round_answered_is_kept_for_a_passage_still_unplaced(self):
        ask, calls = router(lambda b, n: None if n == 1 else [{"id": i, "section": 4 if i == 0 else 1} for i in b if i != 1])
        owner, left = rounds([0, 1, 2], ask, sizes=(3, 1))
        self.assertEqual(owner, {2: 1})
        self.assertEqual(left, {0: ["batch of 3: the call failed", "batch of 1: section 4, not offered"],
                                1: ["batch of 3: the call failed", "batch of 1: left out"]})

    def test_an_id_not_in_the_batch_is_ignored(self):
        ask, _ = router(lambda b, n: [{"id": 9, "section": 1}] + [{"id": i, "section": 3} for i in b])
        owner, left = rounds([0], ask)
        self.assertEqual((owner, left), ({0: 3}, {}))

    def test_the_last_round_asks_a_few_at_a_time(self):
        ask, calls = router(lambda b, n: [{"id": i, "section": 1} for i in b if len(b) <= 2])
        owner, left = rounds(list(range(6)), ask, sizes=(6, 2))
        self.assertEqual(left, {})
        self.assertEqual(calls, [list(range(6)), [0, 1], [2, 3], [4, 5]])


class RouteSchema(unittest.TestCase):
    def test_the_answer_is_held_to_the_sections_offered(self):
        rs = prompts.route_schema({3, 1, 2})
        self.assertEqual(rs["properties"]["assignments"]["items"]["properties"]["section"]["enum"], [1, 2, 3])
        self.assertNotIn("enum", prompts.ROUTE_SCHEMA["properties"]["assignments"]["items"]["properties"]["section"])


if __name__ == "__main__":
    unittest.main()
