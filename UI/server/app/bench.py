"""Benchmark: runs are stored in bench.runs (results, log, uploaded inputs); new runs execute `python -m bench.run --run-id`
as subprocesses."""
import asyncio
import datetime as dt
import os
import subprocess
from typing import Literal
from urllib.parse import quote

import psycopg
from fastapi import APIRouter, Form, HTTPException, UploadFile
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
        f"""select id, status, updated_at, runs, topics, query_set_name, reference_name, rag_collection, wiki_slug, sources, use_saved, {DONE_SQL},
                   results->'config' as config, results->'summary' as summary, results->'errors' as errors,
                   jsonb_array_length(coalesce(results->'config'->'topics_selected', '[]'::jsonb)) as n_topics
            from bench.runs order by created_at desc"""
    )
    out = []
    for r in rows:
        cfg = r["config"] or {}
        out.append({
            "id": r["id"], "started": cfg.get("started"), "finished": cfg.get("finished"), "runs": cfg.get("runs") or r["runs"],
            "judge_model": cfg.get("judge_model"), "topics": r["n_topics"] or r["topics"] or "all",
            "query_set": r["query_set_name"], "reference": r["reference_name"],
            "rag_collection": r["rag_collection"], "wiki": r["wiki_slug"], "sources": r["sources"], "use_saved": r["use_saved"],
            "summary": r["summary"], "progress": _progress(r, cfg, r["errors"]),
        })
    return out


async def _row(run_id: str, cols: str) -> dict:
    row = await _query(f"select id, status, updated_at, {DONE_SQL}, {cols} from bench.runs where id = %s", (run_id,), one=True)
    if not row:
        raise HTTPException(404, "Run not found")
    return row


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    row = await _row(run_id, "results, rag_collection, wiki_slug, sources, use_saved")
    data = row["results"] or {}
    data["progress"] = _progress(row, data.get("config"), data.get("errors"))
    # what the run compared, from the run row (results of older runs do not record it)
    data["compared"] = {"rag_collection": row["rag_collection"], "wiki": row["wiki_slug"], "sources": row["sources"], "use_saved": row["use_saved"]}
    return data


@router.get("/runs/{run_id}/status")
async def status(run_id: str):
    row = await _row(run_id, "results->'config' as config, results->'errors' as errors, log")
    return {**_progress(row, row["config"], row["errors"]), "log": row["log"].splitlines()[-15:]}


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


@router.get("/rubrics")
async def list_rubrics():
    """Saved rubrics (key points built once per reference file and reused by every run), newest first."""
    rows = await _query(
        """select reference_sha256, max(reference_name) as reference_name, count(*) as topics,
                  sum(jsonb_array_length(key_points)) as key_points,
                  sum((select count(*) from jsonb_array_elements(key_points) k where k->>'kind' = 'standard')) as standard,
                  count(reviewed_at) as approved, count(facts_reviewed_at) as facts_approved,
                  min(created_at) as built, max(created_at) as updated
           from bench.rubrics group by reference_sha256 order by max(created_at) desc"""
    )
    for r in rows:
        p = _procs.get(f"rubric-{r['reference_sha256']}")
        r["rebuilding"] = bool(p and p.poll() is None)
    return rows


TAGS = ("standard", "supporting", "beyond_standard")


@router.get("/rubrics/{ref_sha}")
async def get_rubric(ref_sha: str):
    """Every topic's key points and exact-match facts, with their version and approval, for the review screen."""
    rows = await _query(
        """select topic_number, topic_title, reference_name, key_points, facts, version, reviewed_at, facts_reviewed_at, created_at
           from bench.rubrics where reference_sha256 = %s order by topic_number""", (ref_sha,))
    if not rows:
        raise HTTPException(404, "No saved rubric for this reference file")
    return {"reference_sha256": ref_sha, "reference_name": rows[0]["reference_name"], "tags": TAGS, "topics": rows}


class KeyPoint(BaseModel):
    id: str = Field(min_length=1, max_length=12)
    point: str = Field(min_length=1)
    kind: str


class Fact(BaseModel):
    id: str = Field(min_length=1, max_length=12)
    fact: str = Field(min_length=1)


class TopicReview(BaseModel):
    key_points: list[KeyPoint] = Field(min_length=1)
    facts: list[Fact] | None = None
    approve_points: bool = False
    approve_facts: bool = False


@router.put("/rubrics/{ref_sha}/topics/{n}")
async def review_topic(ref_sha: str, n: int, body: TopicReview):
    """Save a topic's reviewed key points (tag, wording, deletions) and/or facts. A change makes a new version (the old one
    is kept); approving stamps the time. Every run after this uses the saved version and records it."""
    cur = await _query("select * from bench.rubrics where reference_sha256 = %s and topic_number = %s", (ref_sha, n), one=True)
    if not cur:
        raise HTTPException(404, "Topic not in this rubric")
    if bad := [p.id for p in body.key_points if p.kind not in TAGS]:
        raise HTTPException(422, f"Unknown tag on {', '.join(bad)}: use {', '.join(TAGS)}")
    if len({p.id for p in body.key_points}) != len(body.key_points):
        raise HTTPException(422, "Key point ids must be unique")
    points = [p.model_dump() for p in body.key_points]
    facts = [f.model_dump() for f in body.facts] if body.facts is not None else cur["facts"]
    changed = points != cur["key_points"] or facts != cur["facts"]
    row = await _query(
        """update bench.rubrics set key_points = %s, facts = %s,
                  version = version + %s,
                  reviewed_at = case when %s then now() when %s then null else reviewed_at end,
                  facts_reviewed_at = case when %s then now() when %s then null else facts_reviewed_at end
           where reference_sha256 = %s and topic_number = %s
           returning topic_number, topic_title, key_points, facts, version, reviewed_at, facts_reviewed_at""",
        (Jsonb(points), Jsonb(facts) if facts is not None else None, 1 if changed else 0,
         body.approve_points, changed and points != cur["key_points"],
         body.approve_facts, changed and facts != cur["facts"], ref_sha, n), one=True)
    await _query(
        """insert into bench.rubric_versions (reference_sha256, topic_number, version, key_points, facts, reviewed_at, facts_reviewed_at, note)
           values (%s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (reference_sha256, topic_number, version) do update set reviewed_at = excluded.reviewed_at,
               facts_reviewed_at = excluded.facts_reviewed_at""",
        (ref_sha, n, row["version"], Jsonb(row["key_points"]), Jsonb(row["facts"]) if row["facts"] is not None else None,
         row["reviewed_at"], row["facts_reviewed_at"], "reviewed"))
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
):
    """Start a run comparing one RAG collection with one wiki. Files left out are reused from the most recent run that has them."""
    _ensure_idle()
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
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    await _query(
        """insert into bench.runs (id, topics, runs, rag_collection, wiki_slug, sources, use_saved, query_set_name, query_set, reference_name, reference)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (run_id, topics.replace(" ", ""), runs, collection, wiki, sources, use_saved, qs[0], qs[1], ref[0], ref[1]),
    )
    _spawn(run_id)
    return {"id": run_id}


@router.post("/runs/{run_id}/resume", status_code=202)
async def resume(run_id: str):
    row = await _row(run_id, "query_set is not null and reference is not null as has_inputs")
    if not row["has_inputs"]:
        raise HTTPException(400, "This run has no stored inputs (imported run); start a new run instead")
    if _status(row) == "running":
        raise HTTPException(409, "Run is still running")
    _spawn(run_id)
    return {"id": run_id}


@router.delete("/runs/{run_id}", status_code=204)
async def delete(run_id: str):
    row = await _row(run_id, "1 as x")
    if _status(row) == "running":
        raise HTTPException(409, "Run is still running")
    await _query("delete from bench.runs where id = %s", (run_id,))
