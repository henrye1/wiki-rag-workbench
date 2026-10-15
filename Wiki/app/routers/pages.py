from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db import get_pool
from ..wiki import saved, store
from ..wiki.store import PAGE_TYPES, Op
from .deps import wiki_dep

router = APIRouter(tags=["pages"])


class PageIn(BaseModel):
    title: str
    type: str = Field("concept", description=f"One of: {', '.join(PAGE_TYPES)}")
    summary: str = ""
    content_md: str
    tags: list[str] = []
    base_version: int | None = Field(None, description="Version you edited; 409 if the page changed since")
    change_note: str = "Manual edit"


async def _saved_and_flags(wiki_id) -> tuple[set[str], dict[str, dict]]:
    async with get_pool().connection() as conn:
        return {r["slug"] for r in await saved.saved_answers(conn, wiki_id)}, await saved.flags(conn, wiki_id)


@router.get("/wikis/{w}/pages")
async def list_pages(wiki: dict = Depends(wiki_dep)):
    keep, flags = await _saved_and_flags(wiki["id"])
    return [{**p, "saved_answer": p["slug"] in keep, "needs_checking": flags.get(p["slug"])} for p in await store.list_pages(wiki["id"])]


async def _page_or_404(wiki: dict, slug: str) -> dict:
    page = await store.get_page(wiki["id"], slug)
    if not page:
        raise HTTPException(404, "Page not found")
    return page


@router.get("/wikis/{w}/pages/{slug}")
async def get_page(slug: str, wiki: dict = Depends(wiki_dep)):
    page = await _page_or_404(wiki, slug)
    keep, flags = await _saved_and_flags(wiki["id"])
    return {**page, "backlinks": await store.backlinks(wiki["id"], slug), "sources": await store.page_sources(page["id"]),
            "saved_answer": slug in keep, "needs_checking": flags.get(slug)}


@router.delete("/wikis/{w}/pages/{slug}/needs-checking", status_code=204)
async def mark_checked(slug: str, wiki: dict = Depends(wiki_dep)):
    """Clear a saved answer's "needs checking" flag once it has been checked."""
    page = await _page_or_404(wiki, slug)
    async with get_pool().connection() as conn:
        await conn.execute("delete from wiki.page_flags where page_id = %s and kind = 'needs_checking'", (page["id"],))


@router.put("/wikis/{w}/pages/{slug}")
async def put_page(slug: str, body: PageIn, wiki: dict = Depends(wiki_dep)):
    """Manual create/edit (applied immediately, versioned)."""
    if body.type not in PAGE_TYPES:
        raise HTTPException(422, f"type must be one of {PAGE_TYPES}")
    slug = store.slugify(slug)
    page = await store.get_page(wiki["id"], slug)
    if page and body.base_version is not None and body.base_version != page["version"]:
        raise HTTPException(409, f"Page is at version {page['version']}")
    op = Op(op="update" if page else "create", slug=slug, title=body.title, type=body.type, summary=body.summary,
            content_md=body.content_md, tags=body.tags, base_version=page["version"] if page else None, change_note=body.change_note)
    res = await store.commit(wiki["id"], "edit", f"Manual edit: {slug}", [op], "auto")
    return res


@router.delete("/wikis/{w}/pages/{slug}", status_code=204)
async def delete_page(slug: str, wiki: dict = Depends(wiki_dep)):
    page = await _page_or_404(wiki, slug)
    await store.commit(wiki["id"], "edit", f"Delete: {slug}", [Op(op="delete", slug=slug, base_version=page["version"])], "auto")


@router.get("/wikis/{w}/pages/{slug}/versions")
async def versions(slug: str, wiki: dict = Depends(wiki_dep)):
    page = await _page_or_404(wiki, slug)
    async with get_pool().connection() as conn:
        return await (
            await conn.execute(
                """select version, title, summary, change_note, job_id, created_at, length(content_md) as chars
                   from wiki.page_versions where page_id = %s order by version desc""",
                (page["id"],),
            )
        ).fetchall()


@router.get("/wikis/{w}/pages/{slug}/versions/{version}")
async def get_version(slug: str, version: int, wiki: dict = Depends(wiki_dep)):
    page = await _page_or_404(wiki, slug)
    async with get_pool().connection() as conn:
        row = await (
            await conn.execute("select * from wiki.page_versions where page_id = %s and version = %s", (page["id"], version))
        ).fetchone()
    if not row:
        raise HTTPException(404, "Version not found")
    return row


@router.post("/wikis/{w}/pages/{slug}/revert/{version}")
async def revert(slug: str, version: int, wiki: dict = Depends(wiki_dep)):
    """Restore an old version as a new version."""
    old = await get_version(slug, version, wiki)
    page = await store.get_page(wiki["id"], slug)
    op = Op(op="update", slug=slug, title=old["title"], type=old["type"], summary=old["summary"], content_md=old["content_md"],
            tags=old["tags"], base_version=page["version"], change_note=f"Revert to v{version}")
    res = await store.commit(wiki["id"], "edit", f"Revert {slug} to v{version}", [op], "auto")
    await store.add_log(wiki["id"], "revert", f"{slug} → v{version}")
    return res
