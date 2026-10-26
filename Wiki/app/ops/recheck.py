"""Re-check: run the after-writing checks (and their fix rounds) on the pages a wiki already has, without re-ingesting.

Each page is checked against the source paragraphs it cites; what the checks look for is read from the wiki's schema.
Fixes are saved as one changeset."""
import logging
import re

from .. import llm
from ..db import get_pool
from ..jobs import JobContext
from ..wiki import checks, store
from ..wiki.store import Op
from . import fixpass
from .ingest import _covers, _fix_breaks, _index_md, _section_for, _sections, _split_also, _with_also

log = logging.getLogger(__name__)
CITE = re.compile(r"\[\[(source-[^\]|#]+)(?:#[^\]|]*)?\|([^\]]+)\]\]")
BASE = lambda label: re.sub(r"(?:\s*\([^)]*\))+$", "", label.strip())  # 5.5.17(a) -> 5.5.17


async def run(ctx: JobContext, wiki: dict, mode: str = "auto") -> dict:
    wiki_id, schema = wiki["id"], wiki["schema_md"]
    chk = checks.load(schema)
    if chk is None:
        return {"skipped": "the schema has no Checks section"}
    sections = _sections(schema)
    pages = [p for p in await store.list_pages(wiki_id, with_content=True) if p["type"] != "synthesis"]
    cite_ctx = await fixpass.cite_context(wiki_id, [x["name"] for x in sections])
    async with get_pool().connection() as conn:
        rows = await (await conn.execute("select slug, text, meta from wiki.sources where wiki_id = %s", (wiki_id,))).fetchall()
    src = {}
    for r in rows:
        blocks = [b.strip() for b in re.split(r"\n\s*\n", r["text"] or "") if b.strip()]
        by_label: dict[str, list[str]] = {}
        for b in blocks:
            if m := re.match(r"^\[([^\]]+)\]", b):
                by_label.setdefault(m.group(1).strip(), []).append(b)
        meta = r["meta"] or {}
        src[r["slug"]] = {"by_label": by_label, "kinds": meta.get("para_kinds") or {}, "text": r["text"] or "",
                          "fields": {k: v for k, v in (meta.get("document") or {}).items() if v}}
    subtopics = [p["slug"] for p in pages if p["type"] == "subtopic"]
    section_pages = {p["slug"] for p in pages if p["type"] == "topic" and _section_for(sections, p["title"], p["slug"])}
    index_pages = {sl for sl in section_pages if any(s.startswith(sl + "-") for s in subtopics)}
    linkable = await store.compact_index(wiki_id, exclude_types=("synthesis",))
    # the page that holds a paragraph's write-up: the one citing it most (a cross-reference cites it in passing)
    times: dict[str, dict[str, int]] = {}
    for x in pages:
        if x["type"] in ("topic", "subtopic") and x["slug"] not in index_pages:
            for slug, label in CITE.findall(_split_also(x["content_md"])[0]):
                times.setdefault(f"{slug}|{BASE(label)}", {}).setdefault(x["slug"], 0)
                times[f"{slug}|{BASE(label)}"][x["slug"]] += 1
    home = {k: {sl for sl, n in v.items() if n == max(v.values())} for k, v in times.items()}
    await ctx.progress(stage="check", pages=len(pages))
    record: list[dict] = []

    def cited(text: str) -> dict[str, list[str]]:
        """The source paragraphs a page cites, per source."""
        out: dict[str, list[str]] = {}
        for slug, label in CITE.findall(text):
            for b in src.get(slug, {}).get("by_label", {}).get(BASE(label), []):
                out.setdefault(slug, [])
                if b not in out[slug]:
                    out[slug].append(b)
        return out

    async def one(p: dict) -> Op | None:
        if p["slug"] in index_pages and checks.holds_no_claims(chk, p["slug"], True):
            # a split section's index holds no claims: rebuilt from its subtopic pages, in the order it listed them
            subs = sorted((x for x in pages if x["type"] == "subtopic" and x["slug"].startswith(p["slug"] + "-")),
                          key=lambda x: p["content_md"].find(f"[[{x['slug']}") % (len(p["content_md"]) + 1))
            sec = _section_for(sections, p["title"], p["slug"])
            content, summary = _index_md(sec["name"] if sec else p["title"], subs, cite_ctx["titles"])
            if content.strip() == p["content_md"].strip():
                return None
            return Op(op="update", slug=p["slug"], title=p["title"], type=p["type"], summary=summary, content_md=content,
                      tags=p["tags"] or [], base_version=p["version"], change_note="Re-check: index rebuilt from its subtopic pages")
        # the "Also recorded here" lines (on a section page, or on a subtopic page of a split section) are kept as they
        # are: each points to its paragraph's own page, where that paragraph is checked
        body, also_lines = _split_also(p["content_md"]) if p["type"] in ("topic", "subtopic") else (p["content_md"], [])
        cite_check = lambda x: fixpass.cite_failures(x, cite_ctx, chk)
        kind, given, may_shrink, may_grow = "citations", {}, False, False
        if p["type"] == "source" and p["slug"] in src:
            s = src[p["slug"]]
            # the sections this source informs: section pages (or their subtopic pages) that cite it
            informed = {sl for sl in section_pages if any(f"[[{p['slug']}|" in x["content_md"] for x in pages
                                                          if x["slug"] == sl or x["slug"].startswith(sl + "-"))}
            args = dict(fields=s["fields"], authority=checks.authority_sentences(s["text"], chk), informed=informed,
                        sections=section_pages, source_slug=p["slug"], c=chk)
            check = lambda x: checks.source_failures(x, **args)[0] + cite_check(x)
            kind, may_shrink, sources_text = "source page", True, "\n\n".join(args["authority"])
            body = checks.detail_lines(body, chk)
        elif p["type"] in ("topic", "subtopic") and p["slug"] not in index_pages:
            given = cited(body)

            def check(x: str) -> list[str]:
                out = []
                for slug, paras in given.items():
                    out += checks.section_failures(x, paras, src[slug]["kinds"], slug, chk, _covers, cite_ctx["labels"].get(slug, set()),
                                                   holds=lambda ref, slug=slug: p["slug"] in home.get(f"{slug}|{ref}", {p["slug"]}))
                return out + cite_check(x)
            kind, sources_text = "section", "\n\n".join(b for paras in given.values() for b in paras)
        elif checks.holds_no_claims(chk, p["slug"]):  # a claim already on the page that holds its paragraph is dropped here
            holders = {x["slug"]: checks.cites(x["content_md"]) for x in pages if x["type"] in ("topic", "subtopic")
                       and x["slug"] not in index_pages and x["slug"] not in chk.no_claim_pages}
            home = lambda c: next((sl for sl, cs in holders.items() if c in cs), None)
            body = fixpass.move_claims(p["slug"], body, home, lambda sl: holders.get(sl, set()), record, cite_ctx["names"])[0]
            check = lambda x: checks.no_claim_failures(x, section_pages, chk, cite_ctx["names"]) + cite_check(x)
            kind, sources_text, may_grow = "no claims", "", True
        else:  # a split section's index, composed pages: their citations only
            check, sources_text = cite_check, ""
        new = await fixpass.fix_rounds(
            schema=schema, slug=p["slug"], title=p["title"], text=body, check=check, sources_text=sources_text,
            linkable=linkable, kind=kind, record=record, may_shrink=may_shrink, may_grow=may_grow, clause=lambda c: fixpass.is_clause(c, cite_ctx),
            parse=(lambda r: checks.detail_lines(_fix_breaks(r).strip(), chk)) if kind == "source page" else (lambda r: _fix_breaks(r).strip()))
        content = _with_also(new, also_lines) if also_lines else new
        if content.strip() == p["content_md"].strip():
            return None
        rec = next((x for x in record if x["page"] == p["slug"]), None)
        note = f"Re-check: {rec['found'] - rec['still']} of {rec['found']} failures fixed" if rec else "Re-check: source details on their own lines"
        return Op(op="update", slug=p["slug"], title=p["title"], type=p["type"], summary=p["summary"], content_md=content,
                  tags=p["tags"] or [], base_version=p["version"], change_note=note)

    ops = [o for o in await llm.gather_limited([one(p) for p in pages]) if o]
    await ctx.progress(stage="commit")
    result = await store.commit(wiki_id, "check", "Re-check: page checks", ops, mode, job_id=ctx.id)
    await store.add_log(wiki_id, "check", "Re-check of every page",
                        "\n".join(f"- [[{o.slug}]]: {o.change_note}" for o in ops) or "No page needed a change.")
    return {"mode": mode, "pages_checked": len(pages), "pages_changed": [o.slug for o in ops], "check_fixes": record,
            **{k: v for k, v in result.items() if k != "ops"}}
