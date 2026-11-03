"""Recompute summaries: every page's summary made again by the rules an upload uses (the schema's subtopic and page
summary rules), from the page text as it stands. No AI call is made and no page text changes. A changed summary is
saved as a new page version; the search index stays as it is, since a page's chunks are built from its text (a page
with no text is indexed by its summary, so a change there is left out and reported)."""
from ..db import get_pool
from ..wiki import checks, store
from .ingest import _sections, page_summaries

NOTE = "Summary recomputed (page text unchanged)"


async def recompute(wiki: dict, dry_run: bool = False) -> dict:
    chk = checks.load(wiki["schema_md"])
    pages = {p["slug"]: p for p in await store.list_pages(wiki["id"], with_content=True)}
    made = await page_summaries(wiki["id"], chk, _sections(wiki["schema_md"]), pages, list(pages))
    changed, skipped = [], []
    for sl, p in pages.items():
        if made[sl] == p["summary"]:
            continue
        item = {"slug": sl, "type": p["type"], "before": p["summary"], "after": made[sl]}
        if store._chunks(p["title"], p["summary"], p["content_md"]) != store._chunks(p["title"], made[sl], p["content_md"]):
            skipped.append({**item, "reason": "the page has no text, so its search index is built from its summary"})
        else:
            changed.append(item)
    if not dry_run and changed:
        async with get_pool().connection() as conn, conn.transaction():
            for c in changed:
                row = await (await conn.execute(
                    """update wiki.pages set summary = %s, version = version + 1, updated_at = now()
                       where wiki_id = %s and slug = %s and summary = %s returning id, version""",
                    (c["after"], wiki["id"], c["slug"], c["before"]))).fetchone()
                if not row:  # changed since it was read
                    c["conflict"] = True
                    continue
                await conn.execute(
                    """insert into wiki.page_versions (page_id, version, title, type, summary, content_md, tags, change_note)
                       select id, version, title, type, summary, content_md, tags, %s from wiki.pages where id = %s""",
                    (NOTE, row["id"]))
                c["version"] = row["version"]
            saved = [c for c in changed if not c.get("conflict")]
            await store.add_log(wiki["id"], "edit", f"Summaries recomputed: {len(saved)} changed",
                                "\n".join(f"- [[{c['slug']}]]" for c in saved), conn=conn)
    return {"dry_run": dry_run, "pages": len(pages), "changed": changed, "skipped": skipped}
