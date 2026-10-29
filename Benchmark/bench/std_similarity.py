"""Standard-only similarity: an extra measure, added to a finished run without changing anything in it.

The saved answers of both systems are judged again, by the same judge (model, effort, both A/B orders with the run's own
blind labels, Message Batches with the normal API for the rest), against only the topic's rubric points tagged
"standard", on the same 0-10 scale as similarity. No answer is generated again; the run's existing scores are not
touched. Each answer's score is the mean of its two orders; a topic's is the mean over its repetitions; a run's is the
mean of topic means, with the wiki-minus-RAG gap and its 95% interval as for the other tests. A topic with no point
tagged standard is not scored. The result is stored in the run's results under "standard_similarity".

  python -m bench.std_similarity RUN_ID [RUN_ID ...]
"""
import asyncio
import statistics
import sys

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import gaps, judge
from .config import get_settings

VERSION = "std-sim-1"
ORDERS = ("1", "2")

STD_SCHEMA = {
    "type": "object",
    "properties": {
        "similarity": {
            "type": "object",
            "description": "0-10 overall closeness to the reference points",
            "properties": {"A": {"type": "integer"}, "B": {"type": "integer"}},
            "required": ["A", "B"],
            "additionalProperties": False,
        },
        "rationale": {"type": "string", "description": "2-4 sentences: where each answer aligns with or misses the reference points"},
    },
    "required": ["similarity", "rationale"],
    "additionalProperties": False,
}

STD_SYSTEM = """You are an impartial IFRS 9 expert judging how close two answers are to a reference.
The reference here is only the points of a human-written reference answer that come from the Standard text itself.
The answers come from two different systems; their order is random and carries no meaning. Do not favour length or style.
Score overall similarity to the reference points from 0 to 10 (10 = covers everything the reference points say, with
nothing contradictory). Judge only against these points: material an answer adds beyond them neither raises nor lowers
its score unless it contradicts them. Explain briefly."""


def _user(rec: dict, points: list[dict], answer_a: str, answer_b: str) -> str:
    ref = "\n".join(f"{p['id']}: {p['point']}" for p in points)
    return (f"Topic: {rec['code']} {rec['title']}\n\nQuestions asked:\n{rec['question']}"
            f"\n\n<reference_points>\n{ref}\n</reference_points>"
            f"\n\n<answer_A>\n{answer_a}\n</answer_A>\n\n<answer_B>\n{answer_b}\n</answer_B>")


def _requests(data: dict) -> tuple[dict[str, dict], dict[str, tuple]]:
    """Every pair to judge, by custom id (topic, repetition, order), with what each answer label stands for."""
    reqs, where = {}, {}
    for n, rec in data["topics"].items():
        points = [p for p in rec["key_points"] if p["kind"] == "standard"]
        if not points:
            continue
        for r, run in rec["runs"].items():
            if not run.get("judgement"):
                continue
            for k in ORDERS:
                label = run["orders"][k]["blind_labels"]
                cid = f"t{n}-r{r}-o{k}"
                user = _user(rec, points, run["systems"][label["A"]]["answer"], run["systems"][label["B"]]["answer"])
                reqs[cid] = judge._params(STD_SYSTEM, user, STD_SCHEMA)
                where[cid] = (n, r, k, label, user)
    return reqs, where


def _summary(scores: dict) -> dict:
    """Run means (mean of topic means) per system, and the gap with its interval, as for the other judged tests."""
    pseudo = {"topics": {n: {"runs": {r: {"judgement": True, "systems": {s: {"similarity": v[s]} for s in ("rag", "wiki")}}
                                      for r, v in by_r.items()}} for n, by_r in scores.items()}}
    topic_means = {s: [statistics.mean(v[s] for v in by_r.values()) for by_r in scores.values()] for s in ("rag", "wiki")}
    return {"by_system": {s: {"mean": round(statistics.mean(m), 2), "n_topics": len(m)} for s, m in topic_means.items()},
            "gap": gaps.gaps(pseudo)["similarity"]}


async def run(run_id: str, conn: psycopg.Connection):
    s = get_settings()
    row = conn.execute("select results from bench.runs where id = %s", (run_id,)).fetchone()
    if not row:
        sys.exit(f"Run {run_id} not found")
    data = row["results"]
    prev = data.get("standard_similarity") or {}
    reqs, where = _requests(data)
    print(f"Run {run_id}: {len(reqs)} pairs to judge ({len({w[0] for w in where.values()})} topics with standard points)", flush=True)

    def store(value: dict):
        conn.execute("update bench.runs set results = jsonb_set(results, '{standard_similarity}', %s) where id = %s", (Jsonb(value), run_id))

    async def on_submit(batch_id):
        store({"version": VERSION, "batch": batch_id, "status": "judging"})
    got = await judge.grade_batch(reqs, prev.get("batch") if prev.get("status") == "judging" else None, on_submit, what="standard-only similarity")
    sem = asyncio.Semaphore(s.concurrency)

    async def again(cid):  # what the batch did not return, judged normally (with the refusal fallback)
        async with sem:
            try:
                got[cid] = await judge._json_call(STD_SYSTEM, where[cid][4], STD_SCHEMA)
            except Exception as e:
                got[cid] = e
    await asyncio.gather(*(again(c) for c, v in got.items() if isinstance(v, Exception)))

    per_pair, errors = {}, {}
    for cid, (n, r, k, label, _) in where.items():
        res = got[cid]
        if isinstance(res, Exception):
            errors[cid] = f"{type(res).__name__}: {res}"
            continue
        sim = res["data"]["similarity"]
        per_pair.setdefault(n, {}).setdefault(r, {})[k] = {"scores": {label["A"]: sim["A"], label["B"]: sim["B"]},
                                                           "rationale": res["data"]["rationale"], "usage": res["usage"]}
    scores = {n: {r: {sys_: statistics.mean(o[k]["scores"][sys_] for k in ORDERS) for sys_ in ("rag", "wiki")}
                  for r, o in by_r.items() if all(k in o for k in ORDERS)} for n, by_r in per_pair.items()}
    scores = {n: v for n, v in scores.items() if v}
    value = {"version": VERSION, "status": "done", "judge_model": s.judge_model, "judge_effort": s.judge_effort,
             "reference": "rubric points tagged standard", "scale": "0-10, as similarity",
             "orders": "both, with the run's blind labels; each answer's score is the mean of the two",
             "topics": {n: {"repetitions": per_pair[n], "scores": scores.get(n)} for n in per_pair},
             "summary": _summary(scores) if scores else None, "errors": errors}
    store(value)
    sm = value["summary"]
    if sm:
        print(f"  rag  standard-only similarity {sm['by_system']['rag']['mean']}/10\n"
              f"  wiki standard-only similarity {sm['by_system']['wiki']['mean']}/10\n"
              f"  gap {sm['gap']['diff']} CI {sm['gap']['ci']} -> {sm['gap']['verdict']}"
              + (f"\n  errors: {errors}" if errors else ""), flush=True)


async def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with psycopg.connect(get_settings().database_url, autocommit=True, row_factory=dict_row) as conn:
        for run_id in sys.argv[1:]:
            await run(run_id, conn)


if __name__ == "__main__":
    asyncio.run(main())
