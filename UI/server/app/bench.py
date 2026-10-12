"""Benchmark: runs are stored in bench.runs (results, log, uploaded inputs); new runs execute `python -m bench.run --run-id`
as subprocesses."""
import asyncio
import datetime as dt
import os
import subprocess

import psycopg
from fastapi import APIRouter, Form, HTTPException, UploadFile
from psycopg.rows import dict_row

from .config import get_settings

router = APIRouter(prefix="/api/bench", tags=["benchmark"])
_procs: dict[str, subprocess.Popen] = {}
STALE = dt.timedelta(minutes=2)  # bench.run heartbeats every 30 s; a 'running' row silent for longer was interrupted
MAX_UPLOAD = 20 * 1024 * 1024

# Judged-run count straight from the results JSON
DONE_SQL = """(select count(*) from jsonb_each(coalesce(results->'topics', '{}'::jsonb)) t,
                 jsonb_each(coalesce(t.value->'runs', '{}'::jsonb)) r where r.value ? 'judgement')::int as done"""


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
        f"""select id, status, updated_at, runs, topics, query_set_name, reference_name, {DONE_SQL},
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
    row = await _row(run_id, "results")
    data = row["results"] or {}
    data["progress"] = _progress(row, data.get("config"), data.get("errors"))
    return data


@router.get("/runs/{run_id}/status")
async def status(run_id: str):
    row = await _row(run_id, "results->'config' as config, results->'errors' as errors, log")
    return {**_progress(row, row["config"], row["errors"]), "log": row["log"].splitlines()[-15:]}


def _ensure_idle():
    if any(p.poll() is None for p in _procs.values()):
        raise HTTPException(409, "A benchmark run is already in progress")


def _spawn(run_id: str):
    s = get_settings()
    _ensure_idle()
    py = s.bench_python_path()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "DATABASE_URL": s.database_url,
           "RAG_URL": s.rag_url, "RAG_API_KEY": s.rag_api_key, "WIKI_URL": s.wiki_url, "WIKI_API_KEY": s.wiki_api_key}
    # Output goes to this server's log; the run also keeps its own log in bench.runs
    _procs[run_id] = subprocess.Popen([str(py), "-m", "bench.run", "--run-id", run_id], cwd=s.bench_dir, env=env)


async def _read(f: UploadFile | None, ext: str) -> tuple[str, bytes] | None:
    if f is None or not f.filename:
        return None
    if not f.filename.lower().endswith(ext):
        raise HTTPException(400, f"{f.filename}: expected a {ext} file")
    data = await f.read()
    if not data or len(data) > MAX_UPLOAD:
        raise HTTPException(400, f"{f.filename}: empty or larger than 20 MB")
    return f.filename, data


@router.post("/runs", status_code=202)
async def start(
    reference: UploadFile | None = None,
    query_set: UploadFile | None = None,
    topics: str = Form("", description="e.g. 1,2,5-7 (empty = all)"),
    runs: int = Form(3, ge=1, le=10),
    wiki: str = Form("ifrs9", description="Wiki slug under test"),
):
    """Start a run. Files left out are reused from the most recent run that has them."""
    _ensure_idle()
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
        """insert into bench.runs (id, topics, runs, wiki_slug, query_set_name, query_set, reference_name, reference)
           values (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (run_id, topics.replace(" ", ""), runs, wiki.strip() or "ifrs9", qs[0], qs[1], ref[0], ref[1]),
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
