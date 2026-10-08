import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, HttpUrl

from .. import jobs
from ..config import get_settings
from ..db import get_pool
from ..ops import ingest
from ..sources import extract
from .deps import Mode, wiki_dep

router = APIRouter(tags=["sources"])
MODE_Q = Query("auto", description="auto = apply changes now; review = create a pending changeset")


class UrlIn(BaseModel):
    url: HttpUrl


class TextIn(BaseModel):
    title: str = Field(min_length=1)
    text: str = Field(min_length=20)


async def _start(wiki: dict, ex: extract.Extracted, uri: str | None, mode: str) -> dict:
    if not ex.text.strip():
        raise HTTPException(422, "No text extracted")
    try:
        source = await ingest.save_source(wiki["id"], ex, uri)
    except ingest.DuplicateSource as e:
        raise HTTPException(409, {"message": "Source already ingested", "source": e.slug})
    job_id = await jobs.submit(
        wiki["id"], "ingest", {"source": source["slug"], "mode": mode},
        lambda ctx: ingest.run_safe(ctx, wiki, source, ex, mode),
    )
    return {"job_id": str(job_id), "source": source["slug"], "title": ex.title, "sections": len(ex.sections), "mode": mode}


@router.post("/wikis/{w}/sources", status_code=202)
async def add_file(file: UploadFile, mode: Mode = MODE_Q, wiki: dict = Depends(wiki_dep)):
    """Upload a source file (.pdf, .docx, .md, .txt). Ingest runs as a background job."""
    s = get_settings()
    data = await file.read()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Max upload is {s.max_upload_mb} MB")
    name = file.filename or "upload.txt"
    try:
        ex = await asyncio.to_thread(extract.from_upload, name, data, s.section_words)
    except ValueError as e:
        raise HTTPException(415, str(e))
    return await _start(wiki, ex, name, mode)


@router.post("/wikis/{w}/sources/url", status_code=202)
async def add_url(body: UrlIn, mode: Mode = MODE_Q, wiki: dict = Depends(wiki_dep)):
    try:
        ex = await extract.from_url(str(body.url), get_settings().section_words)
    except (httpx.HTTPError, ValueError) as e:
        raise HTTPException(422, f"Could not fetch URL: {e}")
    return await _start(wiki, ex, str(body.url), mode)


@router.post("/wikis/{w}/sources/text", status_code=202)
async def add_text(body: TextIn, mode: Mode = MODE_Q, wiki: dict = Depends(wiki_dep)):
    ex = extract.from_text(body.title + ".md", body.text.encode("utf-8"), get_settings().section_words, title=body.title)
    return await _start(wiki, ex, None, mode)


@router.get("/wikis/{w}/sources")
async def list_sources(wiki: dict = Depends(wiki_dep)):
    async with get_pool().connection() as conn:
        return await (
            await conn.execute(
                """select id, slug, title, kind, uri, meta, length(text) as chars, created_at
                   from wiki.sources where wiki_id = %s order by created_at""",
                (wiki["id"],),
            )
        ).fetchall()


@router.get("/wikis/{w}/sources/{slug}")
async def get_source(slug: str, include_text: bool = False, wiki: dict = Depends(wiki_dep)):
    async with get_pool().connection() as conn:
        row = await (
            await conn.execute("select * from wiki.sources where wiki_id = %s and slug = %s", (wiki["id"], slug))
        ).fetchone()
        if not row:
            raise HTTPException(404, "Source not found")
        pages = await (
            await conn.execute(
                """select p.slug, p.title from wiki.page_sources ps join wiki.pages p on p.id = ps.page_id
                   where ps.source_id = %s order by p.slug""",
                (row["id"],),
            )
        ).fetchall()
    if not include_text:
        row["text"] = row["text"][:2000]
    return {**row, "pages": pages}


@router.delete("/wikis/{w}/sources/{slug}", status_code=204)
async def delete_source(slug: str, wiki: dict = Depends(wiki_dep)):
    """Remove a raw source (pages built from it are kept; use lint to find unsourced pages)."""
    async with get_pool().connection() as conn:
        cur = await conn.execute("delete from wiki.sources where wiki_id = %s and slug = %s", (wiki["id"], slug))
        if cur.rowcount == 0:
            raise HTTPException(404, "Source not found")
