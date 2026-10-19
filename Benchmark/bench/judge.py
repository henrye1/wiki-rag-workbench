"""Claude as judge: extract key points from the human reference, then grade two anonymised answers against them.

Gradings can go through the Message Batches API (half price): grade_batch() submits them together and returns each
result or the reason it failed, so the caller grades those normally (with the refusal fallback batches do not allow)."""
import asyncio
import json
import os
import tempfile
import time

from anthropic import AsyncAnthropic

from .config import get_settings

_client: AsyncAnthropic | None = None


def client() -> AsyncAnthropic:
    global _client
    if _client is None:
        key = get_settings().anthropic_api_key
        # SDK retries 408/409/429/5xx + connection errors
        _client = AsyncAnthropic(api_key=key, max_retries=5) if key else AsyncAnthropic(max_retries=5)
    return _client


class JudgeRefused(Exception):
    pass


async def _cli_call(system: str, user: str, schema: dict) -> dict:
    """The same judge call through Claude Code on the subscription: the judge's own system prompt replaces Claude Code's,
    with no tools, plugins, MCP servers, settings or project files; the reply must match the same JSON schema."""
    s = get_settings()
    if not s.claude_code_oauth_token:
        raise RuntimeError("JUDGE_BACKEND=claude-code needs CLAUDE_CODE_OAUTH_TOKEN in Benchmark/.env (from `claude setup-token`)")
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}
    env["CLAUDE_CODE_OAUTH_TOKEN"] = s.claude_code_oauth_token
    args = [s.claude_bin, "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
            "--model", s.judge_model, "--effort", s.judge_effort, "--system-prompt", system,
            "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence"]
    with tempfile.TemporaryDirectory() as empty:  # no project files (CLAUDE.md etc.) to pick up
        proc = await asyncio.create_subprocess_exec(*args, cwd=empty, env=env, stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(user.encode()), timeout=s.judge_timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Claude Code judge timed out after {s.judge_timeout_s} s")
    try:
        res = json.loads(out.decode() or "{}")
    except json.JSONDecodeError:
        raise RuntimeError(f"Claude Code judge: unreadable reply (exit {proc.returncode}): {err.decode()[-300:]}")
    if proc.returncode or res.get("is_error"):
        raise RuntimeError(f"Claude Code judge failed (exit {proc.returncode}): {str(res.get('result') or err.decode())[-300:]}")
    data = res.get("structured_output")
    if data is None:
        data = json.loads(res.get("result") or "")
    # Claude Code may make its own small side calls on another model; count only the judge model's tokens
    mu = res.get("modelUsage") or {}
    u = mu.get(s.judge_model) or next(iter(mu.values()), {})
    return {"data": data, "model": s.judge_model if s.judge_model in mu else ", ".join(mu) or s.judge_model, "backend": "claude-code",
            "usage": {"input_tokens": (u.get("inputTokens") or 0) + (u.get("cacheReadInputTokens") or 0)
                      + (u.get("cacheCreationInputTokens") or 0), "output_tokens": u.get("outputTokens") or 0}}


def _params(system: str, user: str, schema: dict) -> dict:
    s = get_settings()
    return {"model": s.judge_model, "max_tokens": 16000, "system": system, "messages": [{"role": "user", "content": user}],
            "output_config": {"effort": s.judge_effort, "format": {"type": "json_schema", "schema": schema}}}


def _parse(resp, batch: bool = False) -> dict:
    if resp.stop_reason == "refusal":
        raise JudgeRefused(str(getattr(resp, "stop_details", None)))
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("Judge output truncated (max_tokens)")
    text = next(b.text for b in resp.content if b.type == "text")
    return {"data": json.loads(text), "model": resp.model, "batch": batch, "backend": "api",
            "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}}


async def _json_call(system: str, user: str, schema: dict) -> dict:
    if get_settings().judge_backend == "claude-code":
        return await _cli_call(system, user, schema)
    resp = await client().beta.messages.create(
        **_params(system, user, schema),
        # Server-side refusal fallback (routes by refusal category); unlikely to trigger on accounting text
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    return _parse(resp)


# ---------- key points ----------

KEY_POINTS_SCHEMA = {
    "type": "object",
    "properties": {
        "key_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "K1, K2, ..."},
                    "point": {"type": "string", "description": "One atomic, checkable point, paraphrased"},
                    "kind": {"type": "string", "enum": ["standard", "beyond_standard"]},
                },
                "required": ["id", "point", "kind"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["key_points"],
    "additionalProperties": False,
}

KEY_POINTS_SYSTEM = """You are an IFRS 9 expert preparing a grading rubric.
Break the human-written reference answer into its key points: atomic, independently checkable statements of substance
(requirements, conditions, definitions, examples, nuances). Cover the whole reference; do not add anything it does not say.
Merge trivial restatements; keep distinct conditions separate.
Tag each point:
- "standard": a requirement, definition or condition that comes from the IFRS 9 / IFRS 7 Standard text itself.
- "beyond_standard": industry practice, regulatory or ITG guidance, Basel references, examples or opinions not in the Standard."""


async def key_points(topic) -> dict:
    user = (
        f"Topic: {topic.code} {topic.title}\n\nQuestions the topic asks:\n" + "\n".join(topic.questions)
        + f"\n\n<reference_answer label=\"{topic.reference_label}\">\n{topic.reference}\n</reference_answer>"
    )
    return await _json_call(KEY_POINTS_SYSTEM, user, KEY_POINTS_SCHEMA)


# ---------- grading ----------

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "point_grades": {
            "type": "array",
            "description": "One entry per key point, in rubric order",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "A": {"type": "string", "enum": ["full", "partial", "missing"]},
                    "B": {"type": "string", "enum": ["full", "partial", "missing"]},
                    "note": {"type": "string", "description": "Short justification, quoting wording where useful"},
                },
                "required": ["id", "A", "B", "note"],
                "additionalProperties": False,
            },
        },
        "contradictions": {
            "type": "object",
            "description": "Statements in each answer that contradict the reference or are wrong",
            "properties": {"A": {"type": "array", "items": {"type": "string"}}, "B": {"type": "array", "items": {"type": "string"}}},
            "required": ["A", "B"],
            "additionalProperties": False,
        },
        "similarity": {
            "type": "object",
            "description": "0-10 overall closeness to the reference answer",
            "properties": {"A": {"type": "integer"}, "B": {"type": "integer"}},
            "required": ["A", "B"],
            "additionalProperties": False,
        },
        "winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "rationale": {"type": "string", "description": "3-6 sentences: where each answer aligns with or misses the reference"},
    },
    "required": ["point_grades", "contradictions", "similarity", "winner", "rationale"],
    "additionalProperties": False,
}

GRADE_SYSTEM = """You are an impartial IFRS 9 expert judging how close two answers are to a human-written reference answer.
The answers come from two different systems; their order is random and carries no meaning. Do not favour length or style.
For each key point of the rubric, grade each answer:
- full: the answer states the point with its substance and conditions intact (wording may differ);
- partial: the answer touches the point but loses a condition, nuance or part of it;
- missing: absent, or the answer says the material does not address it.
Then score overall similarity to the reference from 0 to 10 (10 = covers everything the reference says, with nothing contradictory),
list contradictions or errors relative to the reference, pick the closer answer (or tie), and explain briefly."""


def _grade_user(topic, points: list[dict], answer_a: str, answer_b: str) -> str:
    rubric = "\n".join(f"{p['id']} [{p['kind']}]: {p['point']}" for p in points)
    user = (
        f"Topic: {topic.code} {topic.title}\n\nQuestions asked:\n" + "\n".join(topic.questions)
        + f"\n\n<reference_answer>\n{topic.reference}\n</reference_answer>\n\n<rubric>\n{rubric}\n</rubric>"
        + f"\n\n<answer_A>\n{answer_a}\n</answer_A>\n\n<answer_B>\n{answer_b}\n</answer_B>"
    )
    return user


async def grade(topic, points: list[dict], answer_a: str, answer_b: str) -> dict:
    return await _json_call(GRADE_SYSTEM, _grade_user(topic, points, answer_a, answer_b), GRADE_SCHEMA)


def grade_params(topic, points: list[dict], answer_a: str, answer_b: str) -> dict:
    """The same grading request, for the Message Batches API (which does not take the refusal fallback)."""
    return _params(GRADE_SYSTEM, _grade_user(topic, points, answer_a, answer_b), GRADE_SCHEMA)


async def grade_batch(requests: dict[str, dict], batch_id: str | None, on_submit, log=print) -> dict[str, dict | Exception]:
    """Submit (or, on resume, keep polling) one batch of gradings; each custom_id gets its result or the reason it failed."""
    s = get_settings()
    c = client()
    if not batch_id:
        b = await c.messages.batches.create(requests=[{"custom_id": k, "params": v} for k, v in requests.items()])
        batch_id = b.id
        await on_submit(batch_id)
        log(f"  grading batch {batch_id}: {len(requests)} gradings submitted")
    start, cancelled = time.monotonic(), False
    while True:
        b = await c.messages.batches.retrieve(batch_id)
        if b.processing_status == "ended":
            break
        if not cancelled and time.monotonic() - start > s.batch_timeout_s:
            await c.messages.batches.cancel(batch_id)  # what is left is graded normally
            cancelled = True
            log(f"  grading batch {batch_id}: not finished after {s.batch_timeout_s // 60} min, cancelled")
        await asyncio.sleep(s.batch_poll_s)
    out: dict[str, dict | Exception] = {}
    async for r in await c.messages.batches.results(batch_id):
        if r.result.type == "succeeded":
            try:
                out[r.custom_id] = _parse(r.result.message, batch=True)
            except Exception as e:  # refused or truncated: graded normally, with the refusal fallback
                out[r.custom_id] = e
        else:
            out[r.custom_id] = RuntimeError(f"batch result {r.result.type}")
    for k in requests:
        out.setdefault(k, RuntimeError("missing from the batch results"))
    return out


