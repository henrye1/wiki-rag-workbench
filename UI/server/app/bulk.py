"""RAG bulk requirement runs as BFF background tasks (a 26-topic run takes minutes - too long for one browser request)."""
import asyncio
import datetime as dt
import uuid

from fastapi import APIRouter, Form, HTTPException, UploadFile

from .config import get_settings
from .proxy import client

router = APIRouter(prefix="/api/bulk", tags=["bulk"])
_runs: dict[str, dict] = {}
_tasks: set[asyncio.Task] = set()


async def _execute(run_id: str, filename: str, data: bytes, topics: list[int], revise: bool):
    s = get_settings()
    run = _runs[run_id]
    params = [("revise", str(revise).lower())] + [("topics", str(t)) for t in topics]
    try:
        resp = await client().post(
            f"{s.rag_url}/bulk", params=params, files={"file": (filename, data, "text/plain")},
            headers={"X-API-Key": s.rag_api_key}, timeout=3600,
        )
        resp.raise_for_status()
        run.update(status="succeeded", result=resp.json())
    except Exception as e:
        run.update(status="failed", error=f"{type(e).__name__}: {e}")
    run["finished"] = dt.datetime.now().isoformat(timespec="seconds")


@router.post("", status_code=202)
async def start(file: UploadFile | None = None, topics: str = Form(""), revise: bool = Form(True)):
    """Start a bulk run. No file = the default query set. topics: '1,3,5-7' (empty = all)."""
    s = get_settings()
    if file is not None:
        filename, data = file.filename or "query_set.txt", await file.read()
    else:
        if not s.default_query_set.exists():
            raise HTTPException(404, "Default query set not found")
        filename, data = s.default_query_set.name, s.default_query_set.read_bytes()
    nums: list[int] = []
    for part in [p for p in topics.replace(" ", "").split(",") if p]:
        a, _, b = part.partition("-")
        nums += list(range(int(a), int(b or a) + 1))
    run_id = uuid.uuid4().hex[:12]
    _runs[run_id] = {"id": run_id, "status": "running", "file": filename, "topics": nums, "revise": revise,
                     "started": dt.datetime.now().isoformat(timespec="seconds"), "result": None, "error": None}
    task = asyncio.create_task(_execute(run_id, filename, data, nums, revise))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"id": run_id}


@router.get("")
async def list_runs():
    return [{k: v for k, v in r.items() if k != "result"} for r in sorted(_runs.values(), key=lambda r: r["started"], reverse=True)]


@router.get("/{run_id}")
async def get_run(run_id: str):
    if run_id not in _runs:
        raise HTTPException(404, "Bulk run not found (runs are kept in memory until the UI server restarts)")
    return _runs[run_id]
