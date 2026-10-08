import asyncio
import json
import logging
from collections.abc import AsyncIterator
from functools import lru_cache

import numpy as np
from google import genai
from google.genai import errors, types

from .config import get_settings

log = logging.getLogger(__name__)
RETRYABLE = {429, 500, 502, 503, 504}


@lru_cache
def client() -> genai.Client:
    return genai.Client(api_key=get_settings().gemini_api_key)


async def _retry(fn, attempts: int = 5):
    for i in range(attempts):
        try:
            return await fn()
        except errors.APIError as e:
            if e.code not in RETRYABLE or i == attempts - 1:
                raise
            delay = 2 ** i * 2
            log.warning("Gemini %s, retry in %ss", e.code, delay)
            await asyncio.sleep(delay)


def _normalize(v: list[float]) -> list[float]:
    a = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(a)
    return (a / n).tolist() if n else a.tolist()


async def embed(texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
    s = get_settings()
    out: list[list[float]] = []
    for i in range(0, len(texts), s.embed_batch):
        batch = texts[i : i + s.embed_batch]
        cfg = types.EmbedContentConfig(task_type=task, output_dimensionality=s.embed_dim)
        resp = await _retry(lambda: client().aio.models.embed_content(model=s.gemini_embed_model, contents=batch, config=cfg))
        out.extend(_normalize(e.values) for e in resp.embeddings)
    return out


async def embed_query(text: str) -> list[float]:
    return (await embed([text], task="RETRIEVAL_QUERY"))[0]


def _cfg(system: str, **kw) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(system_instruction=system, temperature=get_settings().temperature, **kw)


async def generate(system: str, prompt: str, schema: dict | None = None) -> str:
    kw = {"response_mime_type": "application/json", "response_json_schema": schema} if schema else {}
    resp = await _retry(
        lambda: client().aio.models.generate_content(model=get_settings().gemini_chat_model, contents=prompt, config=_cfg(system, **kw))
    )
    if not resp.text:
        cand = resp.candidates[0] if resp.candidates else None
        reason = (cand.finish_reason if cand else None) or getattr(resp.prompt_feedback, "block_reason", None)
        raise EmptyResponse(f"Gemini returned no text (finish_reason={reason})")
    return resp.text


class EmptyResponse(Exception):
    pass


async def stream(system: str, prompt: str) -> AsyncIterator[str]:
    it = await _retry(
        lambda: client().aio.models.generate_content_stream(model=get_settings().gemini_chat_model, contents=prompt, config=_cfg(system))
    )
    async for chunk in it:
        if chunk.text:
            yield chunk.text


async def generate_json(system: str, prompt: str, schema: dict, attempts: int = 2) -> dict:
    """JSON-mode generation; retries once on empty/invalid output (e.g. truncation, transient blocks)."""
    for i in range(attempts):
        try:
            return json.loads(await generate(system, prompt, schema=schema))
        except (EmptyResponse, json.JSONDecodeError) as e:
            if i == attempts - 1:
                raise
            log.warning("generate_json retry: %s", e)


async def gather_limited(coros, limit: int | None = None):
    """asyncio.gather with a concurrency cap (default: LLM_CONCURRENCY)."""
    sem = asyncio.Semaphore(limit or get_settings().llm_concurrency)

    async def run(c):
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros))
