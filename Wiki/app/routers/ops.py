import difflib
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .. import jobs
from ..db import get_pool
from ..ops import lint, query
from ..wiki import store
from .deps import Mode, wiki_dep

router = APIRouter(tags=["operations"])


class QueryIn(BaseModel):
    question: str = Field(min_length=3)
    save: bool = Field(False, description="File the answer back into the wiki as a synthesis page")
    mode: Mode = "auto"


class LintIn(BaseModel):
    llm: bool = Field(False, description="Also run the LLM health-check (contradictions, missing pages, ...)")
    fix: bool = Field(False, description="Create pages for broken links/missing concepts and add missing cross-links")
    mode: Mode = "review"


@router.post("/wikis/{w}/query")
async def ask(body: QueryIn, wiki: dict = Depends(wiki_dep)):
    return await query.answer(wiki, body.question, body.save, body.mode)


@router.post("/wikis/{w}/query/stream")
async def ask_stream(body: QueryIn, wiki: dict = Depends(wiki_dep)):
    pages, tokens = await query.stream_answer(wiki, body.question)

    async def events():
        parts = []
        async for t in tokens:
            parts.append(t)
            yield {"event": "token", "data": json.dumps(t)}
        linked = store.extract_links("".join(parts))
        yield {"event": "pages", "data": json.dumps([{"slug": p["slug"], "title": p["title"], "cited": p["slug"] in linked} for p in pages])}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(events())


@router.post("/wikis/{w}/lint", status_code=202)
async def run_lint(body: LintIn, wiki: dict = Depends(wiki_dep)):
    if not body.llm and not body.fix:
        return {"structural": await lint.structural(wiki["id"])}  # fast path, synchronous
    job_id = await jobs.submit(wiki["id"], "lint", body.model_dump(), lambda ctx: lint.run(ctx, wiki, body.llm, body.fix, body.mode))
    return {"job_id": str(job_id)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: UUID):
    job = await jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/wikis/{w}/jobs")
async def list_jobs(wiki: dict = Depends(wiki_dep)):
    async with get_pool().connection() as conn:
        return await (
            await conn.execute(
                """select id, kind, status, params, progress, error, created_at, finished_at
                   from wiki.jobs where wiki_id = %s order by created_at desc limit 50""",
                (wiki["id"],),
            )
        ).fetchall()


# ---------- changesets ----------

@router.get("/wikis/{w}/changesets")
async def list_changesets(status: str | None = None, wiki: dict = Depends(wiki_dep)):
    async with get_pool().connection() as conn:
        return await (
            await conn.execute(
                """select c.*, (select count(*) from wiki.changeset_ops o where o.changeset_id = c.id) as ops
                   from wiki.changesets c where c.wiki_id = %s and (%s::text is null or c.status = %s)
                   order by c.created_at desc limit 100""",
                (wiki["id"], status, status),
            )
        ).fetchall()


async def _cs_in_wiki(wiki: dict, cs_id: UUID):
    try:
        cs, ops = await store.get_changeset(cs_id)
    except store.NotFound:
        raise HTTPException(404, "Changeset not found")
    if cs["wiki_id"] != wiki["id"]:
        raise HTTPException(404, "Changeset not found")
    return cs, ops


@router.get("/wikis/{w}/changesets/{cs_id}")
async def get_changeset(cs_id: UUID, diff: bool = True, wiki: dict = Depends(wiki_dep)):
    cs, ops = await _cs_in_wiki(wiki, cs_id)
    out = []
    for o in ops:
        item = dict(o)
        if diff and o["op"] != "delete":
            cur = await store.get_page(wiki["id"], o["slug"])
            before = (cur["content_md"] if cur else "").splitlines()
            item["diff"] = "\n".join(difflib.unified_diff(before, (o["content_md"] or "").splitlines(),
                                                          f"{o['slug']} (current)", f"{o['slug']} (proposed)", lineterm=""))
            item["current_version"] = cur["version"] if cur else None
        out.append(item)
    return {**cs, "ops": out}


@router.post("/wikis/{w}/changesets/{cs_id}/apply")
async def apply_changeset(cs_id: UUID, force: bool = False, wiki: dict = Depends(wiki_dep)):
    await _cs_in_wiki(wiki, cs_id)
    try:
        return await store.apply_changeset(cs_id, force=force)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/wikis/{w}/changesets/{cs_id}/discard")
async def discard_changeset(cs_id: UUID, wiki: dict = Depends(wiki_dep)):
    await _cs_in_wiki(wiki, cs_id)
    try:
        removed_source = await store.discard_changeset(cs_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    await store.add_log(wiki["id"], "edit", f"Changeset {cs_id} discarded" + (f"; source {removed_source} removed" if removed_source else ""))
    return {"ok": True, "removed_source": removed_source}
