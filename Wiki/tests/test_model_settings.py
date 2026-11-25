"""One model per job: each its own setting, defaulting to the new models, falling back to gemini-2.5-flash when given but
left empty; every call uses the model of the job it is made for. Run from Wiki/: python -m unittest tests.test_model_settings"""
import asyncio
import os
import unittest
from unittest import mock

from app import config, llm

BASE = {"API_KEY": "k", "GEMINI_API_KEY": "g"}
JOBS = {"PARSER_MODEL": "gemini-4-hydrogen", "WRITER_MODEL": "gemini-4-carbon", "ANSWER_MODEL": "gemini-4-carbon",
        "LINT_MODEL": "gemini-4-carbon", "SUGGEST_MODEL": "gemini-4-carbon"}


def settings(**env):
    with mock.patch.dict(os.environ, {**BASE, **env}, clear=True):
        return config.Settings(_env_file=None)


class Settings(unittest.TestCase):
    def test_defaults_are_the_new_models(self):
        s = settings()
        self.assertEqual({f"{j.upper()}_MODEL": s.model_for(j) for j in config.MODEL_JOBS}, JOBS)

    def test_empty_falls_back(self):
        s = settings(WRITER_MODEL="", LINT_MODEL="   ")
        self.assertEqual((s.writer_model, s.lint_model, s.answer_model), ("gemini-2.5-flash", "gemini-2.5-flash", "gemini-4-carbon"))

    def test_each_job_its_own(self):
        self.assertEqual(settings(ANSWER_MODEL="m-answer").model_for("answer"), "m-answer")
        self.assertEqual(settings(ANSWER_MODEL="m-answer").model_for("writer"), "gemini-4-carbon")


class Calls(unittest.TestCase):
    def setUp(self):
        self.s = settings(WRITER_MODEL="m-writer", ANSWER_MODEL="m-answer", LINT_MODEL="m-lint")
        p = mock.patch.object(llm, "get_settings", return_value=self.s)
        p.start()
        self.addCleanup(p.stop)

    def run_call(self, job=None, named=None):
        sent = []

        async def gen(model, contents, config):
            sent.append(model)
            return mock.Mock(text="ok", candidates=[mock.Mock(finish_reason="STOP")], usage_metadata=None)

        fake = mock.Mock()
        fake.aio.models.generate_content = gen

        async def go():
            if job:
                llm.use(job)
            return await llm.generate("s", "p", job=named)

        with mock.patch.object(llm, "client", return_value=fake):
            asyncio.run(go())
        return sent[0]

    def test_the_job_in_use(self):
        self.assertEqual(self.run_call("writer"), "m-writer")
        self.assertEqual(self.run_call("lint"), "m-lint")

    def test_named_job_wins(self):
        self.assertEqual(self.run_call("writer", named="answer"), "m-answer")

    def test_no_job_falls_back(self):
        self.assertEqual(self.run_call(), "gemini-2.5-flash")

    def test_tasks_inherit_the_job(self):
        async def go():
            llm.use("lint")
            return await asyncio.gather(*(asyncio.create_task(asyncio.sleep(0, llm.model())) for _ in range(3)))
        self.assertEqual(asyncio.run(go()), ["m-lint"] * 3)

    def test_unknown_job(self):
        with self.assertRaises(ValueError):
            llm.use("nonsense")

    def test_models_listed(self):
        self.assertEqual(llm.models()["writer"], {"does": config.MODEL_JOBS["writer"], "model": "m-writer", "setting": "WRITER_MODEL"})


class Usage(unittest.TestCase):
    def test_per_step_and_total(self):
        async def go():
            calls = llm.track_usage()
            llm.set_stage("notes")
            llm._record({"step": "json", "model": "m", "input_tokens": 10, "output_tokens": 2, "thinking_tokens": 5})
            llm._record({"step": "embed", "model": "e", "texts": 3, "chars": 30})
            llm.set_stage("write")
            async def child():  # tasks started in a step record under it
                llm._record({"step": "json", "model": "m2", "input_tokens": 1, "output_tokens": 1, "thinking_tokens": None})
            await asyncio.gather(child(), child())
            return llm.usage_summary(calls)
        u = asyncio.run(go())
        self.assertEqual((u["notes"]["calls"], u["notes"]["input_tokens"], u["notes"]["thinking_tokens"], u["notes"]["embed_texts"]), (1, 10, 5, 3))
        self.assertEqual((u["write"]["calls"], u["write"]["input_tokens"], u["write"]["models"]), (2, 2, ["m2"]))
        self.assertEqual((u["total"]["calls"], u["total"]["input_tokens"], u["total"]["output_tokens"], u["total"]["models"]), (3, 12, 4, ["m", "m2"]))


class EntryPoints(unittest.TestCase):
    def test_each_entry_names_its_job(self):
        """Every request and job that reaches a model sets the job its calls are for."""
        import inspect
        from app.ops import ingest, lint, recheck
        from app.routers import ops, sources
        for fn, job in ((ingest.run, "writer"), (recheck.run, "writer"), (lint.run, "lint"), (sources.describe_file, "suggest"),
                        (ops.synthesis_draft, "writer"), (ops.synthesis_check, "writer"), (ops.read_text, "answer"),
                        (ops.ask, "answer"), (ops.ask_stream, "answer"), (ops.check_statement, "answer")):
            with self.subTest(fn.__name__):
                self.assertIn(f'llm.use("{job}")', inspect.getsource(fn))


if __name__ == "__main__":
    unittest.main()
