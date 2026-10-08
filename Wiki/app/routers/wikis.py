import io
import pathlib
import zipfile

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field

from ..db import get_pool
from ..wiki import store
from .deps import wiki_dep

router = APIRouter(tags=["wikis"])
DEFAULT_SCHEMA = (pathlib.Path(__file__).resolve().parent.parent / "schema_default.md").read_text(encoding="utf-8")


class WikiIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str
    description: str = ""
    schema_md: str | None = Field(None, description="Conventions doc; defaults to the built-in generic schema")


class SchemaIn(BaseModel):
    schema_md: str = Field(min_length=20)


@router.post("/wikis", status_code=201)
async def create_wiki(body: WikiIn):
    try:
        async with get_pool().connection() as conn:
            row = await (
                await conn.execute(
                    "insert into wiki.wikis (slug, name, description, schema_md) values (%s,%s,%s,%s) returning *",
                    (body.slug, body.name, body.description, body.schema_md or DEFAULT_SCHEMA),
                )
            ).fetchone()
    except UniqueViolation:
        raise HTTPException(409, "Wiki slug already exists")
    await store.add_log(row["id"], "edit", "Wiki created", body.description)
    return row


@router.get("/wikis")
async def list_wikis():
    async with get_pool().connection() as conn:
        return await (
            await conn.execute(
                """select w.id, w.slug, w.name, w.description, w.created_at,
                          (select count(*) from wiki.pages p where p.wiki_id = w.id) as pages,
                          (select count(*) from wiki.sources s where s.wiki_id = w.id) as sources
                   from wiki.wikis w order by w.created_at"""
            )
        ).fetchall()


@router.get("/wikis/{w}")
async def get_wiki(wiki: dict = Depends(wiki_dep)):
    return wiki


@router.delete("/wikis/{w}", status_code=204)
async def delete_wiki(wiki: dict = Depends(wiki_dep)):
    async with get_pool().connection() as conn:
        await conn.execute("delete from wiki.wikis where id = %s", (wiki["id"],))


@router.get("/wikis/{w}/schema", response_class=PlainTextResponse)
async def get_schema(wiki: dict = Depends(wiki_dep)):
    return wiki["schema_md"]


@router.put("/wikis/{w}/schema")
async def put_schema(body: SchemaIn, wiki: dict = Depends(wiki_dep)):
    async with get_pool().connection() as conn:
        await conn.execute("update wiki.wikis set schema_md = %s where id = %s", (body.schema_md, wiki["id"]))
    await store.add_log(wiki["id"], "edit", "Schema updated")
    return {"ok": True}


@router.get("/wikis/{w}/index.md", response_class=PlainTextResponse)
async def index_md(wiki: dict = Depends(wiki_dep)):
    return await store.render_index(wiki)


@router.get("/wikis/{w}/log.md", response_class=PlainTextResponse)
async def log_md(wiki: dict = Depends(wiki_dep)):
    return await store.render_log(wiki)


def _front(meta: dict) -> str:
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n"


@router.get("/wikis/{w}/export.zip")
async def export_zip(wiki: dict = Depends(wiki_dep)):
    """Obsidian-compatible vault: pages/<slug>.md, sources/<slug>.md, index.md, log.md, SCHEMA.md."""
    pages = await store.list_pages(wiki["id"], with_content=True)
    async with get_pool().connection() as conn:
        sources = await (await conn.execute("select * from wiki.sources where wiki_id = %s", (wiki["id"],))).fetchall()
        ps = await (
            await conn.execute(
                """select ps.page_id, s.slug from wiki.page_sources ps join wiki.sources s on s.id = ps.source_id
                   where s.wiki_id = %s""",
                (wiki["id"],),
            )
        ).fetchall()
    page_src: dict = {}
    for r in ps:
        page_src.setdefault(r["page_id"], []).append(r["slug"])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        root = wiki["slug"]
        z.writestr(f"{root}/index.md", await store.render_index(wiki))
        z.writestr(f"{root}/log.md", await store.render_log(wiki, limit=100000))
        z.writestr(f"{root}/SCHEMA.md", wiki["schema_md"])
        for p in pages:
            meta = {"title": p["title"], "type": p["type"], "summary": p["summary"], "tags": list(p["tags"]),
                    "version": p["version"], "updated": p["updated_at"].isoformat(), "sources": page_src.get(p["id"], [])}
            z.writestr(f"{root}/pages/{p['slug']}.md", _front(meta) + f"# {p['title']}\n\n{p['content_md']}\n")
        for s in sources:
            meta = {"title": s["title"], "kind": s["kind"], "uri": s["uri"], "added": s["created_at"].isoformat()}
            # Raw source text; the wiki's source *page* is pages/<slug>.md
            z.writestr(f"{root}/raw/{s['slug']}.txt", s["text"])
            z.writestr(f"{root}/raw/{s['slug']}.meta.yaml", yaml.safe_dump(meta, sort_keys=False, allow_unicode=True))
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{wiki["slug"]}-wiki.zip"'}
    )
