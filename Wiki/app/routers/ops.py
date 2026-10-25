import difflib
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .. import jobs
from ..db import get_pool
from ..ops import lint, query, recheck, synthesis
from ..wiki import store
from .deps import Mode, wiki_dep

router = APIRouter(tags=["operations"])


class QueryIn(BaseModel):
    question: str = Field(min_length=3)
    save: bool = Field(False, description="File the answer back into the wiki as a synthesis page")
    mode: Mode = "auto"
    sources: Literal["standard", "all"] = Field(
        "all", description="standard = only statements cited to the Standard itself (Part A); all = also Parts B and C")
    use_saved: bool = Field(True, description="Also read relevant saved answers (synthesis pages filed with Save), "
                                              "in addition to the pages chosen for the question")


class SynthAnswer(BaseModel):
    searched: str
    answer: str
    sources: Literal["standard", "all"]
    date: str = Field(description="When the answer was made (ISO)")


class SynthDraftIn(BaseModel):
    chat_id: str = Field(min_length=4)
    chat_title: str = ""
    answers: list[SynthAnswer] = Field(min_length=1, description="The chat's wiki answers, oldest first (never RAG answers)")


class SynthCheckIn(BaseModel):
    content_md: str
    answers: list[SynthAnswer] = Field(min_length=1)


class SynthSaveIn(SynthCheckIn):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*-synthesis-[a-z0-9]+$")
    title: str = Field(min_length=1)
    summary: str = ""
    tags: list[str] = []


@router.post("/wikis/{w}/synthesis/draft")
async def synthesis_draft(body: SynthDraftIn, wiki: dict = Depends(wiki_dep)):
    """Draft one synthesis page from a chat's wiki answers, with its citation problems. Nothing is saved."""
    return await synthesis.draft(wiki, body.chat_id, body.chat_title, [a.model_dump() for a in body.answers])


@router.post("/wikis/{w}/synthesis/check")
async def synthesis_check(body: SynthCheckIn, wiki: dict = Depends(wiki_dep)):
    """Check an (edited) draft again. Nothing is saved."""
    return await synthesis.check(wiki, body.content_md, [a.model_dump() for a in body.answers])


@router.post("/wikis/{w}/synthesis", status_code=201)
async def synthesis_save(body: SynthSaveIn, wiki: dict = Depends(wiki_dep)):
    """Save the draft as a synthesis page (a saved answer); the same chat updates the same page."""
    try:
        return await synthesis.save(wiki, body.model_dump(exclude={"answers"}), [a.model_dump() for a in body.answers])
    except ValueError as e:
        raise HTTPException(409, str(e))


class LintIn(BaseModel):
    llm: bool = Field(False, description="Also run the LLM health-check (contradictions, missing pages, ...)")
    fix: bool = Field(False, description="Create pages for broken links/missing concepts and add missing cross-links")
    mode: Mode = "review"


class ReadTextIn(BaseModel):
    read: list[dict] = Field(description="An answer's `read` record: slug, version and sha256 of each page")
    sources: Literal["standard", "all"] = "all"


@router.post("/wikis/{w}/read-text")
async def read_text(body: ReadTextIn, wiki: dict = Depends(wiki_dep)):
    """The exact text an earlier answer read (for checking an answer against what it read). Changes nothing."""
    return await query.read_text(wiki, body.read, body.sources)


@router.post("/wikis/{w}/query")
async def ask(body: QueryIn, wiki: dict = Depends(wiki_dep)):
    return await query.answer(wiki, body.question, body.save, body.mode, body.sources, body.use_saved)


@router.post("/wikis/{w}/query/stream")
async def ask_stream(body: QueryIn, wiki: dict = Depends(wiki_dep)):
    pages, tokens = await query.stream_answer(wiki, body.question, body.sources, body.use_saved)

    async def events():
        parts = []
        async for t in tokens:
            parts.append(t)
            yield {"event": "token", "data": json.dumps(t)}
        yield {"event": "pages", "data": json.dumps(query.listed(wiki, "".join(parts), pages))}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(events())


@router.post("/wikis/{w}/lint", status_code=202)
async def run_lint(body: LintIn, wiki: dict = Depends(wiki_dep)):
    if not body.llm and not body.fix:
        return {"structural": await lint.structural(wiki["id"])}  # fast path, synchronous
    job_id = await jobs.submit(wiki["id"], "lint", body.model_dump(), lambda ctx: lint.run(ctx, wiki, body.llm, body.fix, body.mode))
    return {"job_id": str(job_id)}


class RecheckIn(BaseModel):
    mode: Mode = "auto"


@router.post("/wikis/{w}/recheck", status_code=202)
async def run_recheck(body: RecheckIn, wiki: dict = Depends(wiki_dep)):
    """Run the after-writing page checks (and their fix rounds) on every page the wiki has, without re-ingesting."""
    job_id = await jobs.submit(wiki["id"], "recheck", body.model_dump(), lambda ctx: recheck.run(ctx, wiki, body.mode))
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
