from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile

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
            """select d.id, d.filename, d.parser, d.created_at, count(c.id) as chunks
               from documents d left join chunks c on c.document_id = d.id
               group by d.id order by d.created_at desc"""
        )
        return await cur.fetchall()


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(doc_id: UUID):
    async with get_pool().connection() as conn:
        cur = await conn.execute("delete from documents where id = %s", (doc_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Not found")
