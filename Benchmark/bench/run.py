"""Run the benchmark.

  python -m bench.run                      # all topics, RUNS runs
  python -m bench.run --topics 2 --runs 1  # quick check
  python -m bench.run --resume results/20261008-101500
"""
import argparse
import asyncio
import datetime as dt
import json
import random
import statistics
import subprocess
import sys

import httpx

from . import judge, systems
from .config import ROOT, get_settings
from .data import Topic, load

WEIGHT = {"full": 1.0, "partial": 0.5, "missing": 0.0}


def parse_topics(spec: str | None, n: int) -> list[int]:
    if not spec:
        return list(range(1, n + 1))
    out: set[int] = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return sorted(out)


def coverage(points: list[dict], grades: dict[str, str], kind: str | None = None) -> float | None:
    ids = [p["id"] for p in points if kind is None or p["kind"] == kind]
    if not ids:
        return None
    return round(100 * sum(WEIGHT[grades.get(i, "missing")] for i in ids) / len(ids), 1)


def _mean_sd(xs: list[float]) -> dict:
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"mean": None, "sd": None, "n": 0}
    return {"mean": round(statistics.mean(xs), 2), "sd": round(statistics.stdev(xs), 2) if len(xs) > 1 else 0.0, "n": len(xs)}


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return None


class Store:
    """results.json, rewritten after every completed step so a run can resume."""

    def __init__(self, path):
        self.path = path
        self.lock = asyncio.Lock()
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    async def save(self):
        async with self.lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)


async def run_topic(t: Topic, runs: int, store: Store, http: httpx.AsyncClient, sem: asyncio.Semaphore):
    s = get_settings()
    rec = store.data["topics"].setdefault(str(t.number), {
        "number": t.number, "code": t.code, "title": t.title, "section": t.section,
        "question": t.question_text(), "reference_label": t.reference_label, "reference": t.reference, "runs": {},
    })
    async with sem:
        if "key_points" not in rec:
            kp = await judge.key_points(t)
            rec["key_points"] = kp["data"]["key_points"]
            rec["key_points_usage"] = kp["usage"]
            await store.save()
        points = rec["key_points"]

        for r in range(1, runs + 1):
            if str(r) in rec["runs"] and "judgement" in rec["runs"][str(r)]:
                continue
            answers = dict(zip(systems.SYSTEMS, await asyncio.gather(*(systems.ask(http, sys_, t.question_text()) for sys_ in systems.SYSTEMS))))
            order = list(systems.SYSTEMS)
            random.Random(f"{s.seed}-{t.number}-{r}").shuffle(order)  # blind A/B assignment
            label = {"A": order[0], "B": order[1]}
            g = await judge.grade(t, points, answers[label["A"]]["answer"], answers[label["B"]]["answer"])
            jd = g["data"]
            per_system = {}
            for lab, name in label.items():
                grades = {pg["id"]: pg[lab] for pg in jd["point_grades"]}
                per_system[name] = {
                    **answers[name],
                    "grades": grades,
                    "similarity": jd["similarity"][lab],
                    "coverage": coverage(points, grades),
                    "coverage_standard": coverage(points, grades, "standard"),
                    "contradictions": jd["contradictions"][lab],
                }
            winner = "tie" if jd["winner"] == "tie" else label[jd["winner"]]
            rec["runs"][str(r)] = {
                "blind_labels": label, "systems": per_system, "winner": winner, "rationale": jd["rationale"],
                "point_notes": {pg["id"]: pg["note"] for pg in jd["point_grades"]}, "judge_model": g["model"], "judge_usage": g["usage"],
                "judgement": True,
            }
            await store.save()
            print(f"  topic {t.number:>2} run {r}: rag {per_system['rag']['similarity']}/10 ({per_system['rag']['coverage']}%) "
                  f"| wiki {per_system['wiki']['similarity']}/10 ({per_system['wiki']['coverage']}%) -> {winner}", flush=True)


def aggregate(data: dict):
    totals = {name: {"similarity": [], "coverage": [], "coverage_standard": []} for name in systems.SYSTEMS}
    wins = {"rag": 0, "wiki": 0, "tie": 0}
    sections: dict[str, dict] = {}
    for rec in data["topics"].values():
        runs = [r for r in rec["runs"].values() if r.get("judgement")]
        if not runs:
            continue
        agg = {}
        for name in systems.SYSTEMS:
            agg[name] = {k: _mean_sd([r["systems"][name][k] for r in runs]) for k in ("similarity", "coverage", "coverage_standard")}
            for k in totals[name]:
                if agg[name][k]["mean"] is not None:
                    totals[name][k].append(agg[name][k]["mean"])
            sec = sections.setdefault(rec["section"], {n: [] for n in systems.SYSTEMS})
            sec[name].append(agg[name]["similarity"]["mean"])
        topic_wins = {w: sum(r["winner"] == w for r in runs) for w in wins}
        for w, c in topic_wins.items():
            wins[w] += c
        agg["wins"] = topic_wins
        # Per key point: how often each system covered it fully across runs
        agg["key_point_hit_rate"] = {
            p["id"]: {name: round(sum(WEIGHT[r["systems"][name]["grades"].get(p["id"], "missing")] for r in runs) / len(runs), 2)
                      for name in systems.SYSTEMS}
            for p in rec["key_points"]
        }
        rec["aggregate"] = agg
    data["summary"] = {
        "topics_scored": len(totals["rag"]["similarity"]),
        "by_system": {name: {k: _mean_sd(v) for k, v in totals[name].items()} for name in systems.SYSTEMS},
        "wins_by_run": wins,
        "by_section_similarity": {sec: {n: _mean_sd(v)["mean"] for n, v in d.items()} for sec, d in sections.items()},
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", help="e.g. 1,2,5-7 (default: all)")
    ap.add_argument("--runs", type=int)
    ap.add_argument("--resume", help="existing results dir to continue")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    s = get_settings()
    runs = args.runs or s.runs
    topics = load()
    wanted = set(parse_topics(args.topics, len(topics)))
    topics = [t for t in topics if t.number in wanted]

    out_dir = ROOT / args.resume if args.resume else ROOT / "results" / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    store = Store(out_dir / "results.json")

    async with httpx.AsyncClient() as http:
        if not store.data:
            store.data = {
                "config": {
                    "started": dt.datetime.now().isoformat(timespec="seconds"), "git_commit": _git_commit(),
                    "judge_model": s.judge_model, "judge_effort": s.judge_effort, "runs": runs, "seed": s.seed,
                    "question_format": "topic title + Q1..Qn, sent identically to RAG /query and Wiki /query",
                    "systems": await systems.describe(http),
                    "query_set": s.query_set.name, "reference": s.reference_docx.name,
                },
                "topics": {},
            }
            await store.save()
        print(f"Benchmark -> {out_dir}  ({len(topics)} topics x {runs} runs)", flush=True)
        sem = asyncio.Semaphore(s.concurrency)
        results = await asyncio.gather(*(run_topic(t, runs, store, http, sem) for t in topics), return_exceptions=True)

    errors = {t.number: f"{type(r).__name__}: {r}" for t, r in zip(topics, results) if isinstance(r, Exception)}
    store.data["errors"] = errors
    aggregate(store.data)
    store.data["config"]["finished"] = dt.datetime.now().isoformat(timespec="seconds")
    await store.save()

    sm = store.data["summary"]
    print("\nSummary (mean of topic means):")
    for name, v in sm["by_system"].items():
        print(f"  {name:<5} similarity {v['similarity']['mean']}/10  coverage {v['coverage']['mean']}%  "
              f"standard-only coverage {v['coverage_standard']['mean']}%")
    print(f"  wins (per run): {sm['wins_by_run']}")
    if errors:
        print(f"  errors: {errors}  (re-run with --resume {out_dir.relative_to(ROOT)})")
    print(f"Results: {out_dir / 'results.json'}")


if __name__ == "__main__":
    asyncio.run(main())
