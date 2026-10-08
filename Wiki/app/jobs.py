"""In-process background jobs with state persisted in wiki.jobs.

Single-instance by design: on startup, jobs left queued/running by a previous process are marked failed.
"""
import asyncio
import json
import logging
import traceback
from collections.abc import Awaitable, Callable
from uuid import UUID

from psycopg.types.json import Jsonb

from .config import get_settings
from .db import get_pool

log = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()
_sem: asyncio.Semaphore | None = None
_wiki_locks: dict[UUID, asyncio.Lock] = {}  # jobs on the same wiki run one at a time (avoids duplicate/clobbered pages)


class JobContext:
    def __init__(self, job_id: UUID):
        self.id = job_id

    async def progress(self, **kw):
        async with get_pool().connection() as conn:
            await conn.execute("update wiki.jobs set progress = progress || %s where id = %s", (Jsonb(kw), self.id))


async def recover():
    global _sem
    _sem = asyncio.Semaphore(get_settings().job_workers)
    async with get_pool().connection() as conn:
        await conn.execute(
            """update wiki.jobs set status='failed', error='Interrupted by server restart', finished_at=now()
               where status in ('queued', 'running')"""
        )


async def submit(wiki_id: UUID, kind: str, params: dict, fn: Callable[[JobContext], Awaitable[dict]]) -> UUID:
    async with get_pool().connection() as conn:
        row = await (
            await conn.execute(
                "insert into wiki.jobs (wiki_id, kind, params) values (%s,%s,%s) returning id", (wiki_id, kind, Jsonb(params))
            )
        ).fetchone()
    job_id = row["id"]
    task = asyncio.create_task(_run(job_id, wiki_id, fn))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job_id


async def _run(job_id: UUID, wiki_id: UUID, fn):
    assert _sem is not None
    async with _wiki_locks.setdefault(wiki_id, asyncio.Lock()), _sem:
        async with get_pool().connection() as conn:
            await conn.execute("update wiki.jobs set status='running', started_at=now() where id=%s", (job_id,))
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
