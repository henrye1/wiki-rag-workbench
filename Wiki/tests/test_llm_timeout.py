"""A model call has a time limit, and a call that stalls (or whose connection drops) is tried again rather than waiting
forever. Run from Wiki/: python -m unittest tests.test_llm_timeout"""
import asyncio
import unittest
from unittest import mock

import httpx

from app import llm
from app.config import get_settings


class TimeLimit(unittest.TestCase):
    def test_client_has_the_limit(self):
        llm.client.cache_clear()
        with mock.patch.object(llm.genai, "Client") as made:
            llm.client()
        self.assertEqual(made.call_args.kwargs["http_options"].timeout, get_settings().llm_timeout_s * 1000)
        llm.client.cache_clear()

    def test_stalled_call_is_tried_again(self):
        calls = []

        async def call():
            calls.append(1)
            if len(calls) < 3:
                raise httpx.ReadTimeout("stalled")
            return "ok"

        with mock.patch.object(llm.asyncio, "sleep", mock.AsyncMock()):
            self.assertEqual(asyncio.run(llm._retry(call)), "ok")
        self.assertEqual(len(calls), 3)

    def test_gives_up_after_the_last_attempt(self):
        async def call():
            raise httpx.ConnectError("dropped")

        with mock.patch.object(llm.asyncio, "sleep", mock.AsyncMock()):
            with self.assertRaises(httpx.ConnectError):
                asyncio.run(llm._retry(call, attempts=2))


if __name__ == "__main__":
    unittest.main()
