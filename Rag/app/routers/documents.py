from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, UploadFile

from .. import storage
from ..db import get_pool
from ..ingest.pipeline import DuplicateDocument, ingest

router = APIRouter(tags=["documents"])
ALLOWED = (".pdf", ".txt", ".md")


@router.post("/ingest", status_code=201)
async def ingest_file(file: UploadFile):
    name = file.filename or "upload"
    if not name.lower().endswith(ALLOWED):
        raise HTTPException(415, f"Supported: {', '.join(ALLOWED)}")
    try:
        return await ingest(name, await file.read())
    except DuplicateDocument as e:
        raise HTTPException(409, {"message": "Document already ingested", "document_id": str(e.doc_id)})
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/documents")
async def list_documents():
    async with get_pool().connection() as conn:
        cur = await conn.execute(
            """select d.id, d.filename, d.parser, d.created_at, d.file is not null as has_file, count(c.id) as chunks
               from documents d left join chunks c on c.document_id = d.id
               group by d.id order by d.created_at desc"""
        )
        return await cur.fetchall()


@router.get("/chunks")
async def get_chunks(para_ref: str, document_id: UUID | None = None, include_notes: bool = False):
    """Look up chunks by IFRS paragraph reference (e.g. 5.5.3, B5.5.17, 'Appendix A: credit loss') - used by citation viewers."""
    async with get_pool().connection() as conn:
        cur = await conn.execute(
            """select c.id, c.para_ref, c.part, c.source_type, c.page, c.heading, c.content, d.filename, d.id as document_id
               from chunks c join documents d on d.id = c.document_id
               where c.para_ref = %s and (%s::uuid is null or c.document_id = %s)
                 and (%s or c.source_type <> 'note')
               order by d.created_at, c.source_type <> 'note' desc, c.part""",
            (para_ref, document_id, document_id, include_notes),
        )
        rows = await cur.fetchall()
    if not rows:
        raise HTTPException(404, f"No chunk with para_ref '{para_ref}'")
    return rows


@router.get("/documents/{doc_id}/file")
async def document_file(doc_id: UUID):
    """A short-lived link to the original uploaded file."""
    async with get_pool().connection() as conn:
        row = await (await conn.execute("select file from documents where id = %s", (doc_id,))).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    if not row["file"]:
        raise HTTPException(404, "No original file is stored for this document")
    if not storage.enabled():
        raise HTTPException(503, "File storage is not configured (SUPABASE_SECRET_KEY)")
    try:
        url = await storage.signed_url(row["file"])
    except httpx.HTTPError as e:
        raise HTTPException(502, f"File storage error: {e}")
    return {"url": url, "name": row["file"]["path"].rsplit("/", 1)[-1], "content_type": row["file"]["content_type"]}


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(doc_id: UUID):
    async with get_pool().connection() as conn:
        row = await (await conn.execute("delete from documents where id = %s returning file", (doc_id,))).fetchone()
        if not row:
            raise HTTPException(404, "Not found")
    await storage.remove(row["file"])
