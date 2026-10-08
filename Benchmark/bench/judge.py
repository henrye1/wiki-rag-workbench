"""Claude as judge: extract key points from the human reference, then grade two anonymised answers against them."""
import json

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


async def _json_call(system: str, user: str, schema: dict) -> dict:
    s = get_settings()
    resp = await client().beta.messages.create(
        model=s.judge_model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": s.judge_effort, "format": {"type": "json_schema", "schema": schema}},
        # Server-side refusal fallback (routes by refusal category); unlikely to trigger on accounting text
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        raise JudgeRefused(str(resp.stop_details))
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("Judge output truncated (max_tokens)")
    text = next(b.text for b in resp.content if b.type == "text")
    return {"data": json.loads(text), "model": resp.model,
            "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}}


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


async def grade(topic, points: list[dict], answer_a: str, answer_b: str) -> dict:
    rubric = "\n".join(f"{p['id']} [{p['kind']}]: {p['point']}" for p in points)
    user = (
        f"Topic: {topic.code} {topic.title}\n\nQuestions asked:\n" + "\n".join(topic.questions)
        + f"\n\n<reference_answer>\n{topic.reference}\n</reference_answer>\n\n<rubric>\n{rubric}\n</rubric>"
        + f"\n\n<answer_A>\n{answer_a}\n</answer_A>\n\n<answer_B>\n{answer_b}\n</answer_B>"
    )
    return await _json_call(GRADE_SYSTEM, user, GRADE_SCHEMA)

