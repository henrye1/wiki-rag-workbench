"""Skill runs: a skill's questions are cleaned and capped; the summary prompt carries each question with one side's answer
(or why there is none); the summary instruction falls back to the default. Run from UI/server:
python -m unittest tests.test_skill_runs"""
import unittest

from fastapi import HTTPException

from app import ask, skills


def skill_in(**kw):
    return skills.SkillIn(**({"name": "Eval", "instructions": "Be strict."} | kw))


class Clean(unittest.TestCase):
    def test_blank_questions_dropped_and_trimmed(self):
        out = skills._clean(skill_in(questions=["  Q1? ", "", "   ", "Q2?"], summary="  Score it. "))
        self.assertEqual(out[3], ["Q1?", "Q2?"])
        self.assertEqual(out[4], "Score it.")

    def test_no_questions_is_fine(self):
        self.assertEqual(skills._clean(skill_in())[3:], ([], ""))

    def test_too_many_questions(self):
        with self.assertRaises(HTTPException) as e:
            skills._clean(skill_in(questions=[f"Q{i}" for i in range(skills.MAX_QUESTIONS + 1)]))
        self.assertEqual(e.exception.status_code, 422)

    def test_question_too_long(self):
        with self.assertRaises(HTTPException):
            skills._clean(skill_in(questions=["x" * (skills.MAX_QUESTION + 1)]))


class SummaryPrompt(unittest.TestCase):
    ROWS = [
        {"searched": "What is A?", "rag": {"answer": "A is 1."}, "wiki": {"answer": "A is one [[p|5.1]]."}},
        {"searched": "What is B?", "rag": {"answer": "", "error": "Stopped"}, "wiki": None},
    ]

    def test_one_side_in_order(self):
        p = ask.summary_prompt(self.ROWS, "wiki")
        self.assertLess(p.index("What is A?"), p.index("What is B?"))
        self.assertIn("A is one [[p|5.1]].", p)
        self.assertNotIn("A is 1.", p)  # the other side's answers are never used
        self.assertIn("(No answer: nothing was returned)", p)

    def test_error_is_given_as_the_reason(self):
        self.assertIn("(No answer: Stopped)", ask.summary_prompt(self.ROWS, "rag"))

    def test_system_uses_skill_text_or_default(self):
        s = ask.summary_system({"instructions": "Be strict.", "summary": ""})
        self.assertIn("Be strict.", s)
        self.assertIn(ask.DEFAULT_SUMMARY, s)
        self.assertIn("Score 1-5.", ask.summary_system({"instructions": "x", "summary": "Score 1-5."}))


if __name__ == "__main__":
    unittest.main()
