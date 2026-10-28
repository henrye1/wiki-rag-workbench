"""Retitle a source: its new title gives it a new slug (as an upload would), and every link and citation to it moves to
that slug word for word; its source page moves with it. The page text otherwise stays as it is."""
import re

from ..db import get_pool
from ..wiki import store
from ..wiki.store import Op, slugify


def _relink(md: str, old: str, new: str) -> str:
    """The text with each link to old ([[old]], [[old|label]], [[old#part|label]]) pointing to new instead."""
    return re.sub(r"\[\[" + re.escape(old) + r"(?=[\]|#])", "[[" + new, md)


async def retitle(wiki: dict, old_slug: str, title: str) -> dict:
    title = " ".join(title.split())
    base = "source-" + slugify(title)[:60]
    async with get_pool().connection() as conn:
        src = await (await conn.execute("select id, slug, title from wiki.sources where wiki_id = %s and slug = %s",
                                        (wiki["id"], old_slug))).fetchone()
        if not src:
            raise KeyError(old_slug)
        taken = {r["slug"] for r in await (await conn.execute(
            "select slug from wiki.sources where wiki_id = %s and slug like %s and slug <> %s "
            "union select slug from wiki.pages where wiki_id = %s and slug like %s and slug <> %s",
            (wiki["id"], base + "%", old_slug, wiki["id"], base + "%", old_slug))).fetchall()}
        new_slug, n = base, 2
        while new_slug in taken:
            new_slug, n = f"{base}-{n}", n + 1
        await conn.execute("update wiki.sources set slug = %s, title = %s where id = %s", (new_slug, title, src["id"]))
    pages = await store.list_pages(wiki["id"], with_content=True)
    ops, moved = [], 0
    for p in pages:
        md = _relink(p["content_md"], old_slug, new_slug)
        n = len(re.findall(r"\[\[" + re.escape(old_slug) + r"(?=[\]|#])", p["content_md"]))
        if p["slug"] == old_slug:  # the source page: under its new slug and title
            ops += [Op(op="create", slug=new_slug, title=title, type=p["type"], summary=p["summary"], content_md=md,
                       tags=p["tags"] or [], change_note=f"Source retitled: {src['title']} -> {title}"),
                    Op(op="delete", slug=old_slug, base_version=p["version"], change_note=f"Moved to [[{new_slug}]]")]
        elif n:
            ops.append(Op(op="update", slug=p["slug"], title=p["title"], type=p["type"], summary=p["summary"], content_md=md,
                          tags=p["tags"] or [], base_version=p["version"],
                          change_note=f"Citations of {src['title']} now name it {title}"))
        moved += n
    res = await store.commit(wiki["id"], "edit", f"Retitle source: {src['title']} -> {title}", ops, "auto")
    return {"from": old_slug, "to": new_slug, "title": title, "links_moved": moved, "pages_changed": len(ops), **res}
