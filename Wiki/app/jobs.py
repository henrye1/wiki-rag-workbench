"""In-process background jobs with state persisted in wiki.jobs.

Uploads to one wiki take turns: an ingest job waits (status queued, the reason in progress.waiting) while an earlier
upload to the same wiki is running or waiting, or while the wiki has an upload changeset pending review. So every upload
is written against the wiki as it stands after the one before it, and applying it later never conflicts. It starts when
the pending one is applied or discarded (checked every WAIT_S seconds, and at once when this service applies or discards
one: release()).

On startup, jobs left queued/running by a previous process are marked failed, except this service's uploads that were
still waiting their turn: they are put back in the queue from their source's saved passages (see resumer()). Uploads
waiting in another service on the same database (a local run beside Render) are left to that service.
"""
import asyncio
import json
import logging
import os
import socket
import traceback
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable
from uuid import UUID

from psycopg.types.json import Jsonb

from .config import get_settings
from .db import get_pool

log = logging.getLogger(__name__)
WAIT_S = 30  # how often a waiting upload checks whether it may start
_tasks: set[asyncio.Task] = set()
_sem: asyncio.Semaphore | None = None
_wiki_locks: dict[UUID, asyncio.Lock] = {}  # jobs on the same wiki run one at a time (avoids duplicate/clobbered pages)
_upload_turns: dict[UUID, asyncio.Lock] = {}  # uploads to the same wiki take turns, in the order they were made
_released: dict[UUID, asyncio.Event] = {}  # set when a changeset of the wiki is applied or discarded
_resumers: dict[str, Callable[[dict], Awaitable[Callable | None]]] = {}


def instance() -> str:
    """Which service queued a job: Render's service id (the same across its restarts and deploys), else the host name."""
    return os.environ.get("RENDER_SERVICE_ID") or socket.gethostname()


def resumer(kind: str):
    """Register how a waiting job of this kind is put back in the queue after a restart: fn(job row) -> the job's
    function, or None when it cannot be resumed (it is then marked failed)."""
    def deco(fn):
        _resumers[kind] = fn
        return fn
    return deco


class JobContext:
    def __init__(self, job_id: UUID):
        self.id = job_id

    async def progress(self, **kw):
        """Record progress; a new stage also records when it started (stage_times: stage -> time), so where an upload
        spends its time can be read from the job."""
        at = {kw["stage"]: datetime.now(timezone.utc).isoformat()} if "stage" in kw else {}
        async with get_pool().connection() as conn:
            await conn.execute(
                """update wiki.jobs set progress = progress || %s
                   || jsonb_build_object('stage_times', coalesce(progress->'stage_times', '{}'::jsonb) || %s) where id = %s""",
                (Jsonb(kw), Jsonb(at), self.id))


async def recover():
    global _sem
    _sem = asyncio.Semaphore(get_settings().job_workers)
    me = instance()
    async with get_pool().connection() as conn:
        waiting = await (await conn.execute(
            """select * from wiki.jobs where status = 'queued' and kind = any(%s) and params->>'instance' = %s
               order by created_at""", (list(_resumers), me))).fetchall()
        resumed = []
        for job in waiting:
            fn = await _resumers[job["kind"]](job)
            if fn:
                resumed.append((job, fn))
        await conn.execute(
            """update wiki.jobs set status='failed', error='Interrupted by server restart', finished_at=now()
               where status in ('queued', 'running') and not id = any(%s)
               and not (status = 'queued' and kind = any(%s) and params ? 'instance' and params->>'instance' <> %s)""",
            ([j["id"] for j, _ in resumed], list(_resumers), me))
    for job, fn in resumed:
        log.info("Job %s (%s) put back in the queue after a restart", job["id"], job["kind"])
        _start(job["id"], job["wiki_id"], job["kind"], fn)


async def submit(wiki_id: UUID, kind: str, params: dict, fn: Callable[[JobContext], Awaitable[dict]]) -> UUID:
    async with get_pool().connection() as conn:
        row = await (
            await conn.execute(
                "insert into wiki.jobs (wiki_id, kind, params) values (%s,%s,%s) returning id",
                (wiki_id, kind, Jsonb({**params, "instance": instance()}))
            )
        ).fetchone()
    _start(row["id"], wiki_id, kind, fn)
    return row["id"]


def release(wiki_id: UUID):
    """A changeset of this wiki was applied or discarded: a waiting upload checks at once whether it may start."""
    if ev := _released.get(wiki_id):
        ev.set()


def _start(job_id: UUID, wiki_id: UUID, kind: str, fn):
    task = asyncio.create_task(_turn(job_id, wiki_id, fn) if kind == "ingest" else _run(job_id, wiki_id, fn))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _waiting(job_id: UUID, why: dict | None):
    async with get_pool().connection() as conn:
        await conn.execute("update wiki.jobs set progress = progress || jsonb_build_object('waiting', %s::jsonb) where id = %s",
                           (Jsonb(why), job_id))


async def _blocker(wiki_id: UUID, job_id: UUID) -> dict | None:
    """What an upload waits for before it may start: the wiki's oldest upload changeset pending review, or another upload
    to the wiki still running (in any service on the database). None when it may start."""
    async with get_pool().connection() as conn:
        cs = await (await conn.execute(
            """select id, summary from wiki.changesets where wiki_id = %s and kind = 'ingest' and status = 'pending'
               order by created_at limit 1""", (wiki_id,))).fetchone()
        if cs:
            return {"changeset": str(cs["id"]), "message": f"Waiting: changeset {str(cs['id'])[:8]} ({cs['summary']}) is "
                    "pending review. This upload starts when it is applied or discarded."}
        job = await (await conn.execute(
            """select id, params->>'source' as source from wiki.jobs where wiki_id = %s and kind = 'ingest'
               and status = 'running' and id <> %s order by started_at limit 1""", (wiki_id, job_id))).fetchone()
    if job:
        return {"job": str(job["id"]), "message": f"Waiting: the upload of {job['source']} (job {str(job['id'])[:8]}) is "
                "still running."}
    return None


async def _turn(job_id: UUID, wiki_id: UUID, fn):
    """An upload: wait for this wiki's earlier uploads, then for nothing to be pending or running, then run."""
    turn = _upload_turns.setdefault(wiki_id, asyncio.Lock())
    if turn.locked():
        await _waiting(job_id, {"message": "Waiting: an earlier upload to this wiki goes first."})
    async with turn:
        ev = _released.setdefault(wiki_id, asyncio.Event())
        while why := await _blocker(wiki_id, job_id):
            await _waiting(job_id, why)
            ev.clear()
            try:
                await asyncio.wait_for(ev.wait(), WAIT_S)
            except TimeoutError:
                pass
        await _waiting(job_id, None)
        await _run(job_id, wiki_id, fn)


async def _run(job_id: UUID, wiki_id: UUID, fn):
    assert _sem is not None
    async with _wiki_locks.setdefault(wiki_id, asyncio.Lock()), _sem:
        async with get_pool().connection() as conn:  # only a job still queued starts (not one failed or taken meanwhile)
            started = await (await conn.execute(
                "update wiki.jobs set status='running', started_at=now() where id=%s and status='queued' returning id",
                (job_id,))).fetchone()
        if not started:
            log.info("Job %s is no longer queued; not started", job_id)
            return
        try:
            result = await fn(JobContext(job_id))
            status, error = "succeeded", None
        except Exception as e:
            log.error("Job %s failed: %s", job_id, traceback.format_exc())
            result, status, error = None, "failed", f"{type(e).__name__}: {e}"
        async with get_pool().connection() as conn:
            await conn.execute(
                "update wiki.jobs set status=%s, result=%s, error=%s, finished_at=now() where id=%s",
                (status, Jsonb(json.loads(json.dumps(result, default=str))) if result is not None else None, error, job_id),
            )


async def get_job(job_id: UUID) -> dict | None:
    async with get_pool().connection() as conn:
        return await (await conn.execute("select * from wiki.jobs where id = %s", (job_id,))).fetchone()
