import asyncio

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, HttpUrl

from .. import jobs, llm, prompts, storage
from ..config import get_settings
from ..db import get_pool
from ..ops import ingest
from ..sources import extract
from ..wiki import checks
from .deps import Mode, wiki_dep

router = APIRouter(tags=["sources"])
MODE_Q = Query("auto", description="auto = apply changes now; review = create a pending changeset")


class UrlIn(BaseModel):
    url: HttpUrl


class TextIn(BaseModel):
    title: str = Field(min_length=1)
    text: str = Field(min_length=20)


async def _start(wiki: dict, ex: extract.Extracted, uri: str | None, mode: str,
                 file: tuple[str, bytes] | None = None) -> dict:
    if not ex.text.strip():
        raise HTTPException(422, "No text extracted")
    try:
        source = await ingest.save_source(wiki["id"], ex, uri)
    except ingest.DuplicateSource as e:
        raise HTTPException(409, {"message": "Source already ingested", "source": e.slug})
    if file:  # keep the original upload so it can be viewed later
        await attach_file(source["id"], storage.object_path("wiki", str(wiki["id"]), source["slug"], file[0]), file[1], file[0])
    job_id = await jobs.submit(
        wiki["id"], "ingest", {"source": source["slug"], "mode": mode},
        lambda ctx: ingest.run_safe(ctx, wiki, source, ex, mode),
    )
    return {"job_id": str(job_id), "source": source["slug"], "title": ex.title, "sections": len(ex.sections), "mode": mode,
            "warnings": ex.meta.get("warnings", [])}


@router.post("/wikis/{w}/sources/describe")
async def describe_file(file: UploadFile, wiki: dict = Depends(wiki_dep)):
    """Suggested issuer, edition and part for a file, read from its opening pages, for the user to confirm before upload."""
    s = get_settings()
    data = await file.read()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Max upload is {s.max_upload_mb} MB")
    name = file.filename or "upload.txt"
    try:
        opening = await asyncio.to_thread(extract.opening_text, name, data)
    except ValueError as e:
        raise HTTPException(415, str(e))
    if not opening.strip():
        return {"issuer": "", "edition": "", "part": ""}
    out = await llm.generate_json(prompts.MAINTAINER_SYSTEM, prompts.describe_prompt(name, opening), prompts.DESCRIBE_SCHEMA)
    return {k: (out.get(k) or "").strip() for k in ("issuer", "edition", "part")}


@router.post("/wikis/{w}/sources", status_code=202)
async def add_file(file: UploadFile, mode: Mode = MODE_Q, wiki: dict = Depends(wiki_dep),
                   issuer: str = Form(""), edition: str = Form(""), part: str = Form("")):
    """Upload a source file (.pdf, .docx, .md, .txt), with its issuer, edition and part as confirmed by the user.
    Ingest runs as a background job."""
    s = get_settings()
    data = await file.read()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Max upload is {s.max_upload_mb} MB")
    name = file.filename or "upload.txt"
    try:
        chk = checks.load(wiki.get("schema_md") or "")
        ex = await asyncio.to_thread(extract.from_upload, name, data, s.section_words, checks.example_label_re(chk) if chk else None,
                                       checks.stub_re(chk))
    except ValueError as e:
        raise HTTPException(415, str(e))
    if document := {k: v.strip() for k, v in (("issuer", issuer), ("edition", edition), ("part", part)) if v.strip()}:
        ex.meta["document"] = document
    return await _start(wiki, ex, name, mode, file=(name, data))


async def attach_file(source_id, path: str, data: bytes, name: str) -> dict | None:
    rec = await storage.put(path, data, storage.content_type(name))
    if rec:
        async with get_pool().connection() as conn:
            await conn.execute("update wiki.sources set meta = meta || jsonb_build_object('file', %s::jsonb) where id = %s",
                               (Jsonb(rec), source_id))
    return rec


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
                """select id, slug, title, kind, uri, meta, meta->'file' as file, length(text) as chars, created_at
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


@router.get("/wikis/{w}/sources/{slug}/file")
async def source_file(slug: str, wiki: dict = Depends(wiki_dep)):
    """A short-lived link to the original uploaded file."""
    async with get_pool().connection() as conn:
        row = await (
            await conn.execute("select meta->'file' as file from wiki.sources where wiki_id = %s and slug = %s", (wiki["id"], slug))
        ).fetchone()
    if not row:
        raise HTTPException(404, "Source not found")
    if not row["file"]:
        raise HTTPException(404, "No original file is stored for this source")
    if not storage.enabled():
        raise HTTPException(503, "File storage is not configured (SUPABASE_SECRET_KEY)")
    try:
        url = await storage.signed_url(row["file"])
    except httpx.HTTPError as e:
        raise HTTPException(502, f"File storage error: {e}")
    return {"url": url, "name": row["file"]["path"].rsplit("/", 1)[-1], "content_type": row["file"]["content_type"]}


@router.delete("/wikis/{w}/sources/{slug}", status_code=204)
async def delete_source(slug: str, wiki: dict = Depends(wiki_dep)):
    """Remove a raw source and its stored file (pages built from it are kept; use lint to find unsourced pages)."""
    async with get_pool().connection() as conn:
        row = await (
            await conn.execute("delete from wiki.sources where wiki_id = %s and slug = %s returning meta->'file' as file",
                               (wiki["id"], slug))
        ).fetchone()
        if not row:
            raise HTTPException(404, "Source not found")
    await storage.remove(row["file"])
