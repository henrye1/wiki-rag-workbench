"""Rebuild concept and entity pages (and the examples index's list of examples inside guidance) for a wiki as it
stands, by the schema's lists, as an upload does at its end. No AI call is made; only the search index of the pages
built is embedded. The pages are cleared and written again, so one whose concept has gone is deleted."""
from ..wiki import checks, store
from .ingest import _sections, composed_ops


async def rebuild(wiki: dict, dry_run: bool = False) -> dict:
    chk = checks.load(wiki["schema_md"])
    existing = {p["slug"]: p for p in await store.list_pages(wiki["id"], with_content=True)}
    ops, count = await composed_ops(wiki["id"], chk, _sections(wiki["schema_md"]), existing, [])
    out = {"count": count, "ops": [{"op": o.op, "slug": o.slug, "type": o.type} for o in ops]}
    if dry_run or not ops:
        return out | {"status": "dry run" if dry_run else "nothing to change"}
    res = await store.commit(wiki["id"], "edit", "Rebuild concept and entity pages", ops, "auto")
    return out | {"status": res["status"], "changeset_id": res.get("changeset_id")}
