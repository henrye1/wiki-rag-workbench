import difflib
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .. import jobs
from ..db import get_pool
from ..ops import composed, ingest, lint, query, recheck, summaries, synthesis, watchdog
from ..wiki import checks, store
from . import sources
from .deps import Mode, wiki_dep

router = APIRouter(tags=["operations"])


class QueryIn(BaseModel):
    question: str = Field(min_length=3)
    save: bool = Field(False, description="File the answer back into the wiki as a synthesis page")
    mode: Mode = "auto"
    sources: Literal["standard", "all"] = Field(
        "all", description="standard = only statements citing text of no paragraph kind the schema lists, by paragraph "
                           "kind (the schema's Standard only list in its Checks); all = every statement")
    use_saved: bool = Field(True, description="Also read relevant saved answers (synthesis pages filed with Save), "
                                              "in addition to the pages chosen for the question")
    instructions: str | None = Field(None, max_length=40000, description="The chat's skills: added to the answer "
                                     "instruction (never to what is searched); none by default")


class SynthAnswer(BaseModel):
    searched: str
    answer: str
    sources: Literal["standard", "all"]
    date: str = Field(description="When the answer was made (ISO)")


class SynthDraftIn(BaseModel):
    chat_id: str = Field(min_length=4)
    chat_title: str = ""
    answers: list[SynthAnswer] = Field(min_length=1, description="The chat's wiki answers, oldest first (never RAG answers)")
    answer_seq: int | None = Field(None, description="The number in the chat of the one answer drafted on its own")
    into: str | None = Field(None, description="An existing synthesis page the answer is added to")


class SynthCheckIn(BaseModel):
    content_md: str
    answers: list[SynthAnswer] = Field(min_length=1)
    into: str | None = Field(None, description="An existing synthesis page the answer is added to")


class SynthSaveIn(SynthCheckIn):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*-synthesis-[a-z0-9]+$")
    title: str = Field(min_length=1)
    summary: str = ""
    tags: list[str] = []


@router.post("/wikis/{w}/synthesis/draft")
async def synthesis_draft(body: SynthDraftIn, wiki: dict = Depends(wiki_dep)):
    """Draft one synthesis page from a chat's wiki answers, or from one of them (answer_seq) as its own page or added to
    an existing synthesis page (into), with its citation problems. Nothing is saved."""
    try:
        return await synthesis.draft(wiki, body.chat_id, body.chat_title, [a.model_dump() for a in body.answers],
                                     body.answer_seq, body.into)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/wikis/{w}/synthesis/check")
async def synthesis_check(body: SynthCheckIn, wiki: dict = Depends(wiki_dep)):
    """Check an (edited) draft again. Nothing is saved."""
    try:
        return await synthesis.check(wiki, body.content_md, [a.model_dump() for a in body.answers], body.into)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/wikis/{w}/synthesis", status_code=201)
async def synthesis_save(body: SynthSaveIn, wiki: dict = Depends(wiki_dep)):
    """Save the draft as a synthesis page (a saved answer); the same chat updates the same page."""
    try:
        return await synthesis.save(wiki, body.model_dump(exclude={"answers", "into"}), [a.model_dump() for a in body.answers], body.into)
    except ValueError as e:
        raise HTTPException(409, str(e))


class LintIn(BaseModel):
    llm: bool = Field(False, description="Also run the LLM health-check (contradictions, missing pages, ...)")
    fix: bool = Field(False, description="Propose plain text for links to pages that do not exist (lint writes no page)")


class ReadTextIn(BaseModel):
    read: list[dict] = Field(description="An answer's `read` record: slug, version and sha256 of each page")
    sources: Literal["standard", "all"] = "all"


@router.post("/wikis/{w}/read-text")
async def read_text(body: ReadTextIn, wiki: dict = Depends(wiki_dep)):
    """The exact text an earlier answer read (for checking an answer against what it read). Changes nothing."""
    try:
        return await query.read_text(wiki, body.read, body.sources)
    except query.NoStandardOnly as e:
        raise HTTPException(400, str(e))


@router.post("/wikis/{w}/query")
async def ask(body: QueryIn, wiki: dict = Depends(wiki_dep)):
    try:
        return await query.answer(wiki, body.question, body.save, body.mode, body.sources, body.use_saved, body.instructions)
    except query.NoStandardOnly as e:
        raise HTTPException(400, str(e))


@router.post("/wikis/{w}/query/stream")
async def ask_stream(body: QueryIn, wiki: dict = Depends(wiki_dep)):
    try:
        pages, tokens, report = await query.stream_answer(wiki, body.question, body.sources, body.use_saved, body.instructions)
    except query.NoStandardOnly as e:
        raise HTTPException(400, str(e))

    async def events():
        parts = []
        async for t in tokens:
            parts.append(t)
            yield {"event": "token", "data": json.dumps(t)}
        yield {"event": "pages", "data": json.dumps(query.listed(wiki, "".join(parts), pages))}
        if report is not None:  # the schema's answer checks: what they found, and what is left after the fix pass
            yield {"event": "check", "data": json.dumps(report)}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(events())


@router.post("/wikis/{w}/lint", status_code=202)
async def run_lint(body: LintIn, wiki: dict = Depends(wiki_dep)):
    if not body.llm and not body.fix:
        return {"structural": await lint.structural(wiki["id"], checks.load(wiki["schema_md"])),  # fast path, synchronous
                "maintain": await lint.maintain(wiki)}
    job_id = await jobs.submit(wiki["id"], "lint", body.model_dump(), lambda ctx: lint.run(ctx, wiki, body.llm, body.fix))
    return {"job_id": str(job_id)}


class RecheckIn(BaseModel):
    mode: Mode = "auto"
    pages: list[str] | None = Field(None, description="Only these pages are checked (every page when left out)")


@router.post("/wikis/{w}/recheck", status_code=202)
async def run_recheck(body: RecheckIn, wiki: dict = Depends(wiki_dep)):
    """Run the after-writing page checks (and their fix rounds) on every page the wiki has (or the pages named), without
    re-ingesting."""
    job_id = await jobs.submit(wiki["id"], "recheck", body.model_dump(), lambda ctx: recheck.run(ctx, wiki, body.mode, body.pages))
    return {"job_id": str(job_id)}


class SummariesIn(BaseModel):
    dry_run: bool = Field(False, description="Report what would change; save nothing")


@router.post("/wikis/{w}/composed")
async def rebuild_composed(body: SummariesIn, wiki: dict = Depends(wiki_dep)):
    """Rebuild the concept and entity pages (and the examples index's list of examples inside guidance) from the pages as
    they stand, by the schema's lists. No AI call; dry_run reports what would change."""
    return await composed.rebuild(wiki, body.dry_run)


@router.post("/wikis/{w}/summaries")
async def recompute_summaries(body: SummariesIn, wiki: dict = Depends(wiki_dep)):
    """Make every page's summary again by the schema's summary rules, from the page text as it stands. No AI call is
    made and no page text changes; a changed summary is saved as a new page version."""
    return await summaries.recompute(wiki, body.dry_run)


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


async def _rerunnable(wiki: dict, cs: dict) -> bool:
    """An upload changeset whose source kept its passages: it can be run again against the current wiki."""
    if cs["kind"] != "ingest" or not cs["source_id"]:
        return False
    async with get_pool().connection() as conn:
        row = await (await conn.execute("select sections is not null as kept from wiki.sources where id = %s",
                                        (cs["source_id"],))).fetchone()
    return bool(row and row["kept"])


@router.get("/wikis/{w}/changesets/{cs_id}")
async def get_changeset(cs_id: UUID, diff: bool = True, wiki: dict = Depends(wiki_dep)):
    """A changeset and its ops. While pending: stale, the ops that no longer fit the wiki (applying is refused while
    there are any), and rerun, whether it can be run again against the current wiki."""
    cs, ops = await _cs_in_wiki(wiki, cs_id)
    if cs["status"] == "pending":
        cs = {**cs, "stale": await store.stale_ops(wiki["id"], ops), "rerun": await _rerunnable(wiki, cs)}
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
async def apply_changeset(cs_id: UUID, force: bool = False, reviewer: str | None = None, wiki: dict = Depends(wiki_dep)):
    """Apply a pending changeset. One held for review (its checks failed) is applied only by a named reviewer, whose
    name is recorded with it."""
    cs, _ = await _cs_in_wiki(wiki, cs_id)
    reviewer = (reviewer or "").strip() or None
    if cs.get("check_failures") and not reviewer:
        raise HTTPException(409, "This changeset was held for review: it is applied only by a named reviewer (give reviewer).")
    try:
        res = await store.apply_changeset(cs_id, force=force, reviewer=reviewer)
    except store.Conflicts as e:
        raise HTTPException(409, {"message": f"Not applied: {len(e.conflicts)} page(s) changed since this changeset was "
                                  "written. It is still pending. Re-run it against the current wiki, or apply it anyway "
                                  "to overwrite those pages.", "conflicts": e.conflicts})
    except ValueError as e:
        raise HTTPException(409, str(e))
    jobs.release(wiki["id"])
    if reviewer:
        await store.add_log(wiki["id"], "edit", f"Changeset {cs_id} applied by {reviewer}")
    return res


@router.post("/wikis/{w}/changesets/{cs_id}/discard")
async def discard_changeset(cs_id: UUID, reviewer: str | None = None, wiki: dict = Depends(wiki_dep)):
    await _cs_in_wiki(wiki, cs_id)
    reviewer = (reviewer or "").strip() or None
    try:
        removed_source = await store.discard_changeset(cs_id, reviewer=reviewer)
    except ValueError as e:
        raise HTTPException(409, str(e))
    jobs.release(wiki["id"])
    await store.add_log(wiki["id"], "edit", f"Changeset {cs_id} discarded" + (f" by {reviewer}" if reviewer else "")
                        + (f"; source {removed_source} removed" if removed_source else ""))
    return {"ok": True, "removed_source": removed_source}


@router.post("/wikis/{w}/changesets/{cs_id}/rerun", status_code=202)
async def rerun_changeset(cs_id: UUID, reviewer: str | None = None, wiki: dict = Depends(wiki_dep)):
    """Run a pending upload again against the wiki as it is now: the changeset is discarded, its source is kept, and a
    new ingest job is queued from the passages the source saved at upload, in the upload's own mode. No file needed."""
    cs, _ = await _cs_in_wiki(wiki, cs_id)
    reviewer = (reviewer or "").strip() or None
    if cs["status"] != "pending":
        raise HTTPException(409, f"Changeset is {cs['status']}")
    if cs["kind"] != "ingest" or not cs["source_id"]:
        raise HTTPException(409, "Only an upload's changeset can be re-run")
    async with get_pool().connection() as conn:
        src = await (await conn.execute("select slug from wiki.sources where id = %s", (cs["source_id"],))).fetchone()
        job = await (await conn.execute("select params from wiki.jobs where id = %s", (cs["job_id"],))).fetchone() \
            if cs["job_id"] else None
    saved = await ingest.saved_upload(wiki["id"], src["slug"]) if src else None
    if not saved:
        raise HTTPException(409, "This source was uploaded before passages were kept: discard the changeset and upload "
                                 "the file again")
    try:
        await store.discard_changeset(cs_id, reviewer=reviewer, keep_source=True)
    except ValueError as e:
        raise HTTPException(409, str(e))
    source, ex = saved
    mode = ((job or {}).get("params") or {}).get("mode") or "review"
    job_id = await sources.submit_ingest(wiki, source, ex, mode, rerun_of=str(cs_id))
    await store.add_log(wiki["id"], "edit", f"Changeset {cs_id} re-run against the current wiki as job {job_id}"
                        + (f" by {reviewer}" if reviewer else ""))
    jobs.release(wiki["id"])
    return {"job_id": str(job_id), "source": source["slug"], "mode": mode, "discarded": str(cs_id)}


class StatementIn(BaseModel):
    statement: str = Field(min_length=3, description="The client statement to check against the standard")
    sources: Literal["standard", "all"] = "all"


@router.post("/wikis/{w}/statements/check")
async def check_statement(body: StatementIn, wiki: dict = Depends(wiki_dep)):
    """Check a client statement (the watchdog): one verdict from the schema's Client-statement verdicts, each clause
    cited and quoted, recorded as an open finding for a named reviewer. Changes no page."""
    try:
        return await watchdog.check_statement(wiki, body.statement, body.sources)
    except (watchdog.NoVerdicts, query.NoStandardOnly) as e:
        raise HTTPException(400, str(e))


@router.get("/wikis/{w}/findings")
async def list_findings(status: Literal["open", "closed"] | None = None, wiki: dict = Depends(wiki_dep)):
    return await watchdog.findings(wiki["id"], status)


class ReviewIn(BaseModel):
    reviewer: str = Field(min_length=1, description="The named reviewer closing the finding")
    decision: str = Field(min_length=1)
    note: str = ""


@router.post("/wikis/{w}/findings/{finding_id}/review")
async def review_finding(finding_id: UUID, body: ReviewIn, wiki: dict = Depends(wiki_dep)):
    """Close a finding: its reviewer's name, decision and note are recorded with it. Changes no page."""
    try:
        row = await watchdog.review(wiki["id"], finding_id, body.reviewer, body.decision, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    await store.add_log(wiki["id"], "review", f"Finding {finding_id} closed by {row['reviewer']}: {row['decision']}")
    return row
