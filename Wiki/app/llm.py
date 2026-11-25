import asyncio
import contextvars
import json
import logging
import re
from collections.abc import AsyncIterator
from functools import lru_cache

import httpx
import numpy as np
from google import genai
from google.genai import errors, types

from .config import FALLBACK_MODEL, MODEL_JOBS, get_settings

log = logging.getLogger(__name__)
RETRYABLE = {429, 500, 502, 503, 504}


@lru_cache
def client() -> genai.Client:
    s = get_settings()
    return genai.Client(api_key=s.gemini_api_key, http_options=types.HttpOptions(timeout=s.llm_timeout_s * 1000))


async def _retry(fn, attempts: int = 5):
    for i in range(attempts):
        try:
            return await fn()
        except (errors.APIError, httpx.TransportError) as e:
            # a busy or failing server, a call over the time limit, or a connection that dropped: tried again
            code = e.code if isinstance(e, errors.APIError) else type(e).__name__
            if (isinstance(e, errors.APIError) and e.code not in RETRYABLE) or i == attempts - 1:
                raise
            delay = 2 ** i * 2
            log.warning("Gemini %s, retry in %ss", code, delay)
            await asyncio.sleep(delay)


# Which job a model call is for (MODEL_JOBS): set where a job or request starts (llm.use), read by every call made for
# it, also in tasks it starts; a call may name its job itself.
_job: contextvars.ContextVar[str | None] = contextvars.ContextVar("llm_job", default=None)


def use(job: str) -> str:
    """Make the calls that follow (and the tasks they start) use this job's model; returns the model."""
    if job not in MODEL_JOBS:
        raise ValueError(f"Unknown model job: {job}")
    _job.set(job)
    return get_settings().model_for(job)


def model(job: str | None = None) -> str:
    """The model for this job (the one in use where none is named)."""
    job = job or _job.get()
    if job is None:
        log.warning("A model call with no job set: using %s", FALLBACK_MODEL)
        return FALLBACK_MODEL
    return get_settings().model_for(job)


def models() -> dict[str, dict[str, str]]:
    """Each job, what it does and its model, as set now."""
    s = get_settings()
    return {j: {"does": what, "model": s.model_for(j), "setting": f"{j.upper()}_MODEL"} for j, what in MODEL_JOBS.items()}


# Token use of the calls made while answering one request (the benchmark records it to work out cost per query).
# A request starts a list with track_usage(); calls made for it (also in tasks it starts) add to that list.
_usage: contextvars.ContextVar[list | None] = contextvars.ContextVar("llm_usage", default=None)


def track_usage(cap_usd: float = 0) -> list:
    """Start recording the calls made from here (and in tasks started from here); cap_usd: the most they may cost (0:
    no limit). Once they have cost that much, every further call stops with SpendCapReached."""
    calls: list = []
    _usage.set(calls)
    _cap.set(cap_usd or 0)
    return calls


# The spending cap of the calls being recorded (a job's: JOB_SPEND_CAP_USD); 0: none
_cap: contextvars.ContextVar[float] = contextvars.ContextVar("llm_cap", default=0)


class SpendCapReached(BaseException):
    """The job's model calls have cost its spending cap. A BaseException, as a cancellation is, so that the steps
    which carry on past a failed call (a page part, a fix round) do not catch it: it stops the whole job."""


def cost_usd(calls: list | None = None) -> float:
    """What the calls recorded cost, at MODEL_PRICES (thinking billed as output). A model with no price: ValueError."""
    prices = get_settings().prices()
    total = 0.0
    for c in (_usage.get() if calls is None else calls) or []:
        if c.get("step") == "embed":
            continue
        if c.get("model") not in prices:
            raise ValueError(f"No price set for {c.get('model')} in MODEL_PRICES: the spending cap cannot be applied")
        inp, outp = prices[c["model"]]
        total += ((c.get("input_tokens") or 0) * inp
                  + ((c.get("output_tokens") or 0) + (c.get("thinking_tokens") or 0)) * outp) / 1e6
    return total


def _within_cap(used: str | None = None) -> None:
    """Stop (SpendCapReached) where the calls recorded have cost the cap; before a call, refuse a model with no price."""
    cap = _cap.get()
    if not cap or _usage.get() is None:
        return
    if used and used not in get_settings().prices():
        raise SpendCapReached(f"No price set for {used} in MODEL_PRICES: the spending cap cannot be applied")
    if (spent := cost_usd()) >= cap:
        raise SpendCapReached(f"Spending cap reached: ${spent:.2f} of ${cap:.2f}")


# The step of a job the calls are made in (an upload's notes, route, plan, write, ...), recorded with each call
_stage: contextvars.ContextVar[str | None] = contextvars.ContextVar("llm_stage", default=None)


def set_stage(stage: str) -> None:
    _stage.set(stage)


def usage_summary(calls: list | None = None) -> dict:
    """Token use of the calls recorded (those of the current request or job where none are given), per step and in
    total: calls, input, output and thinking tokens, and the models used; embedding calls by texts and characters."""
    calls = _usage.get() if calls is None else calls
    out: dict[str, dict] = {}
    for c in calls or []:
        for key in (c.get("stage") or "other", "total"):
            e = out.setdefault(key, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "models": [],
                                     "embed_calls": 0, "embed_texts": 0, "embed_chars": 0})
            if c.get("step") == "embed":
                e["embed_calls"] += 1
                e["embed_texts"] += c.get("texts") or 0
                e["embed_chars"] += c.get("chars") or 0
                continue
            e["calls"] += 1
            for k in ("input_tokens", "output_tokens", "thinking_tokens"):
                e[k] += c.get(k) or 0
            if c.get("model") and c["model"] not in e["models"]:
                e["models"].append(c["model"])
    return out


def _record(entry: dict) -> None:
    calls = _usage.get()
    if calls is not None:
        calls.append({**entry, "stage": _stage.get()})


def _record_generation(step: str, resp, used: str) -> None:
    u = getattr(resp, "usage_metadata", None)
    _record({"step": step, "model": used,
             "input_tokens": getattr(u, "prompt_token_count", None), "output_tokens": getattr(u, "candidates_token_count", None),
             "thinking_tokens": getattr(u, "thoughts_token_count", None)})


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
        _record({"step": "embed", "model": s.gemini_embed_model, "texts": len(batch), "chars": sum(len(t) for t in batch),
                 "input_tokens": None, "output_tokens": None})
    return out


async def embed_query(text: str) -> list[float]:
    return (await embed([text], task="RETRIEVAL_QUERY"))[0]


def _cfg(system: str, job: str | None = None, **kw) -> types.GenerateContentConfig:
    """A call's settings; the parser's thinking is capped (PARSER_THINKING_BUDGET)."""
    s = get_settings()
    if (job or _job.get()) == "parser" and s.parser_thinking_budget > 0:
        kw["thinking_config"] = types.ThinkingConfig(thinking_budget=s.parser_thinking_budget)
    return types.GenerateContentConfig(system_instruction=system, temperature=s.temperature, **kw)


async def generate(system: str, prompt, schema: dict | None = None, job: str | None = None) -> str:
    """prompt: text, or a list of parts (text and page images)."""
    kw = {"response_mime_type": "application/json", "response_json_schema": schema} if schema else {}
    used = model(job)
    _within_cap(used)
    resp = await _retry(
        lambda: client().aio.models.generate_content(model=used, contents=prompt, config=_cfg(system, job, **kw))
    )
    _record_generation("json" if schema else "answer", resp, used)
    _within_cap()
    cand = resp.candidates[0] if resp.candidates else None
    if not resp.text:
        reason = (cand.finish_reason if cand else None) or getattr(resp.prompt_feedback, "block_reason", None)
        raise EmptyResponse(f"Gemini returned no text (finish_reason={reason})")
    reason = getattr(cand.finish_reason, "name", cand.finish_reason) if cand else None
    if schema and reason and reason != "STOP":
        # JSON cut off mid-string (e.g. RECITATION or MAX_TOKENS): fail with the reason, not a JSONDecodeError
        raise EmptyResponse(f"Gemini stopped early (finish_reason={reason}, {len(resp.text)} chars)")
    return resp.text


class EmptyResponse(Exception):
    pass


async def stream(system: str, prompt: str, job: str | None = None) -> AsyncIterator[str]:
    used = model(job)
    _within_cap(used)
    it = await _retry(
        lambda: client().aio.models.generate_content_stream(model=used, contents=prompt, config=_cfg(system, job))
    )
    async for chunk in it:
        if chunk.text:
            yield chunk.text


# A JSON reply's text: every backslash in it (a formula's commands) is written twice, or JSON reads "\neq" as a line
# break and "eq". Told to the model with every JSON call; what it still writes once is put back when the reply is read.
JSON_BACKSLASHES = ("Your reply is JSON: write every backslash in its text twice (\\\\), for example in a formula, "
                    "so that it is read as a backslash and not as a line break, tab or other control character.")
_ESCAPED = {"\n": "n", "\t": "t", "\r": "r", "\f": "f", "\b": "b"}  # the control characters a JSON escape makes
# a formula in markdown: $$...$$, or $...$ opened by a non-space and closed by a non-space not followed by a digit
# (opened, too, by a control character a command's backslash was read as)
MATH = re.compile(r"\$\$.+?\$\$|\$(?=[^\s$]|[\n\t\r][A-Za-z])[^$]*?(?<=[^\s$])\$(?!\d)", re.S)


def restore_backslashes(text: str) -> str:
    """A reply's text with each backslash command the JSON escapes turned into a control character put back: a form
    feed or backspace followed by letters anywhere ("\frac", "\beta"; neither is ever text), and a line break, tab or
    carriage return followed by letters inside a formula ("\neq", "\theta", "\rho")."""
    text = re.sub(r"[\f\b](?=[A-Za-z])", lambda m: "\\" + _ESCAPED[m.group(0)], text)
    return MATH.sub(lambda m: re.sub(r"[\n\t\r](?=[A-Za-z])", lambda x: "\\" + _ESCAPED[x.group(0)], m.group(0)), text)


def _restored(value):
    if isinstance(value, str):
        return restore_backslashes(value)
    if isinstance(value, list):
        return [_restored(v) for v in value]
    if isinstance(value, dict):
        return {k: _restored(v) for k, v in value.items()}
    return value


async def generate_json(system: str, prompt, schema: dict, attempts: int = 3, job: str | None = None) -> dict:
    """JSON-mode generation; retries on empty/invalid output (e.g. truncation, transient blocks). Backslashes in the
    reply's text are kept as written (JSON_BACKSLASHES)."""
    for i in range(attempts):
        try:
            return _restored(json.loads(await generate(f"{system}\n\n{JSON_BACKSLASHES}", prompt, schema=schema, job=job)))
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
