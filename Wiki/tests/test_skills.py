"""A chat's skills are added to the wiki's answer instruction only, and only when it has some; the same wording as RAG.
Run from Wiki/: python -m unittest tests.test_skills"""
import pathlib
import unittest

from app import prompts
from app.ops import query

RAG_PROMPTS = pathlib.Path(__file__).resolve().parents[2] / "Rag" / "app" / "prompts.py"


class Skills(unittest.TestCase):
    def test_no_skills_leaves_the_instruction_unchanged(self):
        wiki = {"schema_md": "# Schema\n"}
        self.assertEqual(query._plain_system(wiki, None), query._plain_system(wiki))
        self.assertEqual(query._plain_system(wiki, " "), query._plain_system(wiki))

    def test_skills_follow_the_instruction(self):
        wiki = {"schema_md": "# Schema\n"}
        out = query._plain_system(wiki, "Answer in three bullets.")
        self.assertTrue(out.startswith(query._plain_system(wiki)))
        self.assertTrue(out.endswith("<skills>\nAnswer in three bullets.\n</skills>"))

    def test_same_wording_as_rag(self):
        self.assertIn(f"SKILLS_INTRO = (\"{prompts.SKILLS_INTRO[:40]}", RAG_PROMPTS.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
