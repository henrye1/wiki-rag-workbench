"""Ingest: source -> notes -> plan -> page writes -> changeset."""
import asyncio
import hashlib
import json
import logging
import re
from uuid import UUID

import numpy as np
from psycopg.types.json import Jsonb

from .. import llm, prompts
from ..config import get_settings
from ..db import get_pool
from ..jobs import JobContext
from ..sources.extract import Extracted
from ..wiki import search, store
from ..wiki.store import Op, slugify

log = logging.getLogger(__name__)


class DuplicateSource(Exception):
    def __init__(self, slug: str):
        self.slug = slug


async def save_source(wiki_id: UUID, ex: Extracted, uri: str | None) -> dict:
    sha = hashlib.sha256(ex.text.encode("utf-8")).hexdigest()
    async with get_pool().connection() as conn:
        dup = await (
            await conn.execute("select slug from wiki.sources where wiki_id=%s and sha256=%s", (wiki_id, sha))
        ).fetchone()
        if dup:
            raise DuplicateSource(dup["slug"])
        base = "source-" + slugify(ex.title)[:60]
        taken = {r["slug"] for r in await (
            await conn.execute(
                "select slug from wiki.sources where wiki_id=%s and slug like %s "
                "union select slug from wiki.pages where wiki_id=%s and slug like %s",
                (wiki_id, base + "%", wiki_id, base + "%"),
            )
        ).fetchall()}
        slug, n = base, 2
        while slug in taken:
            slug, n = f"{base}-{n}", n + 1
        return await (
            await conn.execute(
                """insert into wiki.sources (wiki_id, slug, title, kind, uri, sha256, text, meta)
                   values (%s,%s,%s,%s,%s,%s,%s,%s) returning id, slug, title""",
                (wiki_id, slug, ex.title, ex.kind, uri, sha, ex.text, Jsonb(ex.meta)),
            )
        ).fetchone()


def _notes_md(notes: list[dict]) -> str:
    parts = []
    for i, n in enumerate(notes, start=1):
        lines = [f"### Section {i}", n["summary"], "", "Claims:"]
        lines += [f"- {c}" for c in n["claims"]]
        if n.get("open_questions"):
            lines += ["", "Open questions (posed by the source, NOT facts):"] + [f"- {q}" for q in n["open_questions"]]
        if n["entities"]:
            lines += ["", "Entities:"] + [f"- {e['name']}: {e['description']}" for e in n["entities"]]
        if n["concepts"]:
            lines += ["", "Concepts:"] + [f"- {c['name']}: {c['description']}" for c in n["concepts"]]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _names(notes: list[dict], limit: int = 40) -> list[str]:
    counts: dict[str, int] = {}
    for n in notes:
        for x in n["entities"] + n["concepts"]:
            counts[x["name"]] = counts.get(x["name"], 0) + 1
    return [k for k, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:limit]


def _brief(schema: str, title: str) -> str:
    """The schema's section brief (### NN. <name>) whose name matches the page title, if any."""
    norm = lambda x: re.sub(r"[^a-z0-9]+", " ", x.lower()).strip()
    for m in re.finditer(r"^###\s*\d+\.\s*(.+)$", schema, re.M):
        if norm(m.group(1)) and norm(m.group(1)) in norm(title):
            end = re.search(r"^##", schema[m.end():], re.M)
            return schema[m.start(): m.end() + end.start() if end else len(schema)].strip()
    return ""


def _group_key(para: str, i: int) -> str:
    """Paragraph group from its label: 5.5.3 -> 5.5, B5.5.17 -> B5.5, Appendix A terms together; unlabelled stand alone."""
    m = re.match(r"^\[([^\]]+)\]", para)
    ref = m.group(1).strip() if m else ""
    if ref.startswith("Appendix A"):
        return "Appendix A"
    m = re.fullmatch(r"([A-Z]*)(\d+(?:\.\d+)*)[A-Z]{0,2}", ref)
    if not m:
        return f"#{i}"
    nums = m.group(2).split(".")
    return m.group(1) + ".".join(nums[:-1] if len(nums) > 1 else nums)


def _select(paras: list[str], sim: np.ndarray, budget: int) -> list[str]:
    """Most relevant paragraph groups, whole, up to budget words (the last group partly); returned in document order."""
    groups: dict[str, list[int]] = {}
    for i, p in enumerate(paras):
        groups.setdefault(_group_key(p, i), []).append(i)
    words = [len(p.split()) for p in paras]
    picked, used = [], 0
    for g in sorted(groups, key=lambda g: -float(np.mean(sim[groups[g]]))):
        gw = sum(words[i] for i in groups[g])
        if used + gw <= budget:
            picked += groups[g]
            used += gw
            continue
        for i in sorted(groups[g], key=lambda i: -sim[i]):
            if used + words[i] <= budget:
                picked.append(i)
                used += words[i]
        break
    return [paras[i] for i in sorted(picked)]


def _parts(paras: list[str], max_words: int) -> list[list[str]]:
    """Split paragraphs (in document order) into groups of about max_words, one group per writing call."""
    parts, cur, n = [], [], 0
    for p in paras:
        w = len(p.split())
        if cur and n + w > max_words:
            parts.append(cur)
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        if parts and n < max_words // 4:  # fold a small tail into the previous part
            parts[-1] += cur
        else:
            parts.append(cur)
    return parts


def _not_covered(content: str, paras: list[str]) -> str:
    """List the labelled source paragraphs given for a page that the page does not cite (multi-part pages)."""
    missing = []
    for p in paras:
        m = re.match(r"^\[([^\]]+)\]", p)
        ref = m.group(1).strip() if m else ""
        if not ref or re.fullmatch(r"p(age )?\d+", ref):
            continue
        term = ref.split(":", 1)[1].strip() if ref.startswith("Appendix A:") else ref
        if term and not re.search(rf"(?<![\w.]){re.escape(term)}(?![\w])", content, re.I) and ref not in missing:
            missing.append(ref)
    if not missing:
        return ""
    return "\n\nNot yet covered: (source paragraphs given for this page that it does not cite) " + ", ".join(missing)


async def run(ctx: JobContext, wiki: dict, source: dict, ex: Extracted, mode: str) -> dict:
    s = get_settings()
    wiki_id, schema = wiki["id"], wiki["schema_md"]
    system = prompts.MAINTAINER_SYSTEM

    # 1. Notes per section
    await ctx.progress(stage="notes", sections=len(ex.sections))
    failed: list[dict] = []

    def merge(a: dict, b: dict) -> dict:
        return {k: (f"{a[k]} {b[k]}" if k == "summary" else a.get(k, []) + b.get(k, [])) for k in prompts.NOTES_SCHEMA["required"]}

    async def extract_notes(i: int, sec: str, depth: int = 0) -> tuple[dict | None, str | None]:
        try:
            return await llm.generate_json(
                system, prompts.with_schema(schema, prompts.notes_prompt(ex.title, i, len(ex.sections), sec)), prompts.NOTES_SCHEMA
            ), None
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            blocks = sec.split("\n\n")
            if depth >= 2 or len(blocks) < 2:
                return None, err
            # e.g. RECITATION blocks: smaller inputs usually pass
            half = len(blocks) // 2
            (a, ea), (b, eb) = await asyncio.gather(
                extract_notes(i, "\n\n".join(blocks[:half]), depth + 1), extract_notes(i, "\n\n".join(blocks[half:]), depth + 1)
            )
            if a and b:
                return merge(a, b), None
            return (a or b), (ea or eb)

    async def note(i: int, sec: str):
        result, err = await extract_notes(i, sec)
        if err:  # one bad section (or part of one) should not sink the whole ingest
            failed.append({"section": i, "error": err, "partial": result is not None})
        return result

    notes = [n for n in await llm.gather_limited(note(i, sec) for i, sec in enumerate(ex.sections, start=1)) if n]
    if not notes:
        raise RuntimeError(f"Note extraction failed for every section: {failed[:3]}")
    if failed:
        await ctx.progress(failed_sections=failed)
    notes_md = _notes_md(notes)

    # 2. Plan
    await ctx.progress(stage="plan")
    index = await store.compact_index(wiki_id)
    hits = await search.search_many(wiki_id, _names(notes), k=3)
    candidates = "\n".join(f"{h['slug']} | {h['type']} | {h['title']} | {h['summary']}" for h in hits[:40]) or "(none)"
    plan = await llm.generate_json(
        system,
        prompts.with_schema(schema, prompts.plan_prompt(ex.title, source["slug"], notes_md, index, candidates, s.max_pages_per_ingest)),
        prompts.PLAN_SCHEMA,
    )
    existing = {p["slug"]: p for p in await store.list_pages(wiki_id, with_content=True)}
    items, seen = [], {source["slug"]}
    for p in plan["pages"][: s.max_pages_per_ingest]:
        slug = slugify(p["slug"])
        if slug in seen or (p["type"] == "overview" and slug != "overview"):  # `overview` is the only top-level page
            continue
        seen.add(slug)
        items.append({**p, "slug": slug, "action": "update" if slug in existing else "create"})
    if "overview" not in seen:
        items.append({"action": "update" if "overview" in existing else "create", "slug": "overview", "title": wiki["name"],
                      "type": "overview", "focus": f"Integrate the new source {ex.title} into the overview"})

    # 3. Write pages (source page + planned pages)
    await ctx.progress(stage="write", pages=len(items) + 1)
    planned = "\n".join(f"{i['slug']} | {i['type']} | {i['title']} (being written now)" for i in items)
    linkable = f"{index}\n{source['slug']} | source | {ex.title}\n{planned}"
    material = f"Source: {ex.title}\n\n{notes_md}"
    failed_pages: list[dict] = []

    # Source paragraphs ([label] text blocks), embedded once so each page gets the ones most relevant to its section
    paras = [b.strip() for b in re.split(r"\n\s*\n", ex.text) if b.strip()]
    para_vecs = np.asarray(await llm.embed(paras)) if paras else None

    async def source_paragraphs(title: str, ptype: str, focus: str) -> list[str]:
        if para_vecs is None:
            return []
        budget = s.page_part_words if ptype in ("overview", "source") else s.page_source_words
        q = np.asarray(await llm.embed_query(f"{title}\n{focus}\n{_brief(schema, title)}"[:8000]))
        return _select(paras, para_vecs @ q, budget)

    async def write(slug, title, ptype, focus, source_slug):
        cur = existing.get(slug)
        given = await source_paragraphs(title, ptype, focus)
        groups = _parts(given, s.page_part_words) or [[]]
        outs = []
        for n, group in enumerate(groups, start=1):
            part = (n, len(groups)) if len(groups) > 1 else None
            headings = "\n".join(re.findall(r"^#{2,4} .*$", "\n\n".join(o["content_md"] for o in outs), re.M))
            try:
                outs.append(await llm.generate_json(
                    system,
                    prompts.with_schema(schema, prompts.write_page_prompt(
                        slug=slug, title=title, ptype=ptype, focus=focus, existing_md=cur["content_md"] if cur else None,
                        material=material, linkable=linkable, source_slug=source_slug,
                        source_paragraphs="\n\n".join(group) or None, part=part, headings_so_far=headings,
                    )),
                    prompts.PAGE_SCHEMA,
                ))
            except Exception as e:
                if part is None:
                    raise
                # one failed part should not lose the rest of the page
                log.warning("ingest: page %s part %s/%s failed: %s", slug, n, len(groups), e)
                failed_pages.append({"slug": f"{slug} (part {n} of {len(groups)})", "error": f"{type(e).__name__}: {e}"})
        if not outs:
            raise RuntimeError(f"every part of {slug} failed")
        content = "\n\n".join(o["content_md"].strip() for o in outs)
        if len(groups) > 1:
            content += _not_covered(content, given)
        first = outs[0]
        return Op(
            op="update" if cur else "create", slug=slug, title=first["title"] or title, type=ptype, summary=first["summary"],
            content_md=content, tags=list(dict.fromkeys(t for o in outs for t in o["tags"])),
            base_version=cur["version"] if cur else None, change_note=first["change_note"],
        )

    source_focus = (
        "Source page: what the source is, its scope, key takeaways, and which wiki pages it informs "
        f"(link them). One-line summary: {plan['source_summary']}"
    )

    async def write_safe(slug, *args):
        try:
            return await write(slug, *args)
        except Exception as e:  # one page that keeps failing should not sink the whole ingest
            log.warning("ingest: page %s failed: %s", slug, e)
            failed_pages.append({"slug": slug, "error": f"{type(e).__name__}: {e}"})
            return None

    ops = [o for o in await llm.gather_limited(
        [write_safe(source["slug"], ex.title, "source", source_focus, None)]
        + [write_safe(i["slug"], i["title"], i["type"], i["focus"], source["slug"]) for i in items]
    ) if o]
    if not ops:
        raise RuntimeError(f"Page writing failed for every page: {failed_pages[:3]}")
    if failed_pages:
        await ctx.progress(failed_pages=failed_pages)

    # 4. Commit
    await ctx.progress(stage="commit")
    summary = f"Ingest: {ex.title}"
    result = await store.commit(wiki_id, "ingest", summary, ops, mode, job_id=ctx.id, source_id=source["id"])
    detail = f"Source [[{source['slug']}]] ({ex.kind}, {len(ex.sections)} sections). {plan['source_summary']}\n" + "\n".join(
        f"- {o.op} [[{o.slug}]]: {o.change_note}" for o in ops
    )
    await store.add_log(wiki_id, "ingest", ex.title, detail + f"\n\nMode: {mode} ({result['status']})")
    return {"source": source["slug"], "mode": mode, "failed_sections": failed, "failed_pages": failed_pages, "pages": [{"op": o.op, "slug": o.slug} for o in ops], **json.loads(json.dumps(result, default=str))}


async def run_safe(ctx: JobContext, wiki: dict, source: dict, ex: Extracted, mode: str) -> dict:
    """Run ingest; on failure remove the source (if no page uses it) so the upload can be retried."""
    try:
        return await run(ctx, wiki, source, ex, mode)
    except Exception:
        async with get_pool().connection() as conn:
            await conn.execute(
                """delete from wiki.sources s where s.id = %s
                   and not exists (select 1 from wiki.page_sources ps where ps.source_id = s.id)""",
                (source["id"],),
            )
        raise
