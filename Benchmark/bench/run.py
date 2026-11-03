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

from . import checks, context, gaps, judge, metrics, rubric, std_similarity, systems
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


def coverage(points: list[dict], grades: dict[str, str], kind: str | tuple | None = None) -> float | None:
    kinds = (kind,) if isinstance(kind, str) else kind
    ids = [p["id"] for p in points if kinds is None or p["kind"] in kinds]
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
        self.ref_sha = self.ref_name = None  # the reference file, whose saved rubric the run uses
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


async def answer_topic(t: Topic, runs: int, store: Store, http: httpx.AsyncClient, sem: asyncio.Semaphore):
    """Its key points (the saved rubric) and both systems' answers for every repetition, saved before any grading."""
    rec = store.data["topics"].setdefault(str(t.number), {
        "number": t.number, "code": t.code, "title": t.title, "section": t.section,
        "question": t.question_text(), "reference_label": t.reference_label, "reference": t.reference, "runs": {},
    })
    async with sem:
        if "key_points" not in rec:
            # The rubric is built once per reference file and reused, so every run is scored against the same key points
            async with store.lock:
                saved = await asyncio.to_thread(rubric.get, store.conn, store.ref_sha, t.number)
            stale = bool(saved) and saved["topic_title"] != t.title  # the query set pairs this topic with another block
            if stale:
                store.log(f"  topic {t.number}: saved rubric is for '{saved['topic_title']}', building one for '{t.title}'")
            if not saved or stale:
                kp = await judge.key_points(t)
                async with store.lock:
                    await asyncio.to_thread(rubric.save, store.conn, store.ref_sha, store.ref_name, t.number, t.title,
                                            kp["data"]["key_points"], kp["usage"], kp["model"], store.run_id, stale)
                    saved = await asyncio.to_thread(rubric.get, store.conn, store.ref_sha, t.number)
            if saved.get("facts") is None:
                # the exact-match facts are made once per reference file and topic too, then kept for you to approve
                fx = await checks.make_facts(t.title, t.questions, t.reference, t.reference_label)
                async with store.lock:
                    await asyncio.to_thread(checks.save_facts, store.conn, store.ref_sha, t.number, fx["data"]["facts"], fx["usage"], fx["model"])
                    saved = await asyncio.to_thread(rubric.get, store.conn, store.ref_sha, t.number)
            rec["key_points"] = saved["key_points"]
            rec["key_points_usage"] = saved["key_points_usage"]
            rec["facts"] = saved.get("facts")  # exact-match facts (None until made)
            # the version of this topic's rubric the run used, and whether you had approved it
            rec["rubric"] = {"built_in": saved["source_run"], "saved_at": saved["created_at"].isoformat(timespec="seconds"),
                             "version": saved.get("version", 1),
                             "approved": saved.get("reviewed_at").isoformat(timespec="seconds") if saved.get("reviewed_at") else None,
                             "facts_approved": saved.get("facts_reviewed_at").isoformat(timespec="seconds") if saved.get("facts_reviewed_at") else None}
            await store.save()
        for r in range(1, runs + 1):
            run = rec["runs"].get(str(r)) or {}
            if run.get("judgement") or run.get("answers"):
                continue
            # answers are saved before grading, so a run whose grading failed is graded later without asking again
            names = systems.compared(store.data)
            answers = dict(zip(names, await asyncio.gather(*(systems.ask(http, sys_, t.question_text()) for sys_ in names))))
            rec["runs"][str(r)] = {"answers": answers, "judgement": False}
            await store.save()


def _labels(t: Topic, r: int, order: int = 1, rag: str = "rag") -> dict:
    """Blind A/B labels of one pair (a RAG system and the wiki): order 1 is the seeded shuffle; order 2 swaps it (each
    pair is graded both ways). The rag pair keeps the seed it always had; each other pair has its own."""
    seq = [rag, "wiki"]
    random.Random(f"{get_settings().seed}-{t.number}-{r}" + ("" if rag == "rag" else f"-{rag}")).shuffle(seq)  # blind A/B assignment
    if order == 2:
        seq.reverse()
    return {"A": seq[0], "B": seq[1]}


ORDERS = (1, 2)


def _per_order(points: list[dict], label: dict, g: dict) -> dict:
    """One grading (one order) read per system."""
    jd = g["data"]
    out = {"blind_labels": label, "winner": "tie" if jd["winner"] == "tie" else label[jd["winner"]], "rationale": jd["rationale"],
           "point_notes": {pg["id"]: pg["note"] for pg in jd["point_grades"]}, "judge_model": g["model"], "judge_usage": g["usage"],
           "batch": g.get("batch", False), "backend": g.get("backend", "api"), "systems": {}}
    for lab, name in label.items():
        grades = {pg["id"]: pg[lab] for pg in jd["point_grades"]}
        out["systems"][name] = {"grades": grades, "similarity": jd["similarity"][lab], "contradictions": jd["contradictions"][lab]}
    return out


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _scores(points: list[dict], o: list[dict], name: str, all_sources: bool) -> dict:
    """One system's scores in one pair, from its gradings in both orders."""
    return {
        "grades": o[0]["systems"][name]["grades"],  # order 1, as in runs before both orders
        "grades_by_order": [x["systems"][name]["grades"] for x in o],
        "point_weight": {p["id"]: sum(WEIGHT[x["systems"][name]["grades"].get(p["id"], "missing")] for x in o) / len(o) for p in points},
        "similarity": _avg([x["systems"][name]["similarity"] for x in o]),
        "coverage": _avg([coverage(points, x["systems"][name]["grades"]) for x in o]),
        "coverage_standard": _avg([coverage(points, x["systems"][name]["grades"], "standard") for x in o]),
        # Standard + Supporting: only for runs that read all sources (Parts A, B and C)
        "coverage_std_supp": _avg([coverage(points, x["systems"][name]["grades"], ("standard", "supporting")) for x in o])
                             if all_sources else None,
        "contradictions": list(dict.fromkeys(c for x in o for c in x["systems"][name]["contradictions"])),
    }


def _pair(o: list[dict]) -> dict:
    """What a pair's two orders decided: a win only when both orders pick the same answer, else a tie."""
    w = {x["winner"] for x in o}
    return {
        "blind_labels": o[0]["blind_labels"], "winner": w.pop() if len(w) == 1 else "tie",
        "winners_by_order": [x["winner"] for x in o],
        "rationale": "\n\n".join(f"Order {k} ({x['blind_labels']['A']} first): {x['rationale']}" for k, x in zip(ORDERS, o)),
        "point_notes": o[0]["point_notes"], "orders_graded": len(o), "judge_model": o[0]["judge_model"],
        "judge_usage": {k: sum(x["judge_usage"][k] for x in o) for k in ("input_tokens", "output_tokens")},
        "judge_batch": all(x["batch"] for x in o), "judge_backend": o[0].get("backend", "api"),
    }


def _pair_orders(run: dict, rag: str) -> dict:
    """A pair's gradings by order: the rag pair's are the run's own `orders`; another pair's are kept under `pair_orders`
    until the run is recorded, then under `pairs`."""
    if rag == "rag":
        return run.setdefault("orders", {})
    return ((run.get("pairs") or {}).get(rag) or {}).get("orders") or run.setdefault("pair_orders", {}).setdefault(rag, {})


def _record(store: Store, t: Topic, r: int):
    """Combine the two orders of each pair: scores averaged; a win only when both orders pick the same answer, else a tie.
    The wiki's own scores are from its pair with rag (as in every run before rag_q); its scores in each other pair are
    kept with that pair, beside that pair's RAG system."""
    rec = store.data["topics"][str(t.number)]
    run = rec["runs"][str(r)]
    answers, points = run["answers"], rec["key_points"]
    all_sources = (store.data.get("config") or {}).get("sources") == "all"
    by_pair = {rag: _pair_orders(run, rag) for rag in systems.pairs(store.data)}
    o = [by_pair["rag"][str(k)] for k in ORDERS]
    per_system = {name: {**answers[name], **_scores(points, o, name, all_sources)} for name in ("rag", "wiki")}
    pairs = {}
    for rag in systems.pairs(store.data):
        if rag == "rag":
            continue
        po = [by_pair[rag][str(k)] for k in ORDERS]
        per_system[rag] = {**answers[rag], **_scores(points, po, rag, all_sources)}
        pairs[rag] = {**_pair(po), "orders": by_pair[rag], "wiki": _scores(points, po, "wiki", all_sources)}
    main = _pair(o)
    rec["runs"][str(r)] = {**main, "systems": per_system, "orders": by_pair["rag"], "judgement": True,
                           **({"pairs": pairs} if pairs else {})}
    store.log(f"  topic {t.number:>2} run {r}: rag {per_system['rag']['similarity']}/10 ({per_system['rag']['coverage']}%) "
              f"| wiki {per_system['wiki']['similarity']}/10 ({per_system['wiki']['coverage']}%) -> {main['winner']}"
              + ("" if len(set(main["winners_by_order"])) == 1 else f" (orders disagreed: {', '.join(main['winners_by_order'])})")
              + "".join(f" | {rag} {per_system[rag]['similarity']}/10 ({per_system[rag]['coverage']}%) vs wiki "
                        f"{p['wiki']['similarity']}/10 -> {p['winner']}" for rag, p in pairs.items()))


async def grade_all(topics: list[Topic], store: Store, sem: asyncio.Semaphore) -> dict[int, str]:
    """Grade every saved, ungraded answer pair in both orders: through one Message Batch (half price) when batching is on,
    the rest (and anything the batch did not return) with the normal API. Each order is saved as it arrives, so a pair
    whose second order failed is finished on resume. Returns the topics whose grading failed."""
    s = get_settings()
    pending = [(t, int(r)) for t in topics for r, run in store.data["topics"].get(str(t.number), {}).get("runs", {}).items()
               if run.get("answers") and not run.get("judgement")]
    if not pending:
        return {}
    rags = systems.pairs(store.data)
    cid = lambda t, r, k, p: f"t{t.number}-r{r}-o{k}" + ("" if p == "rag" else f"-{p}")  # the rag pair keeps its old ids
    def args(t, r, k, p):
        rec, label = store.data["topics"][str(t.number)], _labels(t, r, k, p)
        answers = rec["runs"][str(r)]["answers"]
        return rec["key_points"], answers[label["A"]]["answer"], answers[label["B"]]["answer"]
    def done(t, r, k, p):
        return str(k) in _pair_orders(store.data["topics"][str(t.number)]["runs"][str(r)], p)
    def keep(t, r, k, p, g):
        run = store.data["topics"][str(t.number)]["runs"][str(r)]
        _pair_orders(run, p)[str(k)] = _per_order(store.data["topics"][str(t.number)]["key_points"], _labels(t, r, k, p), g)
        if all(str(o) in _pair_orders(run, q) for q in rags for o in ORDERS):
            _record(store, t, r)
    todo = [(t, r, k, p) for t, r in pending for p in rags for k in ORDERS if not done(t, r, k, p)]
    if s.use_batch and todo:
        prev = store.data.get("grading_batch") or {}
        reqs = {cid(*x): judge.grade_params(x[0], *args(*x)) for x in todo}
        reuse = prev.get("id") if set(prev.get("custom_ids", [])) == set(reqs) else None

        async def on_submit(batch_id):
            store.data["grading_batch"] = {"id": batch_id, "custom_ids": sorted(reqs)}
            await store.save()
        try:
            got = await judge.grade_batch(reqs, reuse, on_submit, store.log)
            left = []
            for x in todo:
                res = got[cid(*x)]
                if isinstance(res, Exception):
                    left.append(x)
                    store.log(f"  topic {x[0].number} run {x[1]} order {x[2]} ({x[3]} pair): batch grading failed "
                              f"({type(res).__name__}: {res}); grading normally")
                else:
                    keep(*x, res)
            todo = left
            store.data.pop("grading_batch", None)
            await store.save()
        except Exception as e:  # the batch itself failed: grade everything normally
            store.log(f"  grading batch failed ({type(e).__name__}: {e}); grading normally")
    errors: dict[int, str] = {}

    async def one(t, r, k, p):
        async with sem:
            try:
                keep(t, r, k, p, await judge.grade(t, *args(t, r, k, p)))
                await store.save()
            except Exception as e:
                errors[t.number] = f"{type(e).__name__}: {e}"
    await asyncio.gather(*(one(*x) for x in todo))
    return errors


JUDGED = ("similarity", "coverage", "coverage_standard", "coverage_std_supp")


def aggregate(data: dict):
    names = systems.compared(data)
    others = [rag for rag in systems.pairs(data) if rag != "rag"]  # pairs beyond rag vs wiki
    totals = {name: {k: [] for k in JUDGED} for name in names}
    wiki_vs = {rag: {k: [] for k in JUDGED} for rag in others}  # the wiki's scores in each other pair
    wins = {"rag": 0, "wiki": 0, "tie": 0}
    wins_vs = {rag: {rag: 0, "wiki": 0, "tie": 0} for rag in others}
    sections: dict[str, dict] = {}
    for rec in data["topics"].values():
        runs = [r for r in rec["runs"].values() if r.get("judgement")]
        if not runs:
            continue
        agg = {}
        for name in names:
            agg[name] = {k: _mean_sd([r["systems"][name].get(k) for r in runs]) for k in JUDGED}
            for k in totals[name]:
                if agg[name][k]["mean"] is not None:
                    totals[name][k].append(agg[name][k]["mean"])
            sec = sections.setdefault(rec["section"], {n: [] for n in names})
            sec[name].append(agg[name]["similarity"]["mean"])
        topic_wins = {w: sum(r["winner"] == w for r in runs) for w in wins}
        for w, c in topic_wins.items():
            wins[w] += c
        agg["wins"] = topic_wins
        for rag in others:
            vs = {k: _mean_sd([r["pairs"][rag]["wiki"].get(k) for r in runs]) for k in JUDGED}
            for k in JUDGED:
                if vs[k]["mean"] is not None:
                    wiki_vs[rag][k].append(vs[k]["mean"])
            pw = {w: sum(r["pairs"][rag]["winner"] == w for r in runs) for w in wins_vs[rag]}
            for w, c in pw.items():
                wins_vs[rag][w] += c
            agg.setdefault("pairs", {})[rag] = {"wiki": vs, "wins": pw}
        # Per key point: how often each system covered it fully across runs
        agg["key_point_hit_rate"] = {
            p["id"]: {name: round(sum(r["systems"][name]["point_weight"][p["id"]] if "point_weight" in r["systems"][name]
                                      else WEIGHT[r["systems"][name]["grades"].get(p["id"], "missing")] for r in runs) / len(runs), 2)
                      for name in names}
            for p in rec["key_points"]
        }
        rec["aggregate"] = agg
    data["summary"] = {
        "topics_scored": len(totals["rag"]["similarity"]),
        "by_system": {name: {k: _mean_sd(v) for k, v in totals[name].items()} for name in names},
        "wins_by_run": wins,
        "by_section_similarity": {sec: {n: _mean_sd(v)["mean"] for n, v in d.items()} for sec, d in sections.items()},
        # every wiki-minus-RAG gap with its 95% confidence interval over topics; crossing zero = no clear difference
        "gaps": gaps.gaps(data, get_settings().seed),
    }
    if others:  # each other pair: the wiki's scores in it, its wins, and its wiki-minus-RAG gaps
        data["summary"]["pairs"] = {rag: {"wiki": {k: _mean_sd(v) for k, v in wiki_vs[rag].items()}, "wins_by_run": wins_vs[rag],
                                          "gaps": gaps.gaps(data, get_settings().seed, rag)} for rag in others}


def _new_run(conn: psycopg.Connection, topics: str, runs: int) -> str:
    """CLI: store a new run with the local QUERY_SET / REFERENCE_DOCX files as its inputs."""
    s = get_settings()
    if not (s.rag_collection and s.wiki_slug):
        sys.exit("Set RAG_COLLECTION and WIKI_SLUG (the RAG collection and the wiki to compare)")
    if s.sources not in ("standard", "all"):
        sys.exit("SOURCES must be 'standard' (Part A only) or 'all' (Parts A, B and C)")
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    conn.execute(
        """insert into bench.runs (id, topics, runs, rag_collection, wiki_slug, sources, use_saved, mode, use_batch, query_set_name, query_set,
                                  reference_name, reference)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (run_id, topics, runs, s.rag_collection, s.wiki_slug, s.sources, s.use_saved, s.mode, s.use_batch, s.query_set.name, s.query_set.read_bytes(),
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
    s.rag_collection, s.wiki_slug, s.sources = row["rag_collection"], row["wiki_slug"], row["sources"] or "all"
    s.use_saved = row["use_saved"] is not False  # older runs (null) read every page, saved answers included
    s.mode = row.get("mode") or s.mode
    s.use_batch = s.use_batch if row.get("use_batch") is None else row["use_batch"]
    if s.judge_backend == "claude-code":
        s.use_batch = False  # Message Batches are an API feature; the subscription judge grades one call at a time
    runs = args.runs or row["runs"]
    store = Store(conn, run_id, row["results"] or {}, row["log"])
    store.ref_sha, store.ref_name = rubric.sha256(row["reference"]), row["reference_name"]
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
        if s.mode == "full":  # Full runs use an approved rubric only
            ok = {r["topic_number"] for r in conn.execute(
                """select topic_number from bench.rubrics where reference_sha256 = %s and reviewed_at is not null
                   and facts is not null and facts_reviewed_at is not null""", (store.ref_sha,))}
            if missing := [t.number for t in topics if t.number not in ok]:
                raise RuntimeError(f"Full runs need an approved rubric: approve topic(s) {', '.join(map(str, missing))} "
                                   "on the Rubric review screen, or run in Quick mode")

        async with httpx.AsyncClient() as http:
            if not store.data:
                store.data = {
                    "config": {
                        "started": dt.datetime.now().isoformat(timespec="seconds"), "git_commit": _git_commit(),
                        "judge_model": s.judge_model, "judge_effort": s.judge_effort,
                        "judge_backend": "Claude Code on a Claude subscription (claude -p)" if s.judge_backend == "claude-code" else "Anthropic API",
                        "answer_checks": {"model": s.checks_model, "version": checks.VERSION},
                        "context_checks": {"model": s.context_model, "version": context.VERSION} if s.mode == "full" else None, "runs": runs, "seed": s.seed,
                        "topics_selected": [t.number for t in topics], "expected_judgements": len(topics) * runs,
                        "question_format": "topic title + Q1..Qn, sent identically to RAG /collections/{c}/query (both RAG columns) and Wiki /wikis/{w}/query",
                        "systems_compared": list(systems.SYSTEMS),
                        "system_labels": {n: systems.LABEL[n] for n in systems.SYSTEMS},
                        "rag_retrieval": {n: systems.RETRIEVAL[n] for n in systems.RAGS},
                        "rag_collection": s.rag_collection, "wiki_slug": s.wiki_slug, "sources": s.sources, "use_saved_answers": s.use_saved,
                        "mode": s.mode, "grading": ("the wiki answer, asked once, is paired with each RAG column; each pair in both "
                                                    "orders (A-B and B-A), averaged; a win only when both agree; the wiki's own "
                                                    "scores are from its pair with RAG (per topic); "
                                                    + ("message batches (half price), normal API for the rest" if s.use_batch else "normal API")),
                        "capture": "read+usage v1",  # each answer records what was read and its AI calls' tokens
                        "systems": await systems.describe(http),
                        "query_set": row["query_set_name"], "reference": row["reference_name"],
                        "reference_sha256": store.ref_sha,
                    },
                    "topics": {},
                }
                await store.save()
            store.log(f"Benchmark {run_id}  ({len(topics)} topics x {runs} runs)")
            sem = asyncio.Semaphore(s.concurrency)
            results = await asyncio.gather(*(answer_topic(t, runs, store, http, sem) for t in topics), return_exceptions=True)

        errors = {t.number: f"{type(r).__name__}: {r}" for t, r in zip(topics, results) if isinstance(r, Exception)}
        # the rubric version (and approval) of each topic this run used
        store.data["config"]["rubric_used"] = {str(t.number): store.data["topics"][str(t.number)].get("rubric")
                                               for t in topics if str(t.number) in store.data["topics"]}
        # the tests that need no judge, for every saved answer (also when grading fails below)
        await metrics.compute(store.data, s.mode)
        await store.save()
        errors.update(await grade_all([t for t in topics if t.number not in errors], store, sem))
        try:  # completeness, exact match and citation accuracy: one check call per answer
            await checks.run_checks(store.data, store.conn, store.ref_sha, sem, s.use_batch, store.save, store.log)
        except Exception as e:
            store.log(f"Answer checks failed ({type(e).__name__}: {e}); they show as not measured")
        if s.mode == "full":  # faithfulness and context recall: one call per answer, reading what the answer read
            try:
                await context.run_context(store.data, sem, s.use_batch, store.save, store.log)
            except Exception as e:
                store.log(f"Faithfulness and context recall failed ({type(e).__name__}: {e}); they show as not measured")
            try:  # standard-only similarity: the graded pairs judged again against the standard points only
                await std_similarity.compute(store.data, s.use_batch, store.save, store.log)
            except Exception as e:  # kept with the run, so its page says why; a resume judges again
                store.data["standard_similarity"] = {"version": std_similarity.VERSION, "status": "failed", "error": f"{type(e).__name__}: {e}"}
                store.log(f"Standard-only similarity failed ({type(e).__name__}: {e}); it shows as not measured")
        await metrics.compute(store.data, s.mode)  # graded answers keep their tests; the summary is refreshed
        store.data["errors"] = errors
        aggregate(store.data)
        store.data["config"]["finished"] = dt.datetime.now().isoformat(timespec="seconds")

        sm = store.data["summary"]
        store.log("\nSummary (mean of topic means):")
        for name, v in sm["by_system"].items():
            store.log(f"  {name:<5} similarity {v['similarity']['mean']}/10  coverage {v['coverage']['mean']}%  "
                      f"standard-only coverage {v['coverage_standard']['mean']}%")
        store.log(f"  wins (per run): {sm['wins_by_run']}")
        for rag, p in (sm.get("pairs") or {}).items():
            store.log(f"  wiki vs {rag}: wiki similarity {p['wiki']['similarity']['mean']}/10  standard-only coverage "
                      f"{p['wiki']['coverage_standard']['mean']}%  wins {p['wins_by_run']}")
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
