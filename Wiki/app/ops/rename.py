"""Retitle a source: its title changes, never its slug (the schema's slugs are stable). The source record and its source
page take the new title; the page keeps its slug, text and history, and every link and citation to it stays as it is."""
from ..db import get_pool
from ..wiki import store
from ..wiki.store import Op


async def retitle(wiki: dict, slug: str, title: str) -> dict:
    title = " ".join(title.split())
    async with get_pool().connection() as conn:
        src = await (await conn.execute("select id, slug, title from wiki.sources where wiki_id = %s and slug = %s",
                                        (wiki["id"], slug))).fetchone()
        if not src:
            raise KeyError(slug)
        await conn.execute("update wiki.sources set title = %s where id = %s", (title, src["id"]))
    page = await store.get_page(wiki["id"], slug)
    ops = [Op(op="update", slug=slug, title=title, type=page["type"], summary=page["summary"], content_md=page["content_md"],
              tags=page["tags"] or [], base_version=page["version"], change_note=f"Source retitled: {src['title']} -> {title}")] \
        if page and page["title"] != title else []
    res = await store.commit(wiki["id"], "edit", f"Retitle source: {src['title']} -> {title}", ops, "auto") if ops else {"status": "empty"}
    return {"from": slug, "to": slug, "title": title, "links_moved": 0, "pages_changed": len(ops), **res}
