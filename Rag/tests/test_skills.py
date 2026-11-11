"""A chat's skills are added to the answer instruction only, and only when it has some.
Run from Rag/: python -m unittest tests.test_skills"""
import unittest

from app import prompts
from app.routers.query import QueryIn, _system


class Skills(unittest.TestCase):
    def test_no_skills_leaves_the_instruction_unchanged(self):
        for none in (None, "", "  \n "):
            self.assertEqual(prompts.with_skills(prompts.QUERY_SYSTEM, none), prompts.QUERY_SYSTEM)
        self.assertEqual(_system(QueryIn(question="What is ECL?")), prompts.QUERY_SYSTEM)

    def test_skills_follow_the_instruction(self):
        out = _system(QueryIn(question="What is ECL?", instructions="## Short\n\nThree bullets."))
        self.assertTrue(out.startswith(prompts.QUERY_SYSTEM))
        self.assertIn("<skills>\n## Short\n\nThree bullets.\n</skills>", out)


if __name__ == "__main__":
    unittest.main()
