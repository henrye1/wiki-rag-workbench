"""Lint: structural checks (SQL), the schema's Maintain checks it can run (Checks: Lint checks), an optional LLM
health-check, and optional fixes. Lint reports: a link it would add or remove is a proposal, with the page and the
link, and no page is changed for it. Saved answers are never its material."""
import re
from uuid import UUID

from .. import llm, prompts
from ..config import get_settings
from ..db import get_pool
from ..jobs import JobContext
from ..wiki import checks, store
from ..wiki.store import slugify
from . import fixpass, pagecheck

async def structural(wiki_id: UUID, chk: checks.Checks) -> dict:
    """The SQL checks. chk: the schema's Checks; a page holding only its Empty section text is not a thin page."""
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
            """select slug, content_md, array_length(regexp_split_to_array(trim(content_md), '\\s+'), 1) as words
               from wiki.pages where wiki_id = %(w)s
                 and coalesce(array_length(regexp_split_to_array(trim(content_md), '\\s+'), 1), 0) < 40 order by slug"""
        )
        thin = [{"slug": r["slug"], "words": r["words"]} for r in thin if not _only_empty_text(r["content_md"], chk)]
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


def _only_empty_text(md: str, chk: checks.Checks | None) -> bool:
    """Whether a page's text, headings aside, is only the schema's Empty section text."""
    if not (chk.empty_text):
        return False
    body = " ".join(ln for ln in (md or "").split("\n") if ln.strip() and not ln.lstrip().startswith("#"))
    return " ".join(body.split()) == " ".join(chk.empty_text.split())


MATERIAL = ("synthesis",)  # page types lint never reads as material: saved answers


def _batches(pages: list[dict], size: int) -> list[list[dict]]:
    return [pages[i : i + size] for i in range(0, len(pages), size)]


async def llm_check(wiki: dict, ctx: JobContext) -> dict:
    s = get_settings()
    pages = [p for p in await store.list_pages(wiki["id"], with_content=True) if p["type"] not in MATERIAL]
    index = await store.compact_index(wiki["id"], exclude_types=MATERIAL)
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


async def fix(wiki: dict, report: dict, ctx: JobContext) -> dict:
    """Lint writes no page. Why: every page is made from the schema's controlled lists, never from free text. A link to
    a page that does not exist is proposed to be written as plain text (the schema's links rule)."""
    proposals = await unlink_proposals(wiki["id"], report)
    await ctx.progress(stage="fix", new_pages=0, link_proposals=len(proposals))
    return {"status": "proposed", "link_proposals": proposals}


async def unlink_proposals(wiki_id: UUID, report: dict) -> list[dict]:
    """Each link to a page that does not exist, proposed to be written as plain text: the page, the link, and the text
    it would show. Nothing is changed."""
    valid = {p["slug"] for p in await store.list_pages(wiki_id)}
    out = []
    for slug in sorted({x for b in report["broken_links"] for x in b["linked_from"]}):
        page = await store.get_page(wiki_id, slug)
        for m in store.LINK_RE.finditer(page["content_md"] if page else ""):
            if slugify(m.group(1)) not in valid:
                out.append({"page": slug, "link": m.group(0), "proposal": "write as plain text",
                            "as": (m.group(2) or m.group(1)).strip()})
    return out


async def maintain(wiki: dict) -> dict:
    """The schema's Maintain checks, as its Lint checks list names them: each one lint runs, with what it found; each it
    cannot run reported as not run, with the reason (never passed). No AI call; nothing is changed."""
    from .ingest import _covers, _sections, _split_also, _uncited, use_schema_headings
    chk = checks.load(wiki["schema_md"])
    if not chk.lint_checks and not chk.lint_not_run:
        return {"not_run": "the schema has no Lint checks list in its Checks, so lint runs none of its Maintain checks"}
    use_schema_headings(chk)
    pages = [p for p in await store.list_pages(wiki["id"], with_content=True) if p["type"] not in MATERIAL]
    subs = {p["slug"] for p in pages if p["type"] == "subtopic"}
    claims = [p for p in pages if p["type"] in ("topic", "subtopic") and not any(x.startswith(p["slug"] + "-") for x in subs)
              and p["slug"] not in chk.no_claim_pages]  # the pages that hold claims (an index holds none)
    srcs = await pagecheck.sources(wiki["id"])
    cite_ctx = await fixpass.cite_context(wiki["id"], [x["name"] for x in _sections(wiki["schema_md"])])
    covers = lambda label, ref: _covers(label, ref, not chk.range_ends)

    def openers(p):
        cited = {c.split("|", 1)[0] for c in checks.cites(p["content_md"])} & set(srcs)
        return [f for sl in sorted(cited) for f in checks.section_failures(
            p["content_md"], [], srcs[sl]["kinds"], sl, chk, covers, cite_ctx["labels"].get(sl, set()))]

    def coverage():
        text = "\n\n".join(_split_also(p["content_md"])[0] for p in claims)  # its own write-ups, not its also-recorded lines
        out = []
        for sl, info in sorted(srcs.items()):
            own = [x for lab, ps in info["by_label"].items() if not chk.kinds.get(info["kinds"].get(lab, ""))
                   for x in ps if not checks.is_stub(x, chk)]
            out += [f"{sl}: paragraph {lab} of the Standard's own text is cited as its own source on no page."
                    for lab in dict.fromkeys(pagecheck.BASE(re.match(r"^\[([^\]]+)\]", x).group(1)) for x in _uncited(text, own, not chk.range_ends))]
        return out

    per_page = {"openers": openers, "headings": lambda p: checks.heading_failures(p["content_md"]),
                "citations": lambda p: fixpass.cite_failures(p["content_md"], cite_ctx, chk)}
    out = []
    for n in sorted(set(chk.lint_checks) | set(chk.lint_not_run)):
        what = chk.lint_checks.get(n)
        if what is None:
            out.append({"check": n, "run": False, "reason": chk.lint_not_run[n] or "the schema says lint runs none"})
        elif what == "coverage":
            found = coverage()
            out.append({"check": n, "run": True, "runs": what, "failures": len(found), "found": found[:200]})
        elif what in per_page:
            found = {p["slug"]: f for p in claims if (f := per_page[what](p))}
            out.append({"check": n, "run": True, "runs": what, "failures": sum(map(len, found.values())),
                        "pages": {k: v[:20] for k, v in found.items()}})
        else:
            out.append({"check": n, "run": False, "reason": f'lint has no check called "{what}"'})
    return {"checks": out}


async def run(ctx: JobContext, wiki: dict, use_llm: bool, do_fix: bool) -> dict:
    await ctx.progress(stage="structural")
    report = await structural(wiki["id"], checks.load(wiki["schema_md"]))
    await ctx.progress(stage="maintain")
    maintained = await maintain(wiki)
    llm_report = await llm_check(wiki, ctx) if use_llm else None
    result = {"structural": report, "maintain": maintained, "llm": llm_report}
    if do_fix:
        result["fix"] = await fix(wiki, report, ctx)
    counts = {k: len(v) for k, v in report.items()}
    detail = "Structural: " + ", ".join(f"{k}={v}" for k, v in counts.items())
    detail += "\nMaintain checks: " + ("; ".join(
        f"{c['check']} ({c['runs']}): {c['failures']} found" if c["run"] else f"{c['check']}: not run ({c['reason']})"
        for c in maintained["checks"]) if "checks" in maintained else maintained["not_run"])
    if llm_report:
        detail += "\nLLM: " + ", ".join(f"{k}={len(v)}" for k, v in llm_report.items())
    if do_fix:
        detail += f"\nFix: {result['fix'].get('status')}; links proposed: {len(result['fix'].get('link_proposals') or [])}"
    await store.add_log(wiki["id"], "lint", "Lint" + (" + LLM" if use_llm else "") + (" + fix" if do_fix else ""), detail)
    return result
