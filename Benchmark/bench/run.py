"""Run the benchmark. Results are stored in bench.runs (see migrations/).

  python -m bench.run                      # new run: all topics, RUNS runs, inputs from QUERY_SET / REFERENCE_DOCX
  python -m bench.run --topics 2 --runs 1  # quick check
  python -m bench.run --run-id 20261008-101500  # run/resume a stored run (inputs come from the row; used by the UI)
"""
import argparse
import asyncio
import datetime as dt
import os
import pathlib
import random
import statistics
import subprocess
import sys
import tempfile

import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

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
    if c := os.environ.get("RENDER_GIT_COMMIT"):
        return c[:7]
    try:
        return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return None


class Store:
    """A bench.runs row. `data` (results) and the log are rewritten after every completed step so a run can resume."""

    LOG_LINES = 300

    def __init__(self, conn: psycopg.Connection, run_id: str, data: dict, log: str = ""):
        self.conn, self.run_id, self.data = conn, run_id, data
        self.lines = log.splitlines()
        self.lock = asyncio.Lock()

    def log(self, msg: str = ""):
        print(msg, flush=True)
        self.lines.extend(msg.splitlines() or [""])
        del self.lines[: -self.LOG_LINES]

    async def heartbeat(self):
        """Lets the UI tell a live run from one killed mid-way (e.g. by a redeploy)."""
        while True:
            await asyncio.sleep(30)
            async with self.lock:
                await asyncio.to_thread(self.conn.execute, "update bench.runs set updated_at = now() where id = %s", (self.run_id,))

    async def save(self, status: str | None = None):
        async with self.lock:
            await asyncio.to_thread(
                self.conn.execute,
                "update bench.runs set results = %s, log = %s, status = coalesce(%s, status), updated_at = now() where id = %s",
                (Jsonb(self.data), "\n".join(self.lines), status, self.run_id),
            )


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
            store.log(f"  topic {t.number:>2} run {r}: rag {per_system['rag']['similarity']}/10 ({per_system['rag']['coverage']}%) "
                  f"| wiki {per_system['wiki']['similarity']}/10 ({per_system['wiki']['coverage']}%) -> {winner}")
            await store.save()


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


def _new_run(conn: psycopg.Connection, topics: str, runs: int) -> str:
    """CLI: store a new run with the local QUERY_SET / REFERENCE_DOCX files as its inputs."""
    s = get_settings()
    if not (s.rag_collection and s.wiki_slug):
        sys.exit("Set RAG_COLLECTION and WIKI_SLUG (the RAG collection and the wiki to compare)")
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    conn.execute(
        """insert into bench.runs (id, topics, runs, rag_collection, wiki_slug, query_set_name, query_set, reference_name, reference)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (run_id, topics, runs, s.rag_collection, s.wiki_slug, s.query_set.name, s.query_set.read_bytes(),
         s.reference_docx.name, s.reference_docx.read_bytes()),
    )
    return run_id


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", help="e.g. 1,2,5-7 (default: all)")
    ap.add_argument("--runs", type=int)
    ap.add_argument("--run-id", help="stored run to execute or resume")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    s = get_settings()
    conn = psycopg.connect(s.database_url, autocommit=True, row_factory=dict_row)
    run_id = args.run_id or _new_run(conn, args.topics or "", args.runs or s.runs)
    row = conn.execute("select * from bench.runs where id = %s", (run_id,)).fetchone()
    if not row:
        sys.exit(f"Run {run_id} not found")
    if not (row["query_set"] and row["reference"]):
        sys.exit(f"Run {run_id} has no query set / reference document")
    if not row["rag_collection"]:
        sys.exit(f"Run {run_id} has no RAG collection")
    s.rag_collection, s.wiki_slug = row["rag_collection"], row["wiki_slug"]
    runs = args.runs or row["runs"]
    store = Store(conn, run_id, row["results"] or {}, row["log"])
    store.log(f"--- {dt.datetime.now().isoformat(timespec='seconds')} start")
    await store.save("running")
    beat = asyncio.create_task(store.heartbeat())

    try:
        with tempfile.TemporaryDirectory() as tmp:
            qs, ref = pathlib.Path(tmp, "query_set.txt"), pathlib.Path(tmp, "reference.docx")
            qs.write_bytes(row["query_set"])
            ref.write_bytes(row["reference"])
            topics = load(qs, ref)
        wanted = set(parse_topics(args.topics or row["topics"] or None, len(topics)))
        topics = [t for t in topics if t.number in wanted]

        async with httpx.AsyncClient() as http:
            if not store.data:
                store.data = {
                    "config": {
                        "started": dt.datetime.now().isoformat(timespec="seconds"), "git_commit": _git_commit(),
                        "judge_model": s.judge_model, "judge_effort": s.judge_effort, "runs": runs, "seed": s.seed,
                        "topics_selected": [t.number for t in topics], "expected_judgements": len(topics) * runs,
                        "question_format": "topic title + Q1..Qn, sent identically to RAG /collections/{c}/query and Wiki /wikis/{w}/query",
                        "rag_collection": s.rag_collection, "wiki_slug": s.wiki_slug,
                        "systems": await systems.describe(http),
                        "query_set": row["query_set_name"], "reference": row["reference_name"],
                    },
                    "topics": {},
                }
                await store.save()
            store.log(f"Benchmark {run_id}  ({len(topics)} topics x {runs} runs)")
            sem = asyncio.Semaphore(s.concurrency)
            results = await asyncio.gather(*(run_topic(t, runs, store, http, sem) for t in topics), return_exceptions=True)

        errors = {t.number: f"{type(r).__name__}: {r}" for t, r in zip(topics, results) if isinstance(r, Exception)}
        store.data["errors"] = errors
        aggregate(store.data)
        store.data["config"]["finished"] = dt.datetime.now().isoformat(timespec="seconds")

        sm = store.data["summary"]
        store.log("\nSummary (mean of topic means):")
        for name, v in sm["by_system"].items():
            store.log(f"  {name:<5} similarity {v['similarity']['mean']}/10  coverage {v['coverage']['mean']}%  "
                      f"standard-only coverage {v['coverage_standard']['mean']}%")
        store.log(f"  wins (per run): {sm['wins_by_run']}")
        if errors:
            store.log(f"  errors: {errors}  (resume with --run-id {run_id})")
        await store.save("finished")
    except BaseException as e:
        store.log(f"FAILED: {type(e).__name__}: {e}")
        await store.save("failed")
        raise
    finally:
        beat.cancel()
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
