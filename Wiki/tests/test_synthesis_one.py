"""One answer into a synthesis page: its own page name, and the questions an existing page records kept first."""
import unittest

from app.ops import synthesis

A = [{"searched": "What is X?", "answer": "X is [[source-p|1]].", "sources": "all", "date": "2026-11-09T10:00:00"}]


class OneAnswer(unittest.TestCase):
    def test_own_page_name_differs_from_the_chat(self):
        chat = synthesis.slug_for("abcd1234-5678", A, ["topic-a"], "Wiki")
        one = synthesis.slug_for("abcd1234-5678", A, ["topic-a"], "Wiki", seq=3)
        self.assertEqual(one, chat + "q3")

    def test_record_keeps_earlier_questions(self):
        rows, rest = synthesis.split_record(synthesis.record(A) + "\n\nBody text.")
        self.assertEqual(rows, ["What is X? — answered 2026-11-09, Sources: All"])
        self.assertEqual(rest, "Body text.")
        merged = synthesis.record([{**A[0], "searched": "What is Y?"}], earlier=rows)
        self.assertIn("1. What is X?", merged)
        self.assertIn("2. What is Y?", merged)

    def test_page_without_record(self):
        self.assertEqual(synthesis.split_record("Just text."), ([], "Just text."))


if __name__ == "__main__":
    unittest.main()
