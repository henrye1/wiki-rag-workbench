"""Run downloads: one row per topic, run and system; answers as given; the review page escapes text; a memo file name
left in a download is found. Run from UI/server: python -m unittest tests.test_run_export"""
import csv
import io
import unittest

from app import run_export, scorecard

LABEL = {"rag": "RAG (per topic)", "wiki": "Wiki"}
RUN = {
    "config": {"systems_compared": ["rag", "wiki"], "judge_model": "judge", "runs": 1},
    "reference_label": "Reference memo 1",
    "topics": {"1": {"number": 1, "code": "2.1", "title": "ECL <basics>", "section": "S", "question": "Q1. What?",
                     "reference": "memo text", "key_points": [{"id": "K1", "kind": "standard", "point": "P"}],
                     "runs": {"1": {"winner": "wiki", "systems": {
                         "rag": {"answer": "A", "similarity": 3, "coverage": 40, "grades": {"K1": "missing"}, "read": [{"para_ref": "5.5.3"}]},
                         "wiki": {"answer": "B [[source-x|5.5.3]]", "similarity": 6, "coverage": 70, "grades": {"K1": "full"},
                                  "read": [{"slug": "p", "title": "Page"}]}}}}}},
}


def rows(blob):
    return list(csv.reader(io.StringIO(blob.decode("utf-8").lstrip("﻿"))))


class RunExport(unittest.TestCase):
    def test_results_one_row_per_system(self):
        r = rows(run_export.results_csv(RUN, LABEL))
        self.assertEqual(len(r), 3)
        self.assertEqual(r[2][5:8], ["Wiki", "6", "70"])
        self.assertEqual(r[2][10:13], ["1", "0", "0"])  # key points full / partial / missing

    def test_answers_as_given(self):
        r = rows(run_export.answers_csv(RUN, LABEL))
        self.assertEqual(r[2][6], "B [[source-x|5.5.3]]")
        self.assertEqual(r[1][7], "5.5.3")
        self.assertEqual(r[2][7], "Page")

    def test_review_escapes_and_shows_labels(self):
        page = run_export.review_html(RUN, LABEL, "r1").decode()
        self.assertIn("ECL &lt;basics&gt;", page)
        self.assertIn("B 5.5.3", page)  # a wiki link shows its label
        self.assertIn("Reference memo 1", page)

    def test_scorecard_as_the_page(self):
        run = {**RUN, "summary": {"by_system": {"rag": {"similarity": {"mean": 3.1, "n": 2}}, "wiki": {"similarity": {"mean": 4.3, "n": 2}}},
                                  "wins_by_run": {"rag": 1, "wiki": 3},
                                  "gaps": {"similarity": {"diff": 1.2, "ci": [0.5, 1.9], "verdict": "Wiki better", "leader": "wiki"}}}}
        r = rows(run_export.scorecard_csv(run, LABEL))
        self.assertEqual(len(r) - 1, len(scorecard.ORDER))
        self.assertEqual(r[1][1:4], ["Similarity (0–10)", "3.1/10", "4.3/10"])
        self.assertEqual(r[1][6:12], ["+1.20", "1.2", "+0.50 to +1.90", "0.5", "1.9", "Wiki better"])
        cov = next(x for x in r if x[1] == "Coverage")
        self.assertEqual((cov[2], cov[13]), ("Not run yet", "no graded answers"))

    def test_memo_file_name_is_found(self):
        self.assertEqual(run_export.unmasked(b"see Secret memo.docx", ["Secret memo.docx"]), ["Secret memo.docx"])
        self.assertEqual(run_export.unmasked(b"Reference memo 1", ["Secret memo.docx"]), [])


if __name__ == "__main__":
    unittest.main()
