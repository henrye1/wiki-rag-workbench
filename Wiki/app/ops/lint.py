"""Lint: structural checks (SQL), optional LLM health-check, optional fixes as a changeset."""
import re
from uuid import UUID

from .. import llm, prompts
from ..config import get_settings
from ..db import get_pool
from ..jobs import JobContext
from ..wiki import search, store
from ..wiki.store import Op, slugify

EXEMPT_ORPHAN = ("overview",)


async def structural(wiki_id: UUID) -> dict:
    async with get_pool().connection() as conn:
        async def q(sql):
            return await (await conn.execute(sql, {"w": wiki_id})).fetchall()

        broken = await q(
            """select l.to_slug as slug, array_agg(p.slug order by p.slug) as linked_from
               from wiki.links l join wiki.pages p on p.id = l.from_page_id
               where l.wiki_id = %(w)s and not exists (select 1 from wiki.pages x where x.wiki_id = %(w)s and x.slug = l.to_slug)
               group by l.to_slug order by count(*) desc"""
        )
        orphans = await q(
            """select p.slug, p.title from wiki.pages p
               where p.wiki_id = %(w)s and p.slug <> 'overview'
                 and not exists (select 1 from wiki.links l where l.wiki_id = %(w)s and l.to_slug = p.slug and l.from_page_id <> p.id)
               order by p.slug"""
        )
        missing_meta = await q(
            """select slug, (summary = '') as no_summary, (cardinality(tags) = 0) as no_tags
               from wiki.pages where wiki_id = %(w)s and (summary = '' or cardinality(tags) = 0) order by slug"""
        )
        thin = await q(
            """select slug, array_length(regexp_split_to_array(trim(content_md), '\\s+'), 1) as words
               from wiki.pages where wiki_id = %(w)s
                 and coalesce(array_length(regexp_split_to_array(trim(content_md), '\\s+'), 1), 0) < 40 order by slug"""
        )
        unsourced = await q(
            """select p.slug from wiki.pages p
               where p.wiki_id = %(w)s and p.type not in ('overview', 'synthesis', 'source')
                 and not exists (select 1 from wiki.page_sources ps where ps.page_id = p.id)
                 and p.content_md not like '%%[[source-%%' order by p.slug"""
        )
        titles = await q("select slug, lower(title) as t from wiki.pages where wiki_id = %(w)s")

    norm: dict[str, list[str]] = {}
    for r in titles:
        key = re.sub(r"[^a-z0-9]", "", re.sub(r"s\b", "", r["t"]))
        norm.setdefault(key, []).append(r["slug"])
    duplicates = [v for v in norm.values() if len(v) > 1]
    return {
        "broken_links": broken,
        "orphans": orphans,
        "missing_metadata": missing_meta,
        "thin_pages": thin,
        "unsourced_pages": unsourced,
        "possible_duplicates": duplicates,
    }


def _batches(pages: list[dict], size: int) -> list[list[dict]]:
    return [pages[i : i + size] for i in range(0, len(pages), size)]


async def llm_check(wiki: dict, ctx: JobContext) -> dict:
    s = get_settings()
    pages = await store.list_pages(wiki["id"], with_content=True)
    index = await store.compact_index(wiki["id"])
    batches = _batches(pages, s.lint_batch_pages)
    await ctx.progress(stage="llm", batches=len(batches))
    results = await llm.gather_limited(
        llm.generate_json(
            prompts.MAINTAINER_SYSTEM,
            prompts.with_schema(wiki["schema_md"], prompts.lint_prompt(
                "\n\n".join(f"<page slug=\"{p['slug']}\" title=\"{p['title']}\">\n{p['content_md']}\n</page>" for p in b), index
            )),
            prompts.LINT_SCHEMA,
        )
        for b in batches
    )
    merged = {k: [] for k in prompts.LINT_SCHEMA["required"]}
    for r in results:
        for k in merged:
            merged[k].extend(r.get(k, []))
    existing = {p["slug"] for p in pages}
    seen = set()
    merged["missing_pages"] = [
        m for m in merged["missing_pages"]
        if (sl := slugify(m["slug"])) not in existing and not (sl in seen or seen.add(sl))
    ]
    merged["missing_links"] = [
        m for m in merged["missing_links"] if m["from_slug"] in existing and m["to_slug"] in existing and m["from_slug"] != m["to_slug"]
    ]
    return merged


async def _mentions(wiki_id: UUID, slugs: list[str], term: str) -> str:
    pages = await store.get_pages(wiki_id, slugs)
    if not pages:
        pages = [await store.get_page(wiki_id, h["slug"]) for h in await search.search_pages(wiki_id, term, 4)]
    return "\n\n".join(f"<page slug=\"{p['slug']}\">\n{p['content_md']}\n</page>" for p in pages if p)


async def fix(wiki: dict, report: dict, llm_report: dict | None, ctx: JobContext, mode: str) -> dict:
    s = get_settings()
    wiki_id, schema = wiki["id"], wiki["schema_md"]
    index = await store.compact_index(wiki_id)
    system = prompts.MAINTAINER_SYSTEM

    # New pages: broken link targets + LLM-suggested missing pages (skip singular/plural variants of existing/queued slugs)
    def key(slug: str) -> str:
        return re.sub(r"(es|s)$", "", slug)

    taken = {key(p["slug"]) for p in await store.list_pages(wiki_id)}
    new_pages: dict[str, dict] = {}

    def queue(slug: str, info: dict):
        if key(slug) not in taken:
            taken.add(key(slug))
            new_pages[slug] = info

    for b in report["broken_links"]:
        queue(b["slug"], {"title": b["slug"].replace("-", " ").title(), "type": "concept", "mentioned_in": b["linked_from"],
                          "reason": "Linked from other pages but does not exist"})
    for m in (llm_report or {}).get("missing_pages", []):
        queue(slugify(m["slug"]), m)
    new_items = list(new_pages.items())[: s.max_pages_per_ingest]
    linkable = index + "\n" + "\n".join(f"{k} | {v['type']} | {v['title']} (being written now)" for k, v in new_items)

    async def write_new(slug, info):
        out = await llm.generate_json(
            system,
            prompts.with_schema(schema, prompts.write_page_prompt(
                slug=slug, title=info["title"], ptype=info["type"],
                focus=f"{info['reason']}. Write the page from what the wiki already says; keep claims attributed to their sources.",
                existing_md=None, material=await _mentions(wiki_id, info.get("mentioned_in", []), info["title"]),
                linkable=linkable, source_slug=None,
            )),
            prompts.PAGE_SCHEMA,
        )
        return Op(op="create", slug=slug, title=out["title"], type=info["type"], summary=out["summary"],
                  content_md=out["content_md"], tags=out["tags"], change_note=f"Lint fix: {info['reason']}")

    # Link additions: LLM missing_links + orphans (linked from their best related page)
    add: dict[str, set[str]] = {}
    for m in (llm_report or {}).get("missing_links", []):
        add.setdefault(m["from_slug"], set()).add(m["to_slug"])
    for o in report["orphans"]:
        hits = [h for h in await search.search_pages(wiki_id, o["title"], 3) if h["slug"] != o["slug"]]
        add.setdefault(hits[0]["slug"] if hits else "overview", set()).add(o["slug"])

    async def add_links(slug, targets):
        page = await store.get_page(wiki_id, slug)
        if not page:
            return None
        tlist = "\n".join(f"[[{t}]]" for t in sorted(targets))
        out = await llm.generate_json(system, prompts.add_links_prompt(slug, page["content_md"], tlist), prompts.PAGE_SCHEMA)
        return Op(op="update", slug=slug, title=page["title"], type=page["type"], summary=page["summary"] or out["summary"],
                  content_md=out["content_md"], tags=page["tags"] or out["tags"], base_version=page["version"],
                  change_note=f"Lint fix: add links to {', '.join(sorted(targets))}")

    link_items = list(add.items())[: s.max_pages_per_ingest]
    await ctx.progress(stage="fix", new_pages=len(new_items), link_edits=len(link_items))
    ops = await llm.gather_limited(
        [write_new(k, v) for k, v in new_items] + [add_links(k, v) for k, v in link_items]
    )
    ops = [o for o in ops if o]
    return await store.commit(wiki_id, "lint", "Lint fixes", ops, mode, job_id=ctx.id)


async def run(ctx: JobContext, wiki: dict, use_llm: bool, do_fix: bool, mode: str) -> dict:
    await ctx.progress(stage="structural")
    report = await structural(wiki["id"])
    llm_report = await llm_check(wiki, ctx) if use_llm else None
    result = {"structural": report, "llm": llm_report}
    if do_fix:
        result["fix"] = await fix(wiki, report, llm_report, ctx, mode)
    counts = {k: len(v) for k, v in report.items()}
    detail = "Structural: " + ", ".join(f"{k}={v}" for k, v in counts.items())
    if llm_report:
        detail += "\nLLM: " + ", ".join(f"{k}={len(v)}" for k, v in llm_report.items())
    if do_fix:
        detail += f"\nFix: {result['fix'].get('status')}"
    await store.add_log(wiki["id"], "lint", "Lint" + (" + LLM" if use_llm else "") + (" + fix" if do_fix else ""), detail)
    return result
