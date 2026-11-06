"""Offline tests of how the answer checks find citations (checks-3): no database, no AI call. Run from Benchmark/:
.venv/bin/python -m unittest discover tests"""
import unittest

from bench import checks

S = "source-x"


def found(answer: str) -> list[tuple[str, str]]:
    return [(c["label"], c["statement"]) for c in checks.citations(answer)]


class Citations(unittest.TestCase):
    def test_a_line_holding_only_citations_is_not_counted(self):
        text = f"An entity shall do it [[{S}|1.1]].\n\n## Clause references\n[[{S}|1.1]]\n- [[{S}|1.2]]\n[[{S}|1.3]], [[{S}|1.4]]"
        self.assertEqual(found(text), [("1.1", "An entity shall do it.")])

    def test_only_the_group_that_ends_a_sentence_counts(self):
        text = f"An entity recognises the item [[{S}|9.9]] at cost [[{S}|1.1]], [[{S}|1.2]]. Bare [7.7] then [2.1]."
        self.assertEqual([lab for lab, _ in found(text)], ["1.1", "1.2", "2.1"])

    def test_a_link_in_passing_keeps_what_it_shows_in_the_statement(self):
        text = f"An entity recognises a [[concept-loss-allowance|loss allowance]] for it [[{S}|1.1]]."
        self.assertEqual(found(text), [("1.1", "An entity recognises a loss allowance for it.")])

    def test_list_parts_and_table_cells_end_with_their_own_citations(self):
        text = (f"An entity discloses: (a) one thing [[{S}|3(a)]]; (b) another [[{S}|3(b)]].\n"
                f"- (c) a part [[{S}|3(c)]]; and\n| Item | x [[{S}|7.1]] | y [[{S}|7.2]] |")
        self.assertEqual([lab for lab, _ in found(text)], ["3(a)", "3(b)", "3(c)", "7.1", "7.2"])

    def test_the_checks_version_records_the_change(self):
        self.assertEqual(checks.VERSION, "checks-3")


if __name__ == "__main__":
    unittest.main()
