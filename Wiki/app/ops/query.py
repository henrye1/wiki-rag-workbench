"""Query: index + hybrid search -> read pages -> cited answer; optionally file the answer back as a synthesis page.

Synthesis pages are never chosen as one of the pages for a question. Saved answers (synthesis pages filed with the
Save button) relevant to the question are read in addition, as earlier answers to check against those pages."""
import re
from collections.abc import AsyncIterator

from .. import llm, prompts
from ..config import get_settings
from ..db import get_pool
from ..wiki import citecheck, saved, search, store
from ..wiki.store import Op, slugify


async def _select_pages(wiki: dict, question: str) -> list[dict]:
    """The pages for a question: search top 5 + the AI's picks from the index. Synthesis pages are never among them."""
    s = get_settings()
    wiki_id = wiki["id"]
    synth = {p["slug"] for p in await store.list_pages(wiki_id) if p["type"] == "synthesis"}
    hits = await search.search_pages(wiki_id, question, s.query_top_k)
    if synth & {h["slug"] for h in hits[:5]}:  # look further so the top 5 are five other pages
        hits = await search.search_pages(wiki_id, question, s.query_top_k + len(synth))
    hits = [h for h in hits if h["slug"] not in synth]
    index = await store.compact_index(wiki_id, exclude_types=("synthesis",))
    picked = await llm.generate_json(
        prompts.MAINTAINER_SYSTEM, prompts.select_prompt(question, index, s.query_max_pages), prompts.SELECT_SCHEMA
    )
    order: list[str] = []
    for slug in [h["slug"] for h in hits[:5]] + [slugify(x) for x in picked["slugs"]]:
        if slug not in order and slug not in synth:
            order.append(slug)
    pages = {p["slug"]: p for p in await store.get_pages(wiki_id, order[: s.query_max_pages + 5])}
    return [pages[x] for x in order if x in pages]


async def _select_saved(wiki: dict, question: str) -> list[dict]:
    """Saved answers to the same or a closely related question (at most 2), read in addition to the pages."""
    async with get_pool().connection() as conn:
        rows = await saved.saved_answers(conn, wiki["id"], readable_only=True)
    if not rows:
        return []
    listing = "\n".join(f"{r['slug']} | {r['title']} | {r['summary']}" for r in rows)
    out = await llm.generate_json(prompts.MAINTAINER_SYSTEM, prompts.select_saved_prompt(question, listing), prompts.SELECT_SCHEMA)
    by = {r["slug"]: r for r in rows}
    return [{**by[x], "saved": True} for x in dict.fromkeys(slugify(x) for x in out["slugs"]) if x in by][:2]


# "Sources: Standard only": keep only statements cited to a Standard (Part A); a page can also hold material from
# documents published with it (Parts B and C), which cite their own sources
_SOURCE_CITE = re.compile(r"\[\[(source-[^\]|#]+)")
_STATEMENT = re.compile(r"(?:\[\[source-[^\]]+\]\][\s,;]*)+[.;:]?")  # a statement ends with its citation group
_HEADING = re.compile(r"^\s*#{1,6} ")


async def _standard_slugs(wiki_id) -> set[str]:
    """Sources read as a Standard (Part A) by the IFRS reader."""
    async with get_pool().connection() as conn:
        rows = await (await conn.execute("select slug from wiki.sources where wiki_id = %s and meta->>'parser' = 'ifrs'", (wiki_id,))).fetchall()
    return {r["slug"] for r in rows}


def standard_only(md: str, standard: set[str]) -> str:
    """The page text keeping headings and only the statements whose source citations are all to a Standard."""
    lines = []
    for line in md.split("\n"):
        if not line.strip() or _HEADING.match(line):
            lines.append(line)
            continue
        parts, pos = [], 0
        for m in _STATEMENT.finditer(line):
            parts.append(line[pos : m.end()])
            pos = m.end()
        kept = [p for p in parts if (cited := set(_SOURCE_CITE.findall(p))) and cited <= standard]
        if kept:
            lines.append("".join(kept).strip())
    out: list[str] = []  # drop headings left with nothing under them
    for i, line in enumerate(lines):
        if _HEADING.match(line):
            rest = next((x for x in lines[i + 1 :] if x.strip()), "")
            if not rest or (_HEADING.match(rest) and len(rest) - len(rest.lstrip("#")) <= len(line) - len(line.lstrip("#"))):
                continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


async def _restrict(wiki: dict, pages: list[dict], sources: str) -> list[dict]:
    if sources != "standard":
        return pages
    standard = await _standard_slugs(wiki["id"])
    out = []
    for p in pages:
        md = standard_only(p["content_md"], standard)
        if _SOURCE_CITE.search(md):
            out.append({**p, "content_md": md})
    return out


def _pages_md(pages: list[dict]) -> str:
    return "\n\n".join(
        f"<saved_answer slug=\"{p['slug']}\" title=\"{p['title']}\" saved=\"{p['updated_at']:%Y-%m-%d}\">\n{p['content_md']}\n</saved_answer>"
        if p.get("saved") else f"<page slug=\"{p['slug']}\" title=\"{p['title']}\" type=\"{p['type']}\">\n{p['content_md']}\n</page>"
        for p in pages)


def _cited(answer: str, pages: list[dict]) -> list[dict]:
    linked = store.extract_links(answer)
    return [{"slug": p["slug"], "title": p["title"], "cited": p["slug"] in linked, "saved": bool(p.get("saved"))} for p in pages]


async def _read(wiki: dict, question: str, sources: str, use_saved: bool) -> tuple[list[dict], list[dict]]:
    """The pages for the question and, if use_saved, the saved answers read with them (both under the Sources setting)."""
    pages = await _restrict(wiki, await _select_pages(wiki, question), sources)
    extra = await _restrict(wiki, await _select_saved(wiki, question), sources) if use_saved and pages else []
    return pages, extra


def _prompt(wiki: dict, question: str, pages: list[dict], extra: list[dict]) -> str:
    ask = prompts.query_prompt(question, _pages_md(pages)) if not extra else prompts.query_saved_prompt(question, _pages_md(pages), _pages_md(extra))
    return prompts.with_schema(wiki["schema_md"], ask)


async def answer(wiki: dict, question: str, save: bool = False, mode: str = "auto", sources: str = "all",
                 use_saved: bool = True) -> dict:
    pages, extra = await _read(wiki, question, sources, use_saved)
    if not pages:
        text = ("The wiki has no Standard (Part A) material relevant to this question." if sources == "standard"
                else "The wiki has no pages relevant to this question yet.")
    else:
        text = await llm.generate(prompts.QUERY_SYSTEM, _prompt(wiki, question, pages, extra))
    result = {"answer": text, "pages": _cited(text, pages + extra)}
    saved = await save_answer(wiki, question, text, mode) if save and pages else None
    if saved:
        result["saved"] = saved
    await store.add_log(wiki["id"], "query", question[:200], f"Sources: {sources}. Pages read: " + ", ".join(f"[[{p['slug']}]]" for p in pages)
                        + (". Saved answers read: " + ", ".join(f"[[{p['slug']}]]" for p in extra) if extra else "")
                        + (f"\n\nSaved as [[{saved['slug']}]] ({saved['status']})" if saved else ""))
    return result


async def stream_answer(wiki: dict, question: str, sources: str = "all", use_saved: bool = True) -> tuple[list[dict], AsyncIterator[str]]:
    pages, extra = await _read(wiki, question, sources, use_saved)
    await store.add_log(wiki["id"], "query", question[:200], f"Sources: {sources}. Pages read: " + ", ".join(f"[[{p['slug']}]]" for p in pages)
                        + (". Saved answers read: " + ", ".join(f"[[{p['slug']}]]" for p in extra) if extra else ""))
    return pages + extra, llm.stream(prompts.QUERY_SYSTEM, _prompt(wiki, question, pages, extra))


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
            content_md=out["content_md"], tags=list(dict.fromkeys([saved.SAVED_TAG, *out["tags"]])),
            change_note=f"Filed from query: {question[:150]}")
    citations = await citecheck.check_ops(wiki_id, [op])  # every citation must name a source that holds the clause
    res = await store.commit(wiki_id, "query", f"Save answer: {out['title']}", [op], mode)
    return {"slug": slug, "status": res["status"], "changeset_id": res.get("changeset_id"), "citations": citations}
