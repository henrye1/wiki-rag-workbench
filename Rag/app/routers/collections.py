"""Collections: independent sets of documents. Each question searches one collection (like a wiki for the Wiki API)."""
from fastapi import APIRouter, HTTPException
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field

from .. import storage
from ..db import get_pool

router = APIRouter(tags=["collections"])
SLUG = r"^[a-z0-9][a-z0-9-]{1,62}$"


class CollectionIn(BaseModel):
    slug: str = Field(pattern=SLUG)
    name: str = Field(min_length=1)
    description: str = ""


class CollectionPatch(BaseModel):
    slug: str | None = Field(None, pattern=SLUG)
    name: str | None = Field(None, min_length=1)
    description: str | None = None


async def collection_dep(c: str) -> dict:
    """The collection named in the path (by slug), or 404."""
    async with get_pool().connection() as conn:
        row = await (await conn.execute("select * from collections where slug = %s", (c,))).fetchone()
    if not row:
        raise HTTPException(404, f"Collection '{c}' not found")
    return row


@router.get("/collections")
async def list_collections():
    async with get_pool().connection() as conn:
        return await (
            await conn.execute(
                """select c.id, c.slug, c.name, c.description, c.created_at,
                          count(distinct d.id) as documents, count(ch.id) as chunks
                   from collections c
                   left join documents d on d.collection_id = c.id
                   left join chunks ch on ch.document_id = d.id
                   group by c.id order by c.created_at"""
            )
        ).fetchall()


@router.post("/collections", status_code=201)
async def create_collection(body: CollectionIn):
    try:
        async with get_pool().connection() as conn:
            return await (
                await conn.execute(
                    "insert into collections (slug, name, description) values (%s, %s, %s) returning *",
                    (body.slug, body.name, body.description),
                )
            ).fetchone()
    except UniqueViolation:
        raise HTTPException(409, f"A collection with slug '{body.slug}' already exists")


@router.patch("/collections/{c}")
async def update_collection(c: str, body: CollectionPatch):
    """Rename a collection (name, description and/or slug). Its documents stay in it."""
    col = await collection_dep(c)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        return col
    sets = ", ".join(f"{k} = %({k})s" for k in fields)
    try:
        async with get_pool().connection() as conn:
            return await (
                await conn.execute(f"update collections set {sets} where id = %(id)s returning *", {**fields, "id": col["id"]})
            ).fetchone()
    except UniqueViolation:
        raise HTTPException(409, f"A collection with slug '{fields['slug']}' already exists")


@router.delete("/collections/{c}", status_code=204)
async def delete_collection(c: str):
    """Delete a collection with all its documents, their chunks and their stored files."""
    col = await collection_dep(c)
    async with get_pool().connection() as conn:
        files = await (
            await conn.execute("select file from documents where collection_id = %s and file is not null", (col["id"],))
        ).fetchall()
        await conn.execute("delete from collections where id = %s", (col["id"],))  # cascades to documents and chunks
    for f in files:
        await storage.remove(f["file"])
