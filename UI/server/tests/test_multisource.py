"""Multi-source synthesis: each key point's document from its backing reference, multi-source topics, the two figures per
pair from the judge's stored grades, their gaps, and the scorecard rows and CSV column.
Run from UI/server: python -m unittest tests.test_multisource"""
import csv
import io
import unittest

from app import multisource, run_export, scorecard

DOCS = [{"name": "Doc 1 Part A", "tier": "standard", "labels": {"5.5.1", "5.5.17", "B5.5.1", "Appendix A: term"}},
        {"name": "Doc 1 Part B", "tier": "supporting", "labels": {"IE1", "IE2"}},
        {"name": "Doc 2 Part A", "tier": "standard", "labels": {"35F"}},
        {"name": "Doc 12 Part A", "tier": "standard", "labels": {"9"}}]


def kp(i, ref=None, kind="standard"):
    return {"id": i, "kind": kind, "point": "p", **({"ref": ref} if ref else {})}


# topic 1: three points from Doc 1 Part A, one from Doc 2 Part A, one with no backing paragraph
POINTS = [kp("K1", "5.5.1 (Doc 1 Part A)"), kp("K2", "B5.5.1 (Doc 1)"), kp("K3", "5.5.17(a) (Doc 1 Part A (Standard))"),
          kp("K4", "35F (Doc 2 Part A)"), kp("K5", kind="beyond_standard")]


def graded(*orders):
    return {"grades": orders[0], "grades_by_order": list(orders)}


def run_rec(rag, wiki, rag_q=None, wiki_q=None, judged=True):
    r = {"judgement": judged, "systems": {"rag": graded(*rag), "wiki": graded(*wiki)}}
    if rag_q:
        r["systems"]["rag_q"] = graded(*rag_q)
        r["pairs"] = {"rag_q": {"wiki": graded(*wiki_q)}}
    return r


ALL = {"K1": "full", "K2": "full", "K3": "full", "K4": "full"}
MAIN_ONLY = {"K1": "full", "K2": "full", "K3": "partial", "K4": "missing"}
HALF_SEC = {"K1": "full", "K2": "missing", "K3": "missing", "K4": "partial"}


def data(topics, systems=("rag", "wiki")):
    return {"config": {"systems_compared": list(systems), "seed": 7}, "topics": topics}


class Resolve(unittest.TestCase):
    def test_document_from_the_backing_reference(self):
        r = lambda ref: multisource.resolve(ref, DOCS)
        self.assertEqual(r("5.5.1 (Doc 1 Part A)"), "Doc 1 Part A")  # the name given
        self.assertEqual(r("5.5.17(a) (Doc 1 Part A (Standard))"), "Doc 1 Part A")  # a longer form of it, sub-paragraph
        self.assertEqual(r("B5.5.1 (Doc 1)"), "Doc 1 Part A")  # a shorter name: the document holding the paragraph
        self.assertEqual(r("IE2 (Doc 1)"), "Doc 1 Part B")
        self.assertEqual(r("Appendix A: term (Doc 1)"), "Doc 1 Part A")
        self.assertEqual(r("9 (Doc 12 Part A)"), "Doc 12 Part A")  # "Doc 1" is not a prefix of "Doc 12"
        self.assertEqual(r("35F"), "Doc 2 Part A")  # no name: the one document holding the paragraph

    def test_left_out(self):
        r = lambda ref: multisource.resolve(ref, DOCS)
        self.assertIsNone(r(None))
        self.assertIsNone(r(""))
        self.assertIsNone(r("1.1 (Doc 9)"))  # no such document
        self.assertIsNone(r("7.7.7 (Doc 1)"))  # two documents fit and neither holds the paragraph

    def test_main_document_tie_goes_to_the_standard(self):
        doc_of, left = multisource.topic_documents([kp("A", "IE1 (Doc 1 Part B)"), kp("B", "5.5.1 (Doc 1 Part A)")], DOCS)
        self.assertEqual(left, 0)
        tiers = {d["name"]: d["tier"] for d in DOCS}
        self.assertEqual(multisource.main_document(doc_of, tiers), "Doc 1 Part A")


class Measure(unittest.TestCase):
    def test_figures_from_the_stored_grades(self):
        topics = {"1": {"key_points": POINTS, "runs": {
                    "1": run_rec([MAIN_ONLY, MAIN_ONLY], [ALL, HALF_SEC]),
                    "2": run_rec([ALL, ALL], [ALL, ALL], judged=False)}},  # not graded: left out
                  "2": {"key_points": [kp("K1", "5.5.1 (Doc 1 Part A)"), kp("K2", "5.5.17 (Doc 1 Part A)")],  # one document
                        "runs": {"1": run_rec([ALL], [ALL])}}}
        m = multisource.measure(data(topics), DOCS)
        self.assertEqual((m["topics"], m["multi_source"], m["points"], m["left_out"]), (2, 1, 7, 1))
        by = m["pairs"]["rag"]["by_system"]
        # secondary (K4 only): RAG missing in both orders; wiki full, then partial -> 75
        self.assertEqual(by["rag"]["ms_secondary"], {"mean": 0.0, "n": 1})
        self.assertEqual(by["wiki"]["ms_secondary"], {"mean": 75.0, "n": 1})
        # all documents: RAG misses Doc 2 in both orders; wiki covers both in order 1, in order 2 Doc 1 Part A is 1/3
        self.assertEqual(by["rag"]["ms_all_docs"]["mean"], 0.0)
        self.assertEqual(by["wiki"]["ms_all_docs"]["mean"], 50.0)
        g = m["pairs"]["rag"]["gaps"]["ms_secondary"]
        self.assertEqual((g["diff"], g["n_topics"], g["ci"]), (75.0, 1, None))
        self.assertEqual(g["verdict"], "too few topics for an interval")

    def test_each_pair_uses_its_own_grading(self):
        rec = lambda: {"key_points": POINTS, "runs": {"1": run_rec([MAIN_ONLY], [MAIN_ONLY], rag_q=[MAIN_ONLY], wiki_q=[ALL])}}
        m = multisource.measure(data({"1": rec(), "2": rec(), "3": rec()}, ("rag", "wiki", "rag_q")), DOCS)
        self.assertEqual(m["pairs"]["rag"]["by_system"]["wiki"]["ms_secondary"]["mean"], 0.0)
        self.assertEqual(m["pairs"]["rag_q"]["by_system"]["wiki"]["ms_secondary"]["mean"], 100.0)
        g = m["pairs"]["rag_q"]["gaps"]["ms_all_docs"]
        self.assertEqual((g["diff"], g["ci"], g["leader"], g["verdict"]), (100.0, [100.0, 100.0], "wiki", "Wiki better"))

    def test_no_multi_source_topics(self):
        m = multisource.measure(data({"1": {"key_points": [kp("K1", "5.5.1 (Doc 1 Part A)")], "runs": {"1": run_rec([ALL], [ALL])}}}), DOCS)
        self.assertEqual(m["multi_source"], 0)
        self.assertEqual(m["pairs"]["rag"]["gaps"], {})


class Scorecard(unittest.TestCase):
    def test_rows_and_csv(self):
        rec = lambda g: {"key_points": POINTS, "runs": {"1": run_rec([MAIN_ONLY], [g])}}
        d = data({"1": rec(ALL), "2": rec(HALF_SEC), "3": rec(ALL)})
        d["multi_source"] = multisource.measure(d, DOCS)
        rows = {x["key"]: x for x in scorecard.build(d)["pairs"][0]["rows"]}
        sec = rows["ms_secondary"]
        self.assertEqual((sec["rag"]["text"], sec["wiki"]["text"]), ("0.0%", "83.33%"))
        self.assertEqual(sec["rag"]["reason"], "3 multi-source topic(s)")
        self.assertTrue(sec["gap"]["text"].startswith("+83.3"))
        self.assertIn("3 of 3 topics multi-source", sec["detail"])
        self.assertIn("3 of 15 key points left out", sec["detail"])
        self.assertEqual(rows["coverage"]["detail"], "")
        out = list(csv.reader(io.StringIO(run_export.scorecard_csv(d, {"rag": "RAG (per topic)"}).decode("utf-8").lstrip("﻿"))))
        self.assertEqual(out[0][-1], "about the test")
        line = next(x for x in out if x[1] == scorecard.LABEL["ms_all_docs"])
        self.assertIn("topics multi-source", line[-1])

    def test_not_worked_out(self):
        rows = {x["key"]: x for x in scorecard.build(data({}))["pairs"][0]["rows"]}
        self.assertEqual(rows["ms_secondary"]["wiki"]["text"], "not measured")
        self.assertIsNone(rows["ms_secondary"]["gap"])


if __name__ == "__main__":
    unittest.main()
