import io
import pathlib
import zipfile

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field

from .. import storage
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
    """The wiki, with its state: page count and its latest applied change (a benchmark run records it)."""
    async with get_pool().connection() as conn:
        state = await (await conn.execute(
            """select (select count(*) from wiki.pages where wiki_id = %(w)s) as pages,
                      (select count(*) from wiki.sources where wiki_id = %(w)s) as sources,
                      c.id::text as last_change_id, c.applied_at as last_change_at
               from (select 1) x left join lateral (select id, applied_at from wiki.changesets
                     where wiki_id = %(w)s and status = 'applied' order by applied_at desc limit 1) c on true""",
            {"w": wiki["id"]})).fetchone()
    return {**wiki, **state}


@router.delete("/wikis/{w}", status_code=204)
async def delete_wiki(wiki: dict = Depends(wiki_dep)):
    """Delete a wiki with everything in it, including its sources' stored files."""
    async with get_pool().connection() as conn:
        files = await (
            await conn.execute("select meta->'file' as file from wiki.sources where wiki_id = %s and meta ? 'file'", (wiki["id"],))
        ).fetchall()
        await conn.execute("delete from wiki.wikis where id = %s", (wiki["id"],))
    for f in files:
        await storage.remove(f["file"])


@router.get("/wikis/{w}/schema", response_class=PlainTextResponse)
async def get_schema(wiki: dict = Depends(wiki_dep)):
    return wiki["schema_md"]


@router.put("/wikis/{w}/schema")
async def put_schema(body: SchemaIn, wiki: dict = Depends(wiki_dep)):
    async with get_pool().connection() as conn:
        await conn.execute("update wiki.wikis set schema_md = %s where id = %s", (body.schema_md, wiki["id"]))
    await store.add_log(wiki["id"], "edit", "Schema updated")
    return {"ok": True}


@router.get("/wikis/{w}/graph")
async def graph(wiki: dict = Depends(wiki_dep)):
    """Nodes (pages + missing link targets) and edges (wiki links) for graph views."""
    async with get_pool().connection() as conn:
        pages = await (
            await conn.execute("select id, slug, title, type, summary from wiki.pages where wiki_id = %s", (wiki["id"],))
        ).fetchall()
        links = await (
            await conn.execute(
                """select p.slug as source, l.to_slug as target from wiki.links l
                   join wiki.pages p on p.id = l.from_page_id where l.wiki_id = %s and p.slug <> l.to_slug""",
                (wiki["id"],),
            )
        ).fetchall()
    existing = {p["slug"] for p in pages}
    inbound: dict[str, int] = {}
    outbound: dict[str, int] = {}
    for e in links:
        inbound[e["target"]] = inbound.get(e["target"], 0) + 1
        outbound[e["source"]] = outbound.get(e["source"], 0) + 1
    nodes = [
        {"id": p["slug"], "title": p["title"], "type": p["type"], "summary": p["summary"], "missing": False,
         "inbound": inbound.get(p["slug"], 0), "outbound": outbound.get(p["slug"], 0),
         "orphan": p["slug"] != "overview" and inbound.get(p["slug"], 0) == 0}
        for p in pages
    ]
    nodes += [
        {"id": s, "title": s, "type": "missing", "summary": "", "missing": True, "inbound": inbound[s], "outbound": 0, "orphan": False}
        for s in sorted(set(inbound) - existing)
    ]
    return {"nodes": nodes, "edges": links}


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
