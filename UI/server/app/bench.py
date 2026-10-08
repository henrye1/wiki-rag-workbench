"""Benchmark: list/read result runs and start new runs of `python -m bench.run` as subprocesses."""
import datetime as dt
import json
import os
import subprocess

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .config import get_settings

router = APIRouter(prefix="/api/bench", tags=["benchmark"])
_procs: dict[str, subprocess.Popen] = {}


class StartIn(BaseModel):
    topics: str = Field("", description="e.g. 1,2,5-7 (empty = all)")
    runs: int = Field(3, ge=1, le=10)


def _results_dir():
    return get_settings().bench_dir / "results"


def _load(run_id: str) -> dict:
    path = _results_dir() / run_id / "results.json"
    if not path.exists():
        raise HTTPException(404, "Run not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:  # mid-write; caller retries
        raise HTTPException(409, "Results file is being written, retry")


def _progress(data: dict, run_id: str) -> dict:
    topics = data.get("topics", {})
    done = sum(1 for t in topics.values() for r in t.get("runs", {}).values() if r.get("judgement"))
    meta = data.get("config", {})
    expected = meta.get("expected_judgements")
    proc = _procs.get(run_id)
    running = proc is not None and proc.poll() is None
    status = "running" if running else ("finished" if meta.get("finished") else ("failed" if proc is not None else "incomplete"))
    return {"done": done, "expected": expected, "status": status, "errors": data.get("errors") or {}}


@router.get("/runs")
async def list_runs():
    out = []
    root = _results_dir()
    if not root.exists():
        return out
    for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
        try:
            data = _load(d.name)
        except HTTPException:
            continue
        cfg = data.get("config", {})
        out.append({
            "id": d.name, "started": cfg.get("started"), "finished": cfg.get("finished"), "runs": cfg.get("runs"),
            "judge_model": cfg.get("judge_model"), "topics": len(data.get("topics", {})),
            "summary": data.get("summary"), "progress": _progress(data, d.name),
        })
    return out


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    data = _load(run_id)
    data["progress"] = _progress(data, run_id)
    return data


@router.get("/runs/{run_id}/status")
async def status(run_id: str):
    data = _load(run_id)
    log = _results_dir() / run_id / "run.log"
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:] if log.exists() else []
    return {**_progress(data, run_id), "log": tail}


@router.post("/runs", status_code=202)
async def start(body: StartIn):
    s = get_settings()
    py = s.bench_python_path()
    if not py.exists():
        raise HTTPException(500, f"Benchmark python not found: {py}")
    if any(p.poll() is None for p in _procs.values()):
        raise HTTPException(409, "A benchmark run is already in progress")
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = _results_dir() / run_id
    out.mkdir(parents=True, exist_ok=True)
    args = [str(py), "-m", "bench.run", "--resume", f"results/{run_id}", "--runs", str(body.runs)]
    if body.topics.strip():
        args += ["--topics", body.topics.replace(" ", "")]
    log = open(out / "run.log", "w", encoding="utf-8")
    _procs[run_id] = subprocess.Popen(args, cwd=s.bench_dir, stdout=log, stderr=subprocess.STDOUT,
                                      env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    return {"id": run_id}
