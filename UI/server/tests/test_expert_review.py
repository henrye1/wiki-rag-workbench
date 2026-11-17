"""Expert review files: the topics are shared out evenly within each group, shared topics are in every reviewer's file
and the same in each, the same seed gives the same files, the reviewer files are blind and show one judge reading as it
was graded, the KEY says which answer is which, and the results read back what the reviewers entered (a shared topic
counted once in a gap, the reviewers compared with each other on the shared topics). Run from UI/server: python -m unittest tests.test_expert_review"""
import io
import unittest

from openpyxl import load_workbook

from app import expert_review as er

LABEL = {"rag": "RAG (per topic)", "rag_q": "RAG (per question)", "wiki": "Wiki"}
TAG = {"wiki": "one", "rag_q": "two", "rag": "three"}  # a note names its answer A without naming a system
POINTS = [{"id": "K1", "kind": "standard", "point": "P1"}, {"id": "K2", "kind": "supporting", "point": "P2"}]


def _order(a: str, b: str, ga: dict, gb: dict, winner: str) -> dict:
    return {"blind_labels": {"A": a, "B": b}, "winner": winner, "point_notes": {"K1": f"A is {TAG[a]}", "K2": "B note"},
            "systems": {a: {"grades": ga}, b: {"grades": gb}}}


def _topic(n: int) -> dict:
    w, r = {"K1": "full", "K2": "partial"}, {"K1": "missing", "K2": "full"}
    run = {"systems": {"wiki": {"answer": f"wiki answer {n} [[source-x|5.5.3]]", "coverage": 75.0},
                       "rag_q": {"answer": f"rag answer {n}", "coverage": 50.0, "coverage_standard": 10.0},
                       "rag": {"answer": f"=rag topic answer {n}", "coverage": 25.0}},
           "pairs": {"rag_q": {"wiki": {"coverage": 70.0, "coverage_standard": 90.0}, "orders": {
               "1": _order("wiki", "rag_q", w, r, "wiki"), "2": _order("rag_q", "wiki", r, w, "tie")}}},
           "orders": {"1": _order("rag", "wiki", r, w, "wiki"), "2": _order("wiki", "rag", w, r, "wiki")}}
    return {"number": n, "code": f"2.{n}", "title": f"T{n}", "question": f"Q{n}", "reference": "memo text",
            "key_points": POINTS, "runs": {"1": run}}


RUN = {"config": {"systems_compared": ["rag", "wiki", "rag_q"]}, "topics": {str(n): _topic(n) for n in range(1, 27)}}


def _book(blob: bytes):
    return load_workbook(io.BytesIO(blob))


def _rows(ws) -> list[dict]:
    rows = list(ws.iter_rows(values_only=True))
    return [dict(zip(rows[0], r)) for r in rows[1:]]


class Split(unittest.TestCase):
    def test_even_within_groups(self):
        for k in range(1, 5):
            p = er.plan(RUN, "rag_q", 1, k, 7)
            tops = [r["topics"] for r in p["reviewers"]]
            self.assertEqual(sorted(n for t in tops for n in t), list(range(1, 27)))  # each topic once
            self.assertLessEqual(max(map(len, tops)) - min(map(len, tops)), 1)
            for g in range(2):
                counts = [r["by_group"][g] for r in p["reviewers"]]
                self.assertLessEqual(max(counts) - min(counts), 1)
        self.assertEqual(er.plan(RUN, "rag_q", 1, 2, 7)["groups"], [[1, 14], [15, 26]])

    def test_seed_decides(self):
        self.assertEqual(er.plan(RUN, "rag_q", 1, 3, 11), er.plan(RUN, "rag_q", 1, 3, 11))
        self.assertNotEqual(er.plan(RUN, "rag_q", 1, 3, 11)["reviewers"], er.plan(RUN, "rag_q", 1, 3, 12)["reviewers"])

    def test_refuses_what_the_run_lacks(self):
        with self.assertRaises(er.ReviewError):
            er.plan(RUN, "rag_q", 2, 2, 1)
        with self.assertRaises(er.ReviewError):
            er.plan(RUN, "rag_q", 1, 5, 1)


class Files(unittest.TestCase):
    def setUp(self):
        self.files, self.written = er.build(RUN, "r1", "rag_q", 1, 2, 5, LABEL)

    def test_names(self):
        self.assertEqual(sorted(self.files), ["Expert_Review_r1_KEY.xlsx", "Expert_Review_r1_Reviewer1.xlsx",
                                              "Expert_Review_r1_Reviewer2.xlsx"])

    def test_blind(self):
        text = self.written.replace("wiki answer", "").replace("rag answer", "")  # the fixture's answer texts
        for s in ("Wiki", "wiki", "RAG", "rag"):
            self.assertNotIn(s, text)
        wb = _book(self.files["Expert_Review_r1_Reviewer1.xlsx"])
        self.assertEqual(wb.sheetnames, ["Instructions", "Key points", "Answers"])

    def test_reading_shown_as_graded(self):
        """Each topic shows one judge reading whole: its A/B, grades, notes and preference agree with the KEY."""
        key = _book(self.files["Expert_Review_r1_KEY.xlsx"])
        topics = {r["Topic"]: r for r in _rows(key["Topics"])}
        seen_a = set()
        for i in (1, 2):
            wb = _book(self.files[f"Expert_Review_r1_Reviewer{i}.xlsx"])
            for r in _rows(wb["Answers"]):
                t = topics[r["Topic"]]
                self.assertEqual(t["Reviewers"], str(i))
                a_is_wiki = t["Answer A is"] == "Wiki"
                seen_a.add(a_is_wiki)
                self.assertTrue(r["Answer A"].startswith("wiki answer" if a_is_wiki else "rag answer"))
                self.assertEqual(r["Answer A"], f"wiki answer {r['Topic']} 5.5.3" if a_is_wiki else f"rag answer {r['Topic']}")
                self.assertEqual(r["Judge's preference"], "A" if a_is_wiki else "tie")  # reading 1 picked the wiki; 2 a tie
            for r in _rows(wb["Key points"]):
                a_is_wiki = topics[r["Topic"]]["Answer A is"] == "Wiki"
                if r["Key point"] == "K1":
                    self.assertEqual((r["Judge: A"], r["Judge: B"]), ("full", "missing") if a_is_wiki else ("missing", "full"))
                    self.assertEqual(r["Judge's note"], "A is one" if a_is_wiki else "A is two")
        self.assertEqual(seen_a, {True, False})  # A/B differs between topics

    def test_formatting(self):
        wb = _book(self.files["Expert_Review_r1_Reviewer1.xlsx"])
        ws = wb["Key points"]
        self.assertEqual(ws.freeze_panes, "A2")
        self.assertTrue(ws.auto_filter.ref.startswith("A1:"))
        lists = {dv.formula1 for dv in ws.data_validations.dataValidation}
        self.assertEqual(lists, {'"full,partial,missing"', '"yes,partly,no"'})
        self.assertTrue(ws["F2"].alignment.wrap_text)
        self.assertEqual({dv.formula1 for dv in wb["Answers"].data_validations.dataValidation}, {'"A,B,tie"'})

    def test_text_kept_as_text_and_cut_to_fit(self):
        files, _ = er.build(RUN, "r1", "rag", 1, 1, 5, LABEL)
        ws = _book(files["Expert_Review_r1_Reviewer1.xlsx"])["Answers"]
        cells = [c.value for row in ws.iter_rows(min_row=2) for c in row[5:7]]
        self.assertTrue(any(str(v).startswith("=rag topic answer") for v in cells))  # not a formula
        self.assertEqual(len(er._text("x" * 40000)), er.CELL_MAX - 200 + len("\n… [cut here: 7,000 more characters; the full text is in the run's side-by-side review]"))
        self.assertLessEqual(len(er._text("x" * 40000)), er.CELL_MAX)


class Shared(unittest.TestCase):
    def test_two_from_each_group_and_the_rest_balanced(self):
        p = er.plan(RUN, "rag_q", 1, 2, 186393, 4)
        sh = p["shared"]
        self.assertEqual(len(sh), 4)
        self.assertEqual((sum(n <= 14 for n in sh), sum(n >= 15 for n in sh)), (2, 2))
        for r in p["reviewers"]:
            self.assertTrue(set(sh) <= set(r["topics"]))
            self.assertEqual(len(r["topics"]), 15)
            self.assertEqual(r["own_by_group"], [6, 5])  # 12 and 10 left in the two groups, dealt in turn
        own = [n for r in p["reviewers"] for n in r["own"]]
        self.assertEqual(sorted(own + sh), list(range(1, 27)))  # every topic covered, the rest once each
        self.assertEqual(len(own), len(set(own)))

    def test_shared_in_range(self):
        for k in range(0, 5):
            self.assertEqual(len(er.plan(RUN, "rag_q", 1, 3, 9, k)["shared"]), k)
        with self.assertRaises(er.ReviewError):
            er.plan(RUN, "rag_q", 1, 2, 9, 5)
        self.assertEqual(er.plan(RUN, "rag_q", 1, 2, 9, 0)["reviewers"], er.plan(RUN, "rag_q", 1, 2, 9)["reviewers"])

    def test_same_in_every_file_and_recorded(self):
        files, _ = er.build(RUN, "r1", "rag_q", 1, 2, 5, LABEL, 4)
        sh = er.plan(RUN, "rag_q", 1, 2, 5, 4)["shared"]
        one, two = (_book(files[f"Expert_Review_r1_Reviewer{i}.xlsx"]) for i in (1, 2))
        for sheet in ("Key points", "Answers"):
            a = [r for r in _rows(one[sheet]) if r["Topic"] in sh]
            b = [r for r in _rows(two[sheet]) if r["Topic"] in sh]
            self.assertEqual(a, b)
            self.assertEqual({r["Topic"] for r in a}, set(sh))
        key = _book(files["Expert_Review_r1_KEY.xlsx"])
        settings = {r[0]: r[1] for r in key["Settings"].iter_rows(values_only=True) if r[0]}
        self.assertEqual(settings["Shared topics"], ", ".join(map(str, sh)))
        kt = {r["Topic"]: r for r in _rows(key["Topics"])}
        self.assertEqual(len(kt), 26)
        self.assertEqual({n for n, r in kt.items() if r["Shared"] == "yes"}, set(sh))
        self.assertEqual({r["Reviewers"] for n, r in kt.items() if n in sh}, {"1, 2"})
        self.assertEqual(len(_rows(key["Key points"])), 52)  # each topic's key points once
        ins = {r[0]: r[1] for r in one["Instructions"].iter_rows(values_only=True) if r[0]}
        self.assertTrue(ins["Shared topics"].startswith(", ".join(map(str, sh)) + ": every reviewer"))
        self.assertNotIn("Wiki", ins["Shared topics"])


class Results(unittest.TestCase):
    def _returned(self, files: dict, pick, n=2) -> list[bytes]:
        out = []
        for i in range(1, n + 1):
            wb = _book(files[f"Expert_Review_r1_Reviewer{i}.xlsx"])
            for row in wb["Key points"].iter_rows(min_row=2):
                a, b = pick(i, row[6].value, row[7].value)
                row[9].value, row[10].value, row[11].value = a, b, "yes"
            for row in wb["Answers"].iter_rows(min_row=2):
                row[8].value = row[7].value
            buf = io.BytesIO()
            wb.save(buf)
            out.append(buf.getvalue())
        return out

    def _summary(self, res) -> dict:
        return {r[0]: r for r in res["Summary"].iter_rows(values_only=True) if r and r[0]}

    def test_agreeing_reviewers(self):
        files, _ = er.build(RUN, "r1", "rag_q", 1, 2, 5, LABEL, 4)
        res = _book(er.results(files["Expert_Review_r1_KEY.xlsx"], self._returned(files, lambda i, a, b: (a, b))))
        s = self._summary(res)
        first = [r[0] for r in res["Summary"].iter_rows(values_only=True) if r and r[0]][3]
        self.assertEqual(first, "Wiki − RAG gap in standard-only coverage")  # the first figure
        self.assertEqual(s["Standard-only coverage gap: reviewers"][1:3], (26, 100.0))  # wiki full, rag missing on K1
        self.assertEqual(s["Standard-only coverage gap: judge, the reading the reviewers saw"][2], 100.0)
        self.assertEqual(s["Standard-only coverage gap: judge, as the run scored it (both readings)"][2], 80.0)  # 90 - 10
        self.assertEqual(s["Coverage gap: reviewers"][1:3], (26, 25.0))  # 26 topics: shared ones once
        self.assertEqual(s["Coverage gap: judge, as the run scored it (both readings)"][2], 20.0)  # 70 - 50
        self.assertEqual(s["Coverage gap: reviewers − judge (the reading they saw)"][2], 0.0)
        self.assertEqual(s["Wiki"][1:5], (60, "100%", "0%", "0%"))  # 30 topic files, 2 points: shared ones per reviewer
        self.assertEqual(s["Key point grades: Wiki"][1:3], (8, "100%"))  # 4 shared topics x 2 points, one pair
        self.assertEqual(s["Preferred answer"][1:3], (4, "100%"))
        cmp = list(res["Reviewers compared"].iter_rows(values_only=True))
        self.assertIn(("Topic", "Key point", "Kind", "Reviewer 1: Wiki", "Reviewer 2: Wiki", "Same: Wiki",
                       "Reviewer 1: RAG (per question)", "Reviewer 2: RAG (per question)", "Same: RAG (per question)"), cmp)
        self.assertEqual(len(_rows(res["By key point"])), 60)
        self.assertEqual(len(_rows(res["By topic"])), 26)

    def test_shared_topic_averaged_once(self):
        """Reviewer 2 marks everything missing: a shared topic's reviewer coverage is the two reviewers' mean, counted once."""
        files, _ = er.build(RUN, "r1", "rag_q", 1, 2, 5, LABEL, 4)
        sh = er.plan(RUN, "rag_q", 1, 2, 5, 4)["shared"]
        res = _book(er.results(files["Expert_Review_r1_KEY.xlsx"],
                               self._returned(files, lambda i, a, b: (a, b) if i == 1 else ("missing", "missing"))))
        topics = {r["Topic"]: r for r in _rows(res["By topic"])}
        for n in sh:
            self.assertEqual(topics[n]["Coverage: reviewers, Wiki %"], 37.5)  # mean of 75 and 0
            self.assertEqual(topics[n]["Standard-only coverage: reviewers, Wiki %"], 50.0)
        s = self._summary(res)
        self.assertEqual(s["Key point grades: Wiki"][1:3], (8, "0%"))
        self.assertEqual(s["Coverage gap: reviewers"][1], 26)

    def test_harsher_on_one_system(self):
        """Reviewers who mark every answer 'missing' grade the wiki lower than the judge more often than RAG."""
        files, _ = er.build(RUN, "r1", "rag_q", 1, 2, 5, LABEL)
        res = _book(er.results(files["Expert_Review_r1_KEY.xlsx"], self._returned(files, lambda i, a, b: ("missing", "missing"))))
        s = self._summary(res)
        self.assertEqual(s["Wiki"][4], "100%")  # the judge gave the wiki full / partial on both points
        self.assertEqual(s["RAG (per question)"][4], "50%")
        self.assertEqual(s["Coverage gap: reviewers"][2], 0.0)

    def test_wrong_files_refused(self):
        files, _ = er.build(RUN, "r1", "rag_q", 1, 2, 5, LABEL)
        other, _ = er.build(RUN, "r2", "rag_q", 1, 2, 5, LABEL)
        with self.assertRaises(er.ReviewError):
            er.results(files["Expert_Review_r1_KEY.xlsx"], [other["Expert_Review_r2_Reviewer1.xlsx"]])
        with self.assertRaises(er.ReviewError):
            er.results(files["Expert_Review_r1_Reviewer1.xlsx"], [files["Expert_Review_r1_Reviewer1.xlsx"]])
        with self.assertRaises(er.ReviewError):
            er.results(files["Expert_Review_r1_KEY.xlsx"], [files["Expert_Review_r1_Reviewer1.xlsx"]] * 2)
        moved, _ = er.build(RUN, "r1", "rag_q", 1, 2, 6, LABEL)  # another seed: topics given to other reviewers
        with self.assertRaises(er.ReviewError):
            er.results(files["Expert_Review_r1_KEY.xlsx"], [moved["Expert_Review_r1_Reviewer1.xlsx"]])


if __name__ == "__main__":
    unittest.main()
