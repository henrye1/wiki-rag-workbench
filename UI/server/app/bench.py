"""Benchmark: runs are stored in bench.runs (results, log, uploaded inputs); new runs execute `python -m bench.run --run-id`
as subprocesses."""
import asyncio
import datetime as dt
import hashlib
import json
import os
import statistics
import subprocess
import tempfile
from typing import Literal
from urllib.parse import quote

import psycopg
from fastapi import APIRouter, Form, HTTPException, Response, UploadFile
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .config import get_settings
from .proxy import client

router = APIRouter(prefix="/api/bench", tags=["benchmark"])
_procs: dict[str, subprocess.Popen] = {}
STALE = dt.timedelta(minutes=2)  # bench.run heartbeats every 30 s; a 'running' row silent for longer was interrupted
MAX_UPLOAD = 20 * 1024 * 1024

# Judged-run count straight from the results JSON
DONE_SQL = """(select count(*) from jsonb_each(coalesce(results->'topics', '{}'::jsonb)) t,
                 jsonb_each(coalesce(t.value->'runs', '{}'::jsonb)) r where (r.value->>'judgement')::boolean is true)::int as done"""


def _query(sql: str, params: tuple = (), one: bool = False):
    def run():
        with psycopg.connect(get_settings().database_url, autocommit=True, row_factory=dict_row) as conn:
            cur = conn.execute(sql, params)
            if cur.description is None:
                return None
            return cur.fetchone() if one else cur.fetchall()
    return asyncio.to_thread(run)


# ---------- reference memos: shown by a neutral label, never by file name ----------

_ref_cache: dict = {}  # labels and masks, kept briefly: working them out hashes every stored memo
REF_TTL = dt.timedelta(minutes=15)  # cleared on rename, new ticks and new runs


def _ref_cache_clear():
    _ref_cache.clear()


async def _labels() -> dict[str, dict]:
    """sha256 -> {label, tag_sources} for every reference memo; a memo seen for the first time gets the next
    "Reference memo N"."""
    hit = _ref_cache.get("labels")
    if hit and dt.datetime.now() - hit[0] < REF_TTL:
        return hit[1]
    await _query(
        """insert into bench.references (reference_sha256, label, created_at)
           select sha, 'Reference memo ' || ((select count(*) from bench.references) + row_number() over (order by first_seen)), first_seen
           from (select encode(sha256(reference), 'hex') as sha, min(created_at) as first_seen from bench.runs
                 where reference is not null group by 1) s
           where sha not in (select reference_sha256 from bench.references)
           on conflict do nothing""")
    out = {r["reference_sha256"]: r for r in await _query("select reference_sha256, label, tag_sources from bench.references")}
    _ref_cache["labels"] = (dt.datetime.now(), out)
    return out


async def _masks() -> list[tuple[str, str]]:
    """(file name, label) for every name a memo was uploaded or saved under, longest first, with and without .docx."""
    hit = _ref_cache.get("masks")
    if hit and dt.datetime.now() - hit[0] < REF_TTL:
        return hit[1]
    labels = await _labels()
    rows = await _query("""select distinct encode(sha256(reference), 'hex') as sha, reference_name as name from bench.runs
                           where reference is not null and reference_name is not null
                           union select distinct reference_sha256, reference_name from bench.rubrics where reference_name is not null""")
    pairs = set()
    for r in rows:
        lab = (labels.get(r["sha"]) or {}).get("label") or "Reference memo"
        name = r["name"].strip()
        for n in {name, name.removesuffix(".docx").strip()}:
            if len(n) >= 4:
                pairs.add((n, lab))
    out = sorted(pairs, key=lambda p: -len(p[0]))
    _ref_cache["masks"] = (dt.datetime.now(), out)
    return out


async def _run_shas() -> dict[str, str]:
    """run id -> its memo's SHA-256 (cached with the labels)."""
    hit = _ref_cache.get("shas")
    if hit and dt.datetime.now() - hit[0] < REF_TTL:
        return hit[1]
    out = {r["id"]: r["sha"] for r in await _query(
        "select id, encode(sha256(reference), 'hex') as sha from bench.runs where reference is not null")}
    _ref_cache["shas"] = (dt.datetime.now(), out)
    return out


def _mask(obj, pairs: list[tuple[str, str]]):
    """The value with every memo file name replaced by its label (strings inside dicts and lists too)."""
    if isinstance(obj, str):
        for name, lab in pairs:
            if name in obj:
                obj = obj.replace(name, lab)
        return obj
    if isinstance(obj, dict):
        return {k: _mask(v, pairs) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask(v, pairs) for v in obj]
    return obj


async def db_ok() -> bool:
    try:
        await _query("select 1 from bench.runs limit 1")
        return True
    except Exception:
        return False


def _status(row: dict) -> str:
    proc = _procs.get(row["id"])
    if proc is not None and proc.poll() is None:
        return "running"
    if row["status"] in ("running", "queued"):
        local_dead = proc is not None  # started here and exited without recording an outcome
        stale = dt.datetime.now(dt.timezone.utc) - row["updated_at"] > STALE
        return "interrupted" if local_dead or stale else "running"  # still running elsewhere (e.g. CLI)
    return row["status"]


def _progress(row: dict, cfg: dict | None, errors: dict | None = None) -> dict:
    return {"done": row["done"], "expected": (cfg or {}).get("expected_judgements"), "status": _status(row), "errors": errors or {}}


@router.get("/runs")
async def list_runs():
    rows = await _query(
        f"""select id, status, updated_at, runs, topics, query_set_name, rag_collection, wiki_slug, sources, use_saved, mode, use_batch, {DONE_SQL},
                   results->'config' as config, results->'summary' as summary, results->'errors' as errors,
                   jsonb_array_length(coalesce(results->'config'->'topics_selected', '[]'::jsonb)) as n_topics
            from bench.runs order by created_at desc"""
    )
    out, labels, pairs, shas = [], await _labels(), await _masks(), await _run_shas()
    for r in rows:
        r["reference_sha"] = shas.get(r["id"])
        cfg = _mask(r["config"] or {}, pairs)
        out.append({
            "id": r["id"], "started": cfg.get("started"), "finished": cfg.get("finished"), "runs": cfg.get("runs") or r["runs"],
            "judge_model": cfg.get("judge_model"), "topics": r["n_topics"] or r["topics"] or "all",
            "query_set": r["query_set_name"], "reference": (labels.get(r["reference_sha"]) or {}).get("label"),
            "reference_sha256": r["reference_sha"],
            "rag_collection": r["rag_collection"], "wiki": r["wiki_slug"], "sources": r["sources"], "use_saved": r["use_saved"],
            "mode": r["mode"], "use_batch": r["use_batch"],
            "summary": r["summary"], "progress": _progress(r, cfg, _mask(r["errors"], pairs)),
            "rubric": _rubric_label(cfg), "judge": _judge_label(cfg),
        })
    return out


def _rubric_label(cfg: dict) -> dict:
    """Which rubric version(s) a run used, and how many of its topics were approved then."""
    used = [u for u in (cfg.get("rubric_used") or {}).values() if u]
    if not used:
        return {"label": "—", "title": "Run made before rubric versions were recorded"}
    vs = sorted({u.get("version") or 1 for u in used})
    approved = sum(1 for u in used if u.get("approved"))
    return {"label": f"v{vs[0]}" if len(vs) == 1 else f"v{vs[0]}–v{vs[-1]}",
            "title": f"{approved} of {len(used)} topics approved when the run used them", "approved": approved, "topics": len(used)}


def _judge_label(cfg: dict) -> dict:
    backend = cfg.get("judge_backend") or "Anthropic API"  # runs before the subscription option all used the API
    sub = "subscription" in backend.lower()
    return {"label": f"{cfg.get('judge_model') or '—'} · {'subscription' if sub else 'API'}", "title": backend}


async def _row(run_id: str, cols: str) -> dict:
    row = await _query(f"select id, status, updated_at, {DONE_SQL}, {cols} from bench.runs where id = %s", (run_id,), one=True)
    if not row:
        raise HTTPException(404, "Run not found")
    return row


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    row = await _row(run_id, "results, rag_collection, wiki_slug, sources, use_saved")
    row["reference_sha"] = (await _run_shas()).get(run_id)
    data = row["results"] or {}
    pairs = await _masks()
    for k in ("config", "errors", "summary"):
        if k in data:
            data[k] = _mask(data[k], pairs)
    data["reference_label"] = ((await _labels()).get(row["reference_sha"]) or {}).get("label")
    data["progress"] = _progress(row, data.get("config"), data.get("errors"))
    # what the run compared, from the run row (results of older runs do not record it)
    data["compared"] = {"rag_collection": row["rag_collection"], "wiki": row["wiki_slug"], "sources": row["sources"], "use_saved": row["use_saved"]}
    return data


@router.get("/runs/{run_id}/status")
async def status(run_id: str):
    row = await _row(run_id, "results->'config' as config, results->'errors' as errors, log")
    pairs = await _masks()
    return {**_progress(row, row["config"], _mask(row["errors"], pairs)), "log": _mask(row["log"].splitlines()[-15:], pairs)}


def _ensure_idle():
    if any(p.poll() is None for p in _procs.values()):
        raise HTTPException(409, "A benchmark run or rubric rebuild is already in progress")


def _spawn(run_id: str, args: list[str] | None = None):
    s = get_settings()
    _ensure_idle()
    py = s.bench_python_path()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "DATABASE_URL": s.database_url,
           "RAG_URL": s.rag_url, "RAG_API_KEY": s.rag_api_key, "WIKI_URL": s.wiki_url, "WIKI_API_KEY": s.wiki_api_key}
    # Output goes to this server's log; the run also keeps its own log in bench.runs
    _procs[run_id] = subprocess.Popen([str(py), "-m", *(args or ["bench.run", "--run-id", run_id])], cwd=s.bench_dir, env=env)


# ---------- before a run: the topics to choose from, and what the run will cost ----------

def _prices() -> dict:
    return json.loads((get_settings().bench_dir / "bench" / "prices.json").read_text())


async def _latest_inputs() -> dict | None:
    return await _query("""select query_set_name, query_set, reference_name, reference from bench.runs
                           where query_set is not null and reference is not null order by created_at desc limit 1""", one=True)


@router.get("/topics")
async def list_topics():
    """The topics of the query set and reference that a new run uses (the most recent run's)."""
    last = await _latest_inputs()
    if not last:
        return {"topics": [], "query_set": None}
    def parse():
        with tempfile.TemporaryDirectory() as tmp:
            q, r = os.path.join(tmp, "q.txt"), os.path.join(tmp, "r.docx")
            open(q, "wb").write(last["query_set"]); open(r, "wb").write(last["reference"])
            code = ("import json,sys,pathlib; from bench.data import load; "
                    "print(json.dumps([{'number': t.number, 'code': t.code, 'title': t.title, 'section': t.section} "
                    "for t in load(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]))]))")
            out = subprocess.run([str(get_settings().bench_python_path()), "-c", code, q, r], cwd=get_settings().bench_dir,
                                 capture_output=True, text=True, timeout=120)
        if out.returncode:
            raise HTTPException(500, f"Could not read the query set: {out.stderr.strip().splitlines()[-1:]}")
        return json.loads(out.stdout)
    label = ((await _labels()).get(hashlib.sha256(last["reference"]).hexdigest()) or {}).get("label")
    return {"topics": await asyncio.to_thread(parse), "query_set": last["query_set_name"], "reference": label}


def _answer_cost(usage: list, prices: dict) -> float | None:
    total = 0.0
    for u in usage:
        if u.get("step") == "embed":
            continue
        p = prices.get(u.get("model") or "")
        if not p or u.get("input_tokens") is None:
            return None
        total += u["input_tokens"] / 1e6 * p["input"] + ((u.get("output_tokens") or 0) + (u.get("thinking_tokens") or 0)) / 1e6 * p["output"]
    return total


def _judge_backend() -> str:
    """The benchmark's JUDGE_BACKEND (its environment, else Benchmark/.env): api, or claude-code (the Claude subscription)."""
    v = os.environ.get("JUDGE_BACKEND")
    if v is None:
        try:
            for line in (get_settings().bench_dir / ".env").read_text(encoding="utf-8").splitlines():
                k, _, val = line.partition("=")
                if k.strip() == "JUDGE_BACKEND":
                    v = val.strip()
        except OSError:
            pass
    return "claude-code" if (v or "").strip().lower() == "claude-code" else "api"


@router.get("/judge")
async def judge_info():
    """Which judge grades new runs; Message Batches exist only on the API."""
    b = _judge_backend()
    return {"backend": b, "label": "Claude subscription (Claude Code)" if b == "claude-code" else "Anthropic API", "batch_available": b == "api"}


SUBSCRIPTION = "on your Claude subscription: no API charge, counts toward the plan's usage limits"


@router.get("/estimate")
async def estimate(topics: str = "", runs: int = 2, mode: str = "quick", use_batch: bool = True, collection: str = "", wiki: str = ""):
    """What a run is expected to cost, from recorded token use and the price list only: an item with no basis yet is
    reported as such, never guessed."""
    prices, s = _prices(), get_settings()
    sub = _judge_backend() == "claude-code"
    use_batch = use_batch and not sub
    all_topics = (await list_topics())["topics"]
    wanted = set(range(1, len(all_topics) + 1))
    if topics.strip():
        wanted = set()
        for part in topics.replace(" ", "").split(","):
            a, _, b = part.partition("-")
            wanted.update(range(int(a), int(b or a) + 1))
    n = len(wanted & {t["number"] for t in all_topics})
    rows = await _query("""select id, wiki_slug, rag_collection, results->'topics' as topics from bench.runs
                           where results is not null order by created_at desc limit 20""")
    answers = {"rag": {"same": [], "other": []}, "wiki": {"same": [], "other": []}}
    context = {"rag": {"same": [], "other": []}, "wiki": {"same": [], "other": []}}  # tokens the answer's own call read and wrote
    judge_usage, kp_usage, check_usage = [], [], []
    for r in rows:
        for t in (r["topics"] or {}).values():
            if t.get("key_points_usage"):
                kp_usage.append(t["key_points_usage"])
            for run in (t.get("runs") or {}).values():
                if run.get("orders"):  # both orders: each order's own grading
                    judge_usage += [o["judge_usage"] for o in run["orders"].values() if not o.get("batch")]
                elif run.get("judge_usage") and not run.get("judge_batch"):
                    judge_usage.append(run["judge_usage"])
                for sysname, a in (run.get("systems") or run.get("answers") or {}).items():
                    ck = a.get("checks") or {}
                    if ck.get("usage") and not ck.get("batch") and ck.get("backend") != "claude-code":
                        check_usage.append((ck["model"], ck["usage"]))
                    if a.get("usage") is not None and (c := _answer_cost(a["usage"], prices)) is not None:
                        same = (r["wiki_slug"] == wiki) if sysname == "wiki" else (r["rag_collection"] == collection)
                        answers.setdefault(sysname, {"same": [], "other": []})["same" if same else "other"].append(c)
                        call = next((u for u in a["usage"] if u.get("step") == "answer"), None)
                        if call and call.get("input_tokens") is not None:
                            context.setdefault(sysname, {"same": [], "other": []})["same" if same else "other"].append(
                                call["input_tokens"] + (call.get("output_tokens") or 0))
    jm = prices.get("claude-opus-5-5")  # the grading model (bench JUDGE_MODEL)
    items = []
    for sysname, label in (("rag", f"RAG answers ({collection or 'collection'})"), ("wiki", f"Wiki answers ({wiki or 'wiki'})")):
        pool = answers[sysname]["same"] or answers[sysname]["other"]
        basis = (f"mean of {len(pool)} recorded answer(s) of this {'collection' if sysname == 'rag' else 'wiki'}" if answers[sysname]["same"]
                 else f"mean of {len(pool)} recorded answer(s) of another {'collection' if sysname == 'rag' else 'wiki'}" if pool else None)
        unit = statistics.mean(pool) if pool else None
        items.append({"item": label, "count": n * runs, "unit_usd": unit, "total_usd": unit * n * runs if unit is not None else None,
                      "basis": basis or "no answer with recorded tokens yet: cannot estimate until a run has recorded some"})
    if sub:
        items.append({"item": "Grading, both orders (Claude Opus 5.5)", "count": n * runs * 2, "unit_usd": 0, "total_usd": 0,
                      "basis": SUBSCRIPTION})
    elif judge_usage and jm:
        unit = statistics.mean(u["input_tokens"] / 1e6 * jm["input"] + u["output_tokens"] / 1e6 * jm["output"] for u in judge_usage)
        if use_batch:
            unit *= prices.get("batch_discount", 1)
        # each answer pair is graded twice (A-then-B and B-then-A)
        items.append({"item": "Grading, both orders (Claude Opus 5.5" + (", Message Batches: half price)" if use_batch else ")"),
                      "count": n * runs * 2, "unit_usd": unit, "total_usd": unit * n * runs * 2,
                      "basis": f"mean of {len(judge_usage)} recorded grading(s)"})
    else:
        items.append({"item": "Grading, both orders", "count": n * runs * 2, "unit_usd": None, "total_usd": None, "basis": "no recorded grading yet"})
    last = await _latest_inputs()
    if last:
        sha = hashlib.sha256(last["reference"]).hexdigest()
        saved = {r["topic_number"] for r in await _query("select topic_number from bench.rubrics where reference_sha256 = %s", (sha,))}
        missing = len((wanted & {t["number"] for t in all_topics}) - saved)
        if missing and sub:
            items.append({"item": "Key points for topics without a saved rubric", "count": missing, "unit_usd": 0, "total_usd": 0,
                          "basis": SUBSCRIPTION})
        elif missing and kp_usage and jm:
            unit = statistics.mean(u["input_tokens"] / 1e6 * jm["input"] + u["output_tokens"] / 1e6 * jm["output"] for u in kp_usage)
            items.append({"item": "Key points for topics without a saved rubric", "count": missing, "unit_usd": unit,
                          "total_usd": unit * missing, "basis": f"mean of {len(kp_usage)} recorded key-point call(s)"})
        elif not missing:
            items.append({"item": "Key points", "count": 0, "unit_usd": 0, "total_usd": 0, "basis": "the saved rubric is reused"})
    label = "Answer checks: completeness, exact match, citation accuracy (Claude Sonnet 5.5, one call per answer)"
    priced = [u["input_tokens"] / 1e6 * prices[m]["input"] + u["output_tokens"] / 1e6 * prices[m]["output"]
              for m, u in check_usage if m in prices]
    if sub:
        items.append({"item": label, "count": n * runs * 2, "unit_usd": 0, "total_usd": 0, "basis": SUBSCRIPTION})
    elif priced:
        unit = statistics.mean(priced) * (prices.get("batch_discount", 1) if use_batch else 1)
        items.append({"item": label + (", batch" if use_batch else ""), "count": n * runs * 2, "unit_usd": unit,
                      "total_usd": unit * n * runs * 2, "basis": f"mean of {len(priced)} recorded answer check(s)"})
    else:
        items.append({"item": label, "count": n * runs * 2, "unit_usd": None, "total_usd": None,
                      "basis": "no answer check recorded through the API yet"})
    if mode == "full":
        # faithfulness + context recall: one Sonnet call per answer that reads what the answer read. Its input is taken as the
        # tokens the answer's own call read and wrote (recorded); its output as a grading's recorded output per answer.
        cm = prices.get("claude-sonnet-5-5")
        out_per_answer = statistics.mean(u["output_tokens"] for u in judge_usage) / 2 if judge_usage else None
        for sysname, label in (("rag", "RAG"), ("wiki", "Wiki")):
            pool = context[sysname]["same"] or context[sysname]["other"]
            if sub:
                items.append({"item": f"Faithfulness + context recall, {label} answers", "count": n * runs, "unit_usd": 0,
                              "total_usd": 0, "basis": SUBSCRIPTION})
            elif pool and out_per_answer is not None and cm:
                unit = statistics.mean(pool) / 1e6 * cm["input"] + out_per_answer / 1e6 * cm["output"]
                if use_batch:
                    unit *= prices.get("batch_discount", 1)
                items.append({"item": f"Faithfulness + context recall, {label} answers (Claude Sonnet 5.5{', batch' if use_batch else ''})",
                              "count": n * runs, "unit_usd": unit, "total_usd": unit * n * runs,
                              "basis": f"input: mean context of {len(pool)} recorded answer(s) ({statistics.mean(pool):,.0f} tokens); "
                                       f"output: half a recorded grading ({out_per_answer:,.0f} tokens)"})
            else:
                items.append({"item": f"Faithfulness + context recall, {label} answers", "count": n * runs, "unit_usd": None,
                              "total_usd": None, "basis": "no answer with recorded tokens yet"})
    known = [i["total_usd"] for i in items if i["total_usd"] is not None]
    unknown = [i["item"] for i in items if i["total_usd"] is None]
    return {"topics": n, "runs": runs, "mode": mode, "use_batch": use_batch, "items": items, "judge_backend": "claude-code" if sub else "api",
            "total_usd": round(sum(known), 2), "complete": not unknown, "not_estimated": unknown,
            "note": "Estimated from recorded token use and the price list (Benchmark/bench/prices.json); actual cost depends on answer length."}


@router.get("/rubrics")
async def list_rubrics():
    """Saved rubrics (key points built once per reference file and reused by every run), newest first."""
    rows = await _query(
        """select reference_sha256, count(*) as topics,
                  sum(jsonb_array_length(key_points)) as key_points,
                  sum((select count(*) from jsonb_array_elements(key_points) k where k->>'kind' = 'standard')) as standard,
                  count(reviewed_at) as approved, count(facts_reviewed_at) as facts_approved, count(facts) as facts_made,
                  min(created_at) as built, max(created_at) as updated
           from bench.rubrics group by reference_sha256 order by max(created_at) desc"""
    )
    labels = await _labels()
    for r in rows:
        r["reference_name"] = (labels.get(r["reference_sha256"]) or {}).get("label") or "Reference memo"
        p = _procs.get(f"rubric-{r['reference_sha256']}")
        r["rebuilding"] = bool(p and p.poll() is None)
        r["making_facts"] = _making_facts(r["reference_sha256"])
        r["suggesting"] = _running(f"suggest-{r['reference_sha256']}")
    return rows


def _making_facts(ref_sha: str) -> bool:
    p = _procs.get(f"facts-{ref_sha}")
    return bool(p and p.poll() is None)


TAGS = ("standard", "supporting", "beyond_standard")


@router.get("/rubrics/{ref_sha}")
async def get_rubric(ref_sha: str):
    """Every topic's key points and exact-match facts, with their version and approval, for the review screen."""
    rows = await _query(
        """select topic_number, topic_title, key_points, facts, version, reviewed_at, facts_reviewed_at, created_at, suggestions, tag_sources
           from bench.rubrics where reference_sha256 = %s order by topic_number""", (ref_sha,))
    if not rows:
        raise HTTPException(404, "No saved rubric for this reference file")
    ref = (await _labels()).get(ref_sha) or {}
    return {"reference_sha256": ref_sha, "reference_name": ref.get("label") or "Reference memo", "label": ref.get("label"),
            "tag_sources": ref.get("tag_sources"), "documents": await _documents(), "tags": TAGS, "topics": rows,
            "making_facts": _making_facts(ref_sha), "suggesting": _running(f"suggest-{ref_sha}")}


def _running(key: str) -> bool:
    p = _procs.get(key)
    return bool(p and p.poll() is None)


async def _documents() -> list[dict]:
    """Every source document the wikis keep, for ticking which ones the rubric tag check uses."""
    def run():
        import re
        with psycopg.connect(get_settings().database_url, row_factory=dict_row) as c:
            rows = c.execute("""select distinct on (slug) slug, title, meta->>'parser' as parser, meta->>'title' as pdf_title
                                from wiki.sources order by slug, length(text) desc""").fetchall()
        out = []
        for r in rows:
            std = re.search(r"\b(IFRS|IAS|IFRIC|SIC)\s*(\d+)", r["title"] or "")
            part = re.search(r"BB\d{4}-([ABC])\b", r["pdf_title"] or "")
            name = (f"{std.group(1)} {std.group(2)}" if std else r["title"]) + (f" Part {part.group(1)}" if part else "")
            tier = "supporting" if r["parser"] == "ifrs_accompanying" else "standard" if r["parser"] == "ifrs" else "other"
            out.append({"slug": r["slug"], "name": name, "tier": tier, "title": r["title"]})
        return out
    return await asyncio.to_thread(run)


class ReferenceIn(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=80)
    tag_sources: list[str] | None = Field(None, description="Source slugs the next Suggest changes checks tags against")


@router.put("/references/{ref_sha}")
async def update_reference(ref_sha: str, body: ReferenceIn):
    """Rename a reference memo, or save which source documents the rubric tag check uses. The ticks take effect on the
    next Suggest changes; nothing in the rubric changes until you accept its suggestions and approve."""
    labels = await _labels()
    if ref_sha not in labels:
        raise HTTPException(404, "Unknown reference memo")
    if body.tag_sources is not None:
        known = {d["slug"] for d in await _documents()}
        if not body.tag_sources or (bad := [s for s in body.tag_sources if s not in known]):
            raise HTTPException(422, "Tick at least one existing source document" if not body.tag_sources else f"Unknown document(s): {', '.join(bad)}")
    _ref_cache_clear()
    if body.label is not None:
        if any(r["label"] == body.label.strip() and k != ref_sha for k, r in labels.items()):
            raise HTTPException(409, "Another reference memo already has that label")
        await _query("update bench.references set label = %s where reference_sha256 = %s", (body.label.strip(), ref_sha))
    if body.tag_sources is not None:
        await _query("update bench.references set tag_sources = %s where reference_sha256 = %s", (Jsonb(sorted(body.tag_sources)), ref_sha))
    _ref_cache_clear()
    return (await _labels())[ref_sha]


class SuggestIn(BaseModel):
    topics: str = Field("", description="e.g. 1,5 (empty = every topic)")


@router.post("/rubrics/{ref_sha}/suggest", status_code=202)
async def suggest_changes(ref_sha: str, body: SuggestIn):
    """Have the judge suggest tags (with the backing paragraph from the original source texts), list merges and a hard-fact
    list for each topic. Nothing in the rubric changes until you accept the suggestions and save."""
    if not await _query("select 1 from bench.rubrics where reference_sha256 = %s limit 1", (ref_sha,), one=True):
        raise HTTPException(404, "No saved rubric for this reference file")
    _spawn(f"suggest-{ref_sha}", ["bench.suggest", ref_sha] + ([body.topics.replace(" ", "")] if body.topics.strip() else []))
    return {"reference_sha256": ref_sha, "suggesting": True}


@router.post("/rubrics/{ref_sha}/facts", status_code=202)
async def make_facts(ref_sha: str):
    """Have the judge make the exact-match fact lists this rubric is still missing (from each topic's reference answer)."""
    if not await _query("select 1 from bench.rubrics where reference_sha256 = %s and facts is null limit 1", (ref_sha,), one=True):
        raise HTTPException(409, "Every topic of this rubric already has a fact list")
    _spawn(f"facts-{ref_sha}", ["bench.checks", "facts", ref_sha])
    return {"reference_sha256": ref_sha, "making_facts": True}


@router.get("/rubrics/{ref_sha}/export.docx")
async def export_rubric(ref_sha: str, topic: int = 0, tag: str = "", unreviewed: bool = False, suggestions: bool = False):
    """The saved rubric as a Word document laid out like the review screen, with the screen's filters (topic, tag,
    not yet reviewed). Unsaved edits on the screen are not in it."""
    from .rubric_export import TAG_LABEL, build
    rub = await get_rubric(ref_sha)
    rows = rub["topics"]
    counts = (len(rows), sum(1 for r in rows if r["reviewed_at"]), sum(1 for r in rows if r["facts_reviewed_at"]))
    shown = [r for r in rows if (not topic or r["topic_number"] == topic) and (not unreviewed or not r["reviewed_at"] or (r["facts"] is not None and not r["facts_reviewed_at"]))]
    for r in shown:
        r["points"] = [p for p in r["key_points"] or [] if not tag or p.get("kind") == tag]
    filters = ", ".join(x for x in (f"topic {topic}" if topic else "", f"tag {TAG_LABEL.get(tag, tag)}" if tag else "",
                                     "not yet reviewed only" if unreviewed else "") if x)
    names = {d["slug"]: d["name"] for d in rub["documents"]}
    ticked = [names.get(s, s) for s in rub["tag_sources"]] if rub["tag_sources"] is not None else [d["name"] for d in rub["documents"]]
    data = await asyncio.to_thread(build, rub["reference_name"], ref_sha, shown, filters, counts, suggestions, ticked)
    name = f"Rubric - {rub['reference_name']}{' - suggestions' if suggestions else ''}.docx".replace("/", "-")
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


class KeyPoint(BaseModel):
    id: str = Field(min_length=1, max_length=12)
    point: str = Field(min_length=1)
    kind: str
    ref: str | None = None  # the paragraph that backs the tag, e.g. "5.5.5 (IFRS 9 Part A)"


class Fact(BaseModel):
    id: str = Field(min_length=1, max_length=12)
    fact: str = Field(min_length=1)
    kind: str | None = None
    ref: str | None = None


class TopicReview(BaseModel):
    key_points: list[KeyPoint] = Field(min_length=1)
    facts: list[Fact] | None = None
    approve_points: bool = False
    approve_facts: bool = False
    decisions: dict[str, Literal["accepted", "rejected"]] = Field(
        default_factory=dict, description='Your answer to each suggestion: "point:K1", "merge:0", "facts"')


@router.put("/rubrics/{ref_sha}/topics/{n}")
async def review_topic(ref_sha: str, n: int, body: TopicReview):
    """Save a topic's reviewed key points (tag, wording, deletions) and/or facts. A change makes a new version (the old one
    is kept); approving stamps the time. Every run after this uses the saved version and records it."""
    cur = await _query("select * from bench.rubrics where reference_sha256 = %s and topic_number = %s", (ref_sha, n), one=True)
    if not cur:
        raise HTTPException(404, "Topic not in this rubric")
    if bad := [p.id for p in body.key_points if p.kind not in TAGS]:
        raise HTTPException(422, f"Unknown tag on {', '.join(bad)}: use {', '.join(TAGS)}")
    if bad := [f.id for f in body.facts or [] if f.kind is not None and f.kind not in TAGS]:
        raise HTTPException(422, f"Unknown tag on {', '.join(bad)}: use {', '.join(TAGS)}")
    if len({p.id for p in body.key_points}) != len(body.key_points):
        raise HTTPException(422, "Key point ids must be unique")
    points = [{k: v for k, v in p.model_dump().items() if v is not None} for p in body.key_points]
    facts = [{k: v for k, v in f.model_dump().items() if v is not None} for f in body.facts] if body.facts is not None else cur["facts"]
    sug = cur.get("suggestions")
    if sug and body.decisions:  # record your answer to each suggestion, so it is not offered again
        for key, d in body.decisions.items():
            kind, _, ref = key.partition(":")
            if kind == "point" and ref in sug.get("points", {}):
                sug["points"][ref]["status"] = d
            elif kind == "merge" and ref.isdigit() and int(ref) < len(sug.get("merges", [])):
                sug["merges"][int(ref)]["status"] = d
            elif kind == "facts" and sug.get("facts"):
                sug["facts"]["status"] = d
    # acting on suggestions records the documents they were checked against with this version
    tag_sources = cur.get("tag_sources")
    if sug and body.decisions and sug.get("documents") is not None:
        tag_sources = sug["documents"]
    changed = points != cur["key_points"] or facts != cur["facts"] or tag_sources != cur.get("tag_sources")
    row = await _query(
        """update bench.rubrics set key_points = %s, facts = %s, suggestions = %s, tag_sources = %s,
                  version = version + %s,
                  reviewed_at = case when %s then now() when %s then null else reviewed_at end,
                  facts_reviewed_at = case when %s then now() when %s then null else facts_reviewed_at end
           where reference_sha256 = %s and topic_number = %s
           returning topic_number, topic_title, key_points, facts, version, reviewed_at, facts_reviewed_at, suggestions, tag_sources""",
        (Jsonb(points), Jsonb(facts) if facts is not None else None, Jsonb(sug) if sug else None,
         Jsonb(tag_sources) if tag_sources is not None else None, 1 if changed else 0,
         body.approve_points, changed and points != cur["key_points"],
         body.approve_facts, changed and facts != cur["facts"], ref_sha, n), one=True)
    await _query(
        """insert into bench.rubric_versions (reference_sha256, topic_number, version, key_points, facts, reviewed_at, facts_reviewed_at,
                                             note, tag_sources)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (reference_sha256, topic_number, version) do update set reviewed_at = excluded.reviewed_at,
               facts_reviewed_at = excluded.facts_reviewed_at, tag_sources = excluded.tag_sources""",
        (ref_sha, n, row["version"], Jsonb(row["key_points"]), Jsonb(row["facts"]) if row["facts"] is not None else None,
         row["reviewed_at"], row["facts_reviewed_at"], "reviewed", Jsonb(row["tag_sources"]) if row["tag_sources"] is not None else None))
    return row


@router.post("/rubrics/{ref_sha}/rebuild", status_code=202)
async def rebuild_rubric(ref_sha: str):
    """Build the rubric for this reference file again (same judge prompt) and replace the saved one."""
    if not await _query("select 1 from bench.rubrics where reference_sha256 = %s limit 1", (ref_sha,), one=True):
        raise HTTPException(404, "No saved rubric for this reference file")
    _spawn(f"rubric-{ref_sha}", ["bench.rubric", "rebuild", ref_sha])
    return {"reference_sha256": ref_sha, "rebuilding": True}


async def _read(f: UploadFile | None, ext: str) -> tuple[str, bytes] | None:
    if f is None or not f.filename:
        return None
    if not f.filename.lower().endswith(ext):
        raise HTTPException(400, f"{f.filename}: expected a {ext} file")
    data = await f.read()
    if not data or len(data) > MAX_UPLOAD:
        raise HTTPException(400, f"{f.filename}: empty or larger than 20 MB")
    return f.filename, data


async def _ensure_wiki(slug: str):
    """Refuse a run up front when the wiki does not exist, instead of failing on every topic."""
    s = get_settings()
    if not slug:
        raise HTTPException(400, "Choose the wiki to benchmark")
    r = await client().get(f"{s.wiki_url}/wikis/{quote(slug, safe='')}", headers={"X-API-Key": s.wiki_api_key}, timeout=15)
    if r.status_code == 404:
        raise HTTPException(400, f"No wiki with slug '{slug}'")
    r.raise_for_status()


async def _ensure_collection(slug: str):
    """Refuse a run up front when the RAG collection does not exist."""
    s = get_settings()
    if not slug:
        raise HTTPException(400, "Choose the RAG collection to benchmark")
    r = await client().get(f"{s.rag_url}/collections/{quote(slug, safe='')}/documents", headers={"X-API-Key": s.rag_api_key}, timeout=15)
    if r.status_code == 404:
        raise HTTPException(400, f"No RAG collection with slug '{slug}'")
    r.raise_for_status()
    if not r.json():
        raise HTTPException(400, f"RAG collection '{slug}' has no documents")


def _numbers(spec: str) -> set[int]:
    out = set()
    for part in spec.replace(" ", "").split(","):
        if part:
            a, _, b = part.partition("-")
            out.update(range(int(a), int(b or a) + 1))
    return out


async def _ensure_approved(ref_sha: str, topics: str):
    """Full runs use an approved rubric only: every chosen topic's key points and fact list approved."""
    rows = await _query("select topic_number, reviewed_at, facts, facts_reviewed_at from bench.rubrics where reference_sha256 = %s", (ref_sha,))
    if not rows:
        raise HTTPException(400, "Full runs need an approved rubric, and this reference file has none yet: run it in Quick mode "
                                 "first to build the rubric, then approve it on the Rubric review screen")
    by = {r["topic_number"]: r for r in rows}
    wanted = _numbers(topics) or set(by)
    bad = sorted(n for n in wanted if n not in by or not by[n]["reviewed_at"] or by[n]["facts"] is None or not by[n]["facts_reviewed_at"])
    if bad:
        raise HTTPException(400, "Full runs need an approved rubric. Approve the key points and the fact list of topic(s) "
                                 f"{', '.join(map(str, bad))} on the Rubric review screen, or run in Quick mode")


@router.post("/runs", status_code=202)
async def start(
    reference: UploadFile | None = None,
    query_set: UploadFile | None = None,
    topics: str = Form("", description="e.g. 1,2,5-7 (empty = all)"),
    runs: int = Form(2, ge=1, le=10),
    collection: str = Form(..., description="RAG collection under test"),
    wiki: str = Form(..., description="Wiki slug under test"),
    sources: Literal["standard", "all"] = Form(..., description="Both systems use the same: standard = Part A only; all = Parts A, B and C"),
    use_saved: bool = Form(True, description="The wiki also reads relevant saved answers (synthesis pages filed with Save)"),
    mode: Literal["quick", "full"] = Form("quick", description="quick: answers, grading and the answer checks; full: also faithfulness and context recall"),
    use_batch: bool = Form(True, description="Grade through the Message Batches API (half price; slower), normal API for the rest"),
):
    """Start a run comparing one RAG collection with one wiki. Files left out are reused from the most recent run that has them."""
    _ensure_idle()
    use_batch = use_batch and _judge_backend() == "api"  # batches are an API feature; the subscription judge grades normally
    collection, wiki = collection.strip(), wiki.strip()
    await _ensure_collection(collection)
    await _ensure_wiki(wiki)
    ref, qs = await _read(reference, ".docx"), await _read(query_set, ".txt")
    if ref is None:
        last = await _query("select reference_name, reference from bench.runs where reference is not null order by created_at desc limit 1", one=True)
        ref = (last["reference_name"], last["reference"]) if last else None
    if qs is None:
        last = await _query("select query_set_name, query_set from bench.runs where query_set is not null order by created_at desc limit 1", one=True)
        qs = (last["query_set_name"], last["query_set"]) if last else None
    if ref is None or qs is None:
        raise HTTPException(400, "Upload the reference assessment (.docx) and the query set (.txt) for the first run")
    if mode == "full":
        await _ensure_approved(hashlib.sha256(ref[1]).hexdigest(), topics)
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    await _query(
        """insert into bench.runs (id, topics, runs, rag_collection, wiki_slug, sources, use_saved, mode, use_batch, query_set_name, query_set,
                                  reference_name, reference)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (run_id, topics.replace(" ", ""), runs, collection, wiki, sources, use_saved, mode, use_batch, qs[0], qs[1], ref[0], ref[1]),
    )
    _ref_cache_clear()  # a new memo gets its label
    _spawn(run_id)
    return {"id": run_id}


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume(run_id: str):
    row = await _row(run_id, "query_set is not null and reference is not null as has_inputs")
    if not row["has_inputs"]:
        raise HTTPException(400, "This run has no stored inputs (imported run); start a new run instead")
    if _status(row) == "running":
        raise HTTPException(409, "Run is still running")
    _ref_cache_clear()  # a new memo gets its label
    _spawn(run_id)
    return {"id": run_id}


@router.delete("/runs/{run_id}", status_code=204)
async def delete(run_id: str):
    row = await _row(run_id, "1 as x")
    if _status(row) == "running":
        raise HTTPException(409, "Run is still running")
    await _query("delete from bench.runs where id = %s", (run_id,))
