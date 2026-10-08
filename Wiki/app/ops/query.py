"""Query: index + hybrid search -> read pages -> cited answer; optionally file the answer back as a synthesis page."""
from collections.abc import AsyncIterator

from .. import llm, prompts
from ..config import get_settings
from ..wiki import search, store
from ..wiki.store import Op, slugify


async def _select_pages(wiki: dict, question: str) -> list[dict]:
    s = get_settings()
    wiki_id = wiki["id"]
    hits = await search.search_pages(wiki_id, question, s.query_top_k)
    index = await store.compact_index(wiki_id)
    picked = await llm.generate_json(
        prompts.MAINTAINER_SYSTEM, prompts.select_prompt(question, index, s.query_max_pages), prompts.SELECT_SCHEMA
    )
    order: list[str] = []
    for slug in [h["slug"] for h in hits[:5]] + [slugify(x) for x in picked["slugs"]]:
        if slug not in order:
            order.append(slug)
    pages = {p["slug"]: p for p in await store.get_pages(wiki_id, order[: s.query_max_pages + 5])}
    return [pages[x] for x in order if x in pages]


def _pages_md(pages: list[dict]) -> str:
    return "\n\n".join(f"<page slug=\"{p['slug']}\" title=\"{p['title']}\" type=\"{p['type']}\">\n{p['content_md']}\n</page>" for p in pages)


def _cited(answer: str, pages: list[dict]) -> list[dict]:
    linked = store.extract_links(answer)
    return [{"slug": p["slug"], "title": p["title"], "cited": p["slug"] in linked} for p in pages]


async def answer(wiki: dict, question: str, save: bool = False, mode: str = "auto") -> dict:
    pages = await _select_pages(wiki, question)
    if not pages:
        text = "The wiki has no pages relevant to this question yet."
    else:
        text = await llm.generate(prompts.QUERY_SYSTEM, prompts.query_prompt(question, _pages_md(pages)))
    result = {"answer": text, "pages": _cited(text, pages)}
    saved = await save_answer(wiki, question, text, mode) if save and pages else None
    if saved:
        result["saved"] = saved
    await store.add_log(wiki["id"], "query", question[:200], "Pages read: " + ", ".join(f"[[{p['slug']}]]" for p in pages)
                        + (f"\n\nSaved as [[{saved['slug']}]] ({saved['status']})" if saved else ""))
    return result


async def stream_answer(wiki: dict, question: str) -> tuple[list[dict], AsyncIterator[str]]:
    pages = await _select_pages(wiki, question)
    await store.add_log(wiki["id"], "query", question[:200], "Pages read: " + ", ".join(f"[[{p['slug']}]]" for p in pages))
    return pages, llm.stream(prompts.QUERY_SYSTEM, prompts.query_prompt(question, _pages_md(pages)))


async def save_answer(wiki: dict, question: str, answer_md: str, mode: str) -> dict:
    wiki_id = wiki["id"]
    index = await store.compact_index(wiki_id)
    out = await llm.generate_json(
        prompts.MAINTAINER_SYSTEM,
        prompts.with_schema(wiki["schema_md"], prompts.save_answer_prompt(question, answer_md, index)),
        prompts.PAGE_SCHEMA,
    )
    base = slugify(out["title"])
    slug, n = base, 2
    while await store.get_page(wiki_id, slug):
        slug, n = f"{base}-{n}", n + 1
    op = Op(op="create", slug=slug, title=out["title"], type="synthesis", summary=out["summary"],
            content_md=out["content_md"], tags=out["tags"], change_note=f"Filed from query: {question[:150]}")
    res = await store.commit(wiki_id, "query", f"Save answer: {out['title']}", [op], mode)
    return {"slug": slug, "status": res["status"], "changeset_id": res.get("changeset_id")}
