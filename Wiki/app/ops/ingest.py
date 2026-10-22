"""Ingest: source -> notes -> plan -> page writes -> changeset."""
import asyncio
import hashlib
import json
import logging
import re
from uuid import UUID

import numpy as np
from psycopg.types.json import Jsonb

from .. import llm, prompts, storage
from ..config import get_settings
from ..db import get_pool
from ..jobs import JobContext
from ..sources.extract import Extracted
from ..wiki import checks, citecheck, search, store
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


def _norm(x: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", x.lower()).strip()


def _sections(schema: str) -> list[dict]:
    """The schema's fixed sections (### NN. <name>), each with its whole brief."""
    out = []
    for m in re.finditer(r"^###\s*(\d+)\.\s*(.+)$", schema, re.M):
        end = re.search(r"^##", schema[m.end():], re.M)
        stop = m.end() + end.start() if end else len(schema)
        out.append({"num": int(m.group(1)), "name": m.group(2).strip(), "brief": schema[m.start():stop].strip()})
    return out


def _section_for(sections: list[dict], title: str, slug: str) -> dict | None:
    """The section a page covers, matched by section name in its title or slug."""
    t, sl = _norm(title), _norm(slug)
    for sec in sorted(sections, key=lambda x: -len(x["name"])):
        n = _norm(sec["name"])
        if n and (n in t or n in sl):
            return sec
    return None


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




def _ref(para: str) -> str:
    m = re.match(r"^\[([^\]]+)\]", para)
    return m.group(1).strip() if m else ""


REF_PAT = r"[A-Z]*\d+(?:\.\d+)*[A-Z]{0,2}"


def _ref_key(ref: str) -> tuple[str, list[str], int] | None:
    m = re.fullmatch(r"([A-Z]*)(\d+(?:\.\d+)*)([A-Z]{0,2})", ref)
    if not m:
        return None
    nums = m.group(2).split(".")
    return m.group(1), nums[:-1], int(nums[-1])


def _covers(label: str, ref: str) -> bool:
    """Whether a citation label (e.g. "4.2.1(a)", "paragraphs B4.1.1–B4.1.26", "AppA:credit loss") cites ref."""
    if ref.startswith("Appendix A:"):
        term = ref.split(":", 1)[1].strip().lower()
        return bool(term) and term in label.lower()
    if re.search(rf"(?<![\w.]){re.escape(ref)}(?![\w]|\.\d)", label):
        return True
    key = _ref_key(ref)
    for lo, hi in re.findall(rf"({REF_PAT})\s*[–-]\s*({REF_PAT})", label):
        a, b = _ref_key(lo), _ref_key(hi)
        if key and a and b and a[:2] == b[:2] == key[:2] and a[2] <= key[2] <= b[2]:
            return True
    return False


_STUB = re.compile(r"\[?(?:This paragraph refers|These paragraphs refer)[^\]]*?not included in this edition\.?\]?", re.I)


def _placeholder(para: str) -> bool:
    """A paragraph that only says the edition leaves it out ("... not included in this edition."): nothing to write up."""
    body = re.sub(r"^\[[^\]]+\]\s*(?:\([^)]*\)\s*)?", "", para)
    if "included in this edition" not in body:
        return False
    rest = _STUB.sub(" ", body)
    rest = re.sub(r"(?:not\s+)?included in this edition\.?\]?", " ", rest)  # the tail of a stub split across chunks
    rest = re.sub(r"\[?(?:This paragraph refers|These paragraphs refer) to amendments that are not yet effective[^\]]*$",
                  " ", rest, flags=re.I)  # the start of a stub that continues in the next chunk
    rest = re.sub(rf"{REF_PAT}\s*[\u2013-]?", " ", rest)  # range labels such as 7.2.51–
    return not re.search(r"[A-Za-z]{3,}", rest)


def _uncited(content: str, paras: list[str]) -> list[str]:
    """The labelled paragraphs in paras that no citation on the page names (each chunk of an uncited paragraph).
    Placeholders ("not included in this edition") are never counted as uncited."""
    labels = [m.group(2) for m in store.LINK_RE.finditer(content) if m.group(2)]
    out, cited = [], {}
    for p in paras:
        ref = _ref(p)
        if not ref or re.fullmatch(r"p(age )?\d+", ref) or _placeholder(p):
            continue
        if ref not in cited:
            cited[ref] = any(_covers(label, ref) for label in labels)
        if not cited[ref]:
            out.append(p)
    return out


def _not_covered(content: str, paras: list[str], what: str = "source paragraphs given for this page") -> str:
    """List the labelled paragraphs in paras that the page does not cite."""
    missing = list(dict.fromkeys(_ref(p) for p in _uncited(content, paras)))
    if not missing:
        return ""
    return f"\n\nNot yet covered: ({what} that it does not cite) " + ", ".join(missing)


ALSO_HEADING = "## Also recorded here"


def _split_also(md: str) -> tuple[str, list[str]]:
    """A page's text without its "Also recorded here" section, and that section's lines."""
    m = re.search(rf"^{re.escape(ALSO_HEADING)}\s*$", md, re.M)
    if not m:
        return md, []
    rest = md[m.end():]
    end = re.search(r"^(?:#{1,2} |Not yet covered:)", rest, re.M)  # the section ends at the next heading or the gap note
    section, after = (rest[: end.start()], rest[end.start():]) if end else (rest, "")
    lines = [ln.strip() for ln in section.split("\n") if ln.strip()]
    body = (md[: m.start()].rstrip() + ("\n\n" + after.strip() if after.strip() else "")).strip()
    return body, lines


def _with_also(body: str, lines: list[str]) -> str:
    """The page text with its "Also recorded here" section, placed before a closing "Not yet covered" note."""
    if not lines:
        return body
    section = f"{ALSO_HEADING}\n\n" + "\n".join(lines)
    m = re.search(r"\n*^Not yet covered:.*\Z", body, re.M | re.S)
    head, tail = (body[: m.start()], body[m.start():].strip()) if m else (body, "")
    return "\n\n".join(x for x in (head.strip(), section, tail) if x)


def _also_key(line: str) -> str:
    """Lines citing the same paragraph of the same source are one entry (a later upload replaces it)."""
    cites = sorted(f"{m.group(1)}|{m.group(2)}" for m in store.LINK_RE.finditer(line) if m.group(1).startswith("source-") and m.group(2))
    return " ".join(cites) or _norm(line)


HEADING_IN_TEXT = re.compile(r"(?<=[^\s#])[ \t]*(#{2,4} )")  # a heading run on after the previous text
HEADING_RUN_ON = re.compile(r"^(#{2,4} [^\n\[]*?[a-z)])([A-Z][a-z][^\n]*\[\[)", re.M)  # "### Loss allowanceAn entity ... [["
CITE_RUN_ON = re.compile(r"(\]\][.;:]?)(?=[A-Z])")  # "...|5.5.7]].The objective ...": the paragraph break was left out
BULLET_RUN_ON = re.compile(r"(\]\][.;:]?|(?<=\w):|^#{2,4} [^\n*\u2022\[]*?\S)(?=[*\u2022-]\s)", re.M)  # "...]].* Next", "include:* An", "### Key takeaways* An"


def _fix_breaks(text: str) -> str:
    """Put back line breaks the model left out: escaped "\\n" as text, a heading run on after a sentence, or a heading
    run together with the text under it (a heading line that cites something is two lines), or the next paragraph run
    on straight after a citation (or a bullet run on after a citation or a heading)."""
    fixed = text.replace("\\n", "\n")
    fixed = HEADING_IN_TEXT.sub(r"\n\n\1", fixed)
    fixed = HEADING_RUN_ON.sub(r"\1\n\2", fixed)
    fixed = CITE_RUN_ON.sub(r"\1\n\n", fixed)
    fixed = BULLET_RUN_ON.sub(r"\1\n", fixed)
    if fixed != text:
        log.info("ingest: line breaks restored in page text")
    return fixed


def _same_label_together(paras: list[str], placed: dict[int, int]) -> None:
    """The reader splits a long paragraph into chunks that share its label: send them all where most of them went (on a
    tie, where the first went), so the paragraph is written up whole, e.g. an example's facts with its analysis."""
    chunks: dict[str, list[int]] = {}
    for i in sorted(placed):
        if ref := _ref(paras[i]):
            chunks.setdefault(ref, []).append(i)
    for idx in chunks.values():
        if len({placed[i] for i in idx}) > 1:
            votes = [placed[i] for i in idx]
            best = max(votes, key=lambda n: (votes.count(n), -votes.index(n)))
            for i in idx:
                placed[i] = best


def _join_parts(texts: list[str]) -> str:
    """Join a page's parts, dropping any block (paragraph, heading, list) that repeats one from an earlier part."""
    seen: set[str] = set()
    out = []
    for t in map(_fix_breaks, texts):
        blocks = [b for b in re.split(r"\n\s*\n", t.strip()) if b.strip()]
        keys = [_norm(b) for b in blocks]
        out += [b for b, k in zip(blocks, keys) if not k or k not in seen]
        seen.update(k for k in keys if k)
    return "\n\n".join(out)


def _unlink(md: str, valid: set[str]) -> str:
    """Turn links to pages that do not exist into plain text (the label if there is one, else the link text)."""
    return store.LINK_RE.sub(lambda m: m.group(0) if slugify(m.group(1)) in valid else (m.group(2) or m.group(1)).strip(), md)


async def run(ctx: JobContext, wiki: dict, source: dict, ex: Extracted, mode: str) -> dict:
    s = get_settings()
    wiki_id, schema = wiki["id"], wiki["schema_md"]
    system = prompts.MAINTAINER_SYSTEM
    chk = checks.load(schema)  # example routing and the page checks read their words from the schema's Checks section
    if chk is None:
        log.info("ingest: the schema has no Checks section; example routing by label and the page checks are off")
    elif chk.missing:
        log.info("ingest: the schema's Checks section has no list for %s; what uses them is off", ", ".join(chk.missing))

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

    # 2. Route: give each source paragraph to exactly one schema section (only that section's page writes it up)
    paras = [b.strip() for b in re.split(r"\n\s*\n", ex.text) if b.strip()]
    para_vecs = np.asarray(await llm.embed(paras)) if paras else None
    sections = _sections(schema)
    owner: dict[int, int] = {}
    unassigned: list[dict] = []  # paragraphs the model did not assign, and where they were placed instead
    if sections and paras:
        await ctx.progress(stage="route")
        heads = ex.meta.get("headings") or []
        heads = heads if len(heads) == len(paras) else [""] * len(paras)
        # The issuer's labelled examples go to the section the schema names for them; nothing else does
        ex_sec = next((x for x in sections if chk and x["num"] == chk.examples_section), None)
        if ex_sec:
            # Paragraphs of a kind the schema routes to the examples section (by the reader's kind, e.g. a Part B's
            # illustrative examples); in a Standard, paragraphs carrying one of the schema's example labels
            kinds = ex.meta.get("kinds") or []
            kinds = kinds if len(kinds) == len(paras) else [""] * len(paras)
            label_re = checks.example_label_re(chk)
            labelled = {_ref(p) or i for i, p in enumerate(paras)
                        if (checks.routed_to_examples(chk, kinds[i]) if kinds[i] else bool(label_re and label_re.search(p)))}
            owner.update({i: ex_sec["num"] for i, p in enumerate(paras) if (_ref(p) or i) in labelled})
        targets = [x for x in sections if x is not ex_sec]
        briefs = "\n\n".join(x["brief"] for x in targets)
        nums = {x["num"] for x in targets}
        note = (f"Section {ex_sec['num']:02d} ({ex_sec['name']}) is not offered: the issuer's labelled examples have already "
                "been placed there, and every other paragraph goes to the section that owns it." if ex_sec else "")
        outline = "\n".join(ex.meta.get("outline") or [])

        async def route(batch: list[int]) -> dict[int, int]:
            lines = "\n".join(f"{i} | {heads[i] or '-'} | {' '.join(paras[i].split()[:60])}" for i in batch)
            try:
                out = await llm.generate_json(
                    system, prompts.with_schema(schema, prompts.route_prompt(briefs, lines, outline, note)), prompts.ROUTE_SCHEMA
                )
            except Exception as e:  # unrouted paragraphs are retried, then placed by the fallbacks below
                log.warning("ingest: routing batch failed: %s", e)
                return {}
            return {a["id"]: a["section"] for a in out["assignments"] if a["id"] in batch and a["section"] in nums}

        todo = [i for i in range(len(paras)) if i not in owner]
        for size in (s.route_batch, 40):  # second round: only what the first one missed, in smaller batches
            for d in await llm.gather_limited(route(todo[i : i + size]) for i in range(0, len(todo), size)):
                owner.update(d)
            todo = [i for i in todo if i not in owner]
            if not todo:
                break
        # Still missing: where most of its paragraph group (e.g. 5.5.x) went, else the closest section brief
        groups: dict[str, list[int]] = {}
        for i, p in enumerate(paras):
            groups.setdefault(_group_key(p, i), []).append(i)
        name = {x["num"]: f"{x['num']:02d} {x['name']}" for x in sections}
        brief_vecs = np.asarray(await llm.embed([x["brief"][:8000] for x in targets], task="RETRIEVAL_QUERY")) if todo else None
        for i in todo:
            votes = [owner[j] for j in groups[_group_key(paras[i], i)] if j in owner and owner[j] in nums]
            if votes:
                owner[i], by = max(set(votes), key=votes.count), "its paragraph group"
            else:
                owner[i], by = targets[int(np.argmax(brief_vecs @ para_vecs[i]))]["num"], "closest section brief"
            unassigned.append({"paragraph": _ref(paras[i]) or f"paragraph {i + 1}", "placed_in": name[owner[i]], "by": by})
        _same_label_together(paras, owner)  # the chunks of one long paragraph go to one page
        if unassigned:
            await ctx.progress(unassigned=unassigned)

    # 2b. "Also record here" sections (the schema marks them ADDITIVE): a paragraph keeps its own section and is ALSO
    # recorded on such a section's page as one short line, when it holds a presumption, election, policy choice,
    # judgement or estimate
    also: dict[int, list[int]] = {}
    for sec in [x for x in sections if re.search(r"\bADDITIVE\b", x["brief"])] if owner else []:
        cand = [i for i in range(len(paras)) if owner.get(i) != sec["num"] and not _placeholder(paras[i])]

        async def pick(batch: list[int], sec=sec) -> list[int]:
            lines = "\n".join(f"{i} | {' '.join(paras[i].split()[:200])}" for i in batch)
            try:
                out = await llm.generate_json(system, prompts.also_prompt(sec["brief"], lines), prompts.ALSO_SCHEMA)
            except Exception as e:
                log.warning("ingest: also-record batch for %s failed: %s", sec["name"], e)
                return []
            return [i for i in out["ids"] if i in batch]

        picked = await llm.gather_limited(pick(cand[k : k + s.route_batch]) for k in range(0, len(cand), s.route_batch))
        also[sec["num"]] = sorted({i for got in picked for i in got})

    # 2c. Split sections (the schema's Checks list): a split section's paragraphs are grouped into its subtopic pages,
    # by what the schema says they are grouped by; the groups offered are the schema's own sections
    group_of: dict[int, int] = {}  # paragraph -> the section number of its group
    for num, grouped_by in (chk.split.items() if chk and owner else []):
        parent = next((x for x in sections if x["num"] == num), None)
        mine = [i for i, n in sorted(owner.items()) if n == num]
        if not parent or not mine:
            continue
        await ctx.progress(stage="group")
        vocab = [x for x in sections if x["num"] != num]
        listing, gnums = "\n".join(f"{x['num']}. {x['name']}" for x in vocab), {x["num"] for x in vocab}

        async def group(batch: list[int]) -> dict[int, int]:
            lines = "\n".join(f"{i} | {heads[i] or '-'} | {' '.join(paras[i].split()[:80])}" for i in batch)
            try:
                out = await llm.generate_json(system, prompts.with_schema(schema, prompts.group_prompt(
                    parent["brief"], grouped_by, listing, lines)), prompts.ROUTE_SCHEMA)
            except Exception as e:
                log.warning("ingest: grouping batch for section %s failed: %s", num, e)
                return {}
            return {a["id"]: a["section"] for a in out["assignments"] if a["id"] in batch and a["section"] in gnums}

        got: dict[int, int] = {}
        for d in await llm.gather_limited(group(mine[i : i + s.route_batch]) for i in range(0, len(mine), s.route_batch)):
            got.update(d)
        for k, i in enumerate(mine):  # left without a group: its neighbour's (an example runs over several paragraphs)
            if i not in got:
                near = [got[j] for j in reversed(mine[:k]) if j in got][:1] or [got[j] for j in mine[k + 1:] if j in got][:1]
                if near:
                    got[i] = near[0]
        _same_label_together(paras, got)  # ... and to one subtopic page
        group_of.update(got)
        log.info("ingest: section %s split into %s groups (%s of %s paragraphs grouped)", num, len(set(got.values())),
                 len(got), len(mine))

    # 3. Plan
    await ctx.progress(stage="plan")
    # pages one ingest writes, from the schema: every section page and the overview (the source page and any subtopic
    # pages come on top); a schema without fixed sections uses the setting
    cap = len(sections) + 1 if sections else s.max_pages_per_ingest - 1
    # synthesis pages (answers filed back from queries) are never source material: not offered to the planner
    index = await store.compact_index(wiki_id, exclude_types=("synthesis",))
    hits = [h for h in await search.search_many(wiki_id, _names(notes), k=3) if h["type"] != "synthesis"]
    candidates = "\n".join(f"{h['slug']} | {h['type']} | {h['title']} | {h['summary']}" for h in hits[:40]) or "(none)"
    plan = await llm.generate_json(
        system,
        prompts.with_schema(schema, prompts.plan_prompt(ex.title, source["slug"], notes_md, index, candidates, cap)),
        prompts.PLAN_SCHEMA,
    )
    existing = {p["slug"]: p for p in await store.list_pages(wiki_id, with_content=True)}
    items, seen = [], {source["slug"]}
    for p in plan["pages"]:
        slug = slugify(p["slug"])
        if slug in seen or (p["type"] == "overview" and slug != "overview"):  # `overview` is the only top-level page
            continue
        if p["type"] == "synthesis" or existing.get(slug, {}).get("type") == "synthesis":
            continue  # only queries file synthesis pages; an upload never writes or rewrites one
        if existing.get(slug, {}).get("type") == "subtopic":
            continue  # subtopic pages are made from the grouping below, never planned
        seen.add(slug)
        items.append({**p, "slug": slug, "action": "update" if slug in existing else "create"})
    if "overview" not in seen:
        items.append({"action": "update" if "overview" in existing else "create", "slug": "overview", "title": wiki["name"],
                      "type": "overview", "focus": f"Integrate the new source {ex.title} into the overview"})
    sec_of: dict[str, dict] = {}  # topic page -> its section (one page per section)
    for i in items:
        sec = _section_for(sections, i["title"], i["slug"]) if i["type"] == "topic" else None
        if sec and sec["num"] not in {x["num"] for x in sec_of.values()}:
            sec_of[i["slug"]] = sec
    if sections:  # every section gets a page, named like the planned ones (e.g. ifrs-9-<section>)
        covered = {x["num"] for x in sec_of.values()}
        prefix = next((sl[: -len(slugify(x["name"]))] for sl, x in sec_of.items() if sl.endswith(slugify(x["name"]))), "")
        for sec in sections:
            slug = prefix + slugify(sec["name"])
            if sec["num"] in covered or slug in seen:
                continue
            seen.add(slug)
            items.append({"action": "update" if slug in existing else "create", "slug": slug, "title": sec["name"],
                          "type": "topic", "focus": f"Section {sec['num']:02d}: {sec['name']}"})
            sec_of[slug] = sec
    # the source page counts toward the limit; section pages first, then the overview, then the rest
    rank = lambda i: 0 if sec_of.get(i["slug"]) else 1 if i["slug"] == "overview" else 2
    items = sorted(items, key=rank)[:cap]
    # subtopic pages of split sections: one per group that has paragraphs, named <section-slug>-<group>
    by_num = {x["num"]: x for x in sections}
    slug_of = {x["num"]: sl for sl, x in sec_of.items()}
    sub_of: dict[str, dict] = {}  # subtopic page -> its section, its group and its paragraphs
    for i, g in sorted(group_of.items()):
        if owner.get(i) in slug_of and g in by_num:
            sl = f"{slug_of[owner[i]]}-{slugify(by_num[g]['name'])}"
            sub_of.setdefault(sl, {"sec": by_num[owner[i]], "group": by_num[g], "paras": []})["paras"].append(i)
    index_of: dict[str, list[str]] = {}  # split section page -> its subtopic pages written now
    for sl, sub in sub_of.items():
        index_of.setdefault(slug_of[sub["sec"]["num"]], []).append(sl)
        items.append({"action": "update" if sl in existing else "create", "slug": sl, "type": "subtopic",
                      "title": f"{sub['sec']['name']}: {sub['group']['name']}",
                      "focus": f"Section {sub['sec']['num']:02d}: {sub['sec']['name']}, subtopic {sub['group']['name']}"})
    para_sub = {i: sl for sl, sub in sub_of.items() for i in sub["paras"]}

    # 4. Write pages (source page + planned pages)
    await ctx.progress(stage="write", pages=len(items) + 1)
    planned = "\n".join(f"{i['slug']} | {i['type']} | {i['title']} (being written now)" for i in items)
    linkable = f"{index}\n{source['slug']} | source | {ex.title}\n{planned}"
    material = f"Source: {ex.title}\n\n{notes_md}"
    failed_pages: list[dict] = []
    empty_retries: list[dict] = []  # page parts that came back empty and were asked for once more
    check_fixes: list[dict] = []  # pages sent back once to fix what the schema check found
    para_kinds = ex.meta.get("para_kinds") or {}
    authority = checks.authority_sentences(ex.text, chk) if chk else []
    cite_matchers = await citecheck.sources(wiki_id)  # the wiki's sources, this one included, for checking citations

    def cite_failures(text: str) -> list[str]:
        """Citations the citation check would flag, as failures for the fix round to correct."""
        _, _, flagged = citecheck.check(text, cite_matchers)
        return [f'The citation [[{src}|{label}]] does not match a paragraph of that source ({reason}); cite the paragraph '
                "it states, by its own label." for (src, label, reason) in flagged]
    fill_passes: list[dict] = []  # what each extra writing pass was asked for and returned
    missed: list[dict] = []  # paragraphs still not written up (or not also recorded) after the extra passes

    own: dict[int, list[int]] = {}
    for i, n in sorted(owner.items()):
        own.setdefault(n, []).append(i)

    async def relevant(query: str, budget: int, exclude: set[int] = frozenset()) -> list[str]:
        if para_vecs is None or budget <= 0:
            return []
        keep = [i for i in range(len(paras)) if i not in exclude]
        q = np.asarray(await llm.embed_query(query[:8000]))
        return _select([paras[i] for i in keep], para_vecs[keep] @ q, budget)

    async def write(slug, title, ptype, focus, source_slug):
        async def check_and_fix(kind: str, text: str, check, *, sources_text: str, parse, out_schema=prompts.PAGE_SCHEMA,
                                ok=lambda old, new: True, may_shrink: bool = False) -> str:
            """Check the page; if anything fails, send it back with the list, at most twice. A rewrite is kept only if
            it has fewer failures, loses no citation, stays about the same length (a fix changes what was listed, not
            the whole page; may_shrink when a failure asks for something to be taken out) and passes ok."""
            rounds = []
            for rnd in (1, 2):
                failures = check(text)
                if not failures:
                    break
                rec = {"round": rnd, "failures": failures}
                try:
                    out = await llm.generate_json(system, prompts.with_schema(schema, prompts.fix_page_prompt(
                        slug=slug, title=title, content_md=text or "(nothing yet)", failures=failures, linkable=linkable,
                        source_paragraphs=sources_text or "(none)")), out_schema)
                    new = parse(out["content_md"])
                    after = check(new)
                    lost = [] if may_shrink else sorted(checks.cites(text) - checks.cites(new))
                    n_old, n_new = len(text.split()), len(new.split())
                    keep = (bool(new.strip()) and len(after) < len(failures) and not lost and ok(text, new)
                            and n_new <= 1.5 * n_old + 200 and (may_shrink or n_new >= 0.8 * n_old))
                    rec |= {"kept": keep, "fixed": len(failures) - len(after) if keep else 0, "still": after,
                            "words": [n_old, n_new],
                            **({"lost_citations": lost} if lost else {})}
                    if keep:
                        text = new
                    log.info("ingest: page %s %s check, round %s: %s failures, %s fixed, rewrite %s", slug, kind, rnd,
                             len(failures), len(failures) - len(after), "kept" if keep else "discarded")
                except Exception as e:
                    log.warning("ingest: page %s %s check, round %s failed: %s", slug, kind, rnd, e)
                    rec["error"] = f"{type(e).__name__}: {e}"
                rounds.append(rec)
            if rounds:
                check_fixes.append({"page": slug, "kind": kind, "found": len(rounds[0]["failures"]),
                                    "still": len(check(text)), "rounds": rounds})
            return text

        cur = existing.get(slug)
        sec = sec_of.get(slug) if owner else None
        sub = sub_of.get(slug)
        # the page's "Also recorded here" lines are kept as they are; the writer sees (and rewrites) only the rest
        cur_body, old_also = _split_also(cur["content_md"]) if cur and sec else (cur["content_md"] if cur else None, [])
        background, auto_gaps, page_material = [], False, material
        extra = also.get(sec["num"], []) if sec else []  # paragraphs also recorded here as one line each
        if sec or sub:  # a section (or subtopic) page writes up only its own paragraphs; a few related ones are context
            mine = sub["paras"] if sub else own.get(sec["num"], [])
            given = [paras[i] for i in mine]
            if not given and not extra:  # nothing from this source: leave an existing page alone, otherwise say the section is empty
                if cur:
                    return None
                return Op(op="create", slug=slug, title=title, type=ptype, summary="Empty: no source content yet", tags=[],
                          content_md=f"This section is empty: no paragraph of [[{source_slug}]] belongs to it.",
                          change_note=f"Created empty: {ex.title} has nothing for this section")
            # its own paragraphs are its material; the notes cover every section and would leak other sections' points in
            auto_gaps, page_material = True, f"Source: {ex.title}"
            # labels removed: under the schema an uncitable paragraph cannot be written up
            background = [re.sub(r"^\[[^\]]+\]\s*", "", p)
                          for p in await relevant((sub or {"sec": sec})["sec"]["brief"], s.page_background_words, set(mine) | set(extra))] if given else []
        elif owner:  # overview, source and other composed pages: every paragraph belongs to a section page, so context only
            given = []
            background = [re.sub(r"^\[[^\]]+\]\s*", "", p) for p in await relevant(f"{title}\n{focus}", s.page_background_words)]
        else:  # schema without fixed sections: the most relevant paragraphs
            given = await relevant(f"{title}\n{focus}", s.page_part_words if ptype in ("overview", "source") else s.page_source_words)
        groups = _parts(given, s.page_part_words) or ([] if extra else [[]])  # an empty page is written once
        outs = []
        for n, group in enumerate(groups, start=1):
            part = (n, len(groups)) if len(groups) > 1 else None
            prompt = prompts.with_schema(schema, prompts.write_page_prompt(
                slug=slug, title=title, ptype=ptype, focus=focus, existing_md=cur_body,
                material=page_material, linkable=linkable, source_slug=source_slug,
                source_paragraphs="\n\n".join(group) or None, background_paragraphs="\n\n".join(background) or None,
                auto_gaps=auto_gaps, part=part,
                earlier_parts="\n\n".join(o["content_md"] for o in outs),
            ))
            try:
                out = await llm.generate_json(system, prompt, prompts.PAGE_SCHEMA)
                if not out["content_md"].strip():  # an empty reply is retried once
                    log.warning("ingest: page %s%s came back empty; retrying once", slug, f" part {n}/{len(groups)}" if part else "")
                    out = await llm.generate_json(system, prompt, prompts.PAGE_SCHEMA)
                    empty_retries.append({"page": slug, "part": n if part else None, "empty_again": not out["content_md"].strip()})
                    if not out["content_md"].strip():
                        log.warning("ingest: page %s came back empty again", slug)
                outs.append(out)
            except Exception as e:
                if part is None:
                    raise
                # one failed part should not lose the rest of the page
                log.warning("ingest: page %s part %s/%s failed: %s", slug, n, len(groups), e)
                failed_pages.append({"slug": f"{slug} (part {n} of {len(groups)})", "error": f"{type(e).__name__}: {e}"})
        if not outs and given:
            raise RuntimeError(f"every part of {slug} failed")
        content = _join_parts([o["content_md"] for o in outs])
        if sec:
            content = _split_also(content)[0]  # the section is rebuilt below from the kept and the new lines
            if not given and cur:  # only lines to also record: the page itself stays as it is
                content = cur_body

        def cited_only(text: str, refs: set[str]) -> str:
            """The blocks (or bullet lines) of a reply that cite one of refs, so an extra pass cannot rewrite the page."""
            blocks = [b for b in re.split(r"\n\s*\n|\n(?=\s*[-*] )", text.strip()) if b.strip()]
            # a bare heading has no citation; a heading run together with its text ("...InstrumentsAn entity shall ...") does
            bare = lambda b: re.match(r"^#{2,4} ", b) and not store.LINK_RE.search(b)
            keep = [b for b in blocks if bare(b) or any(
                _covers(m.group(2), r) for m in store.LINK_RE.finditer(b) if m.group(2) for r in refs)]
            while keep and bare(keep[-1]):
                keep.pop()
            return "\n\n".join(keep)

        if auto_gaps:  # own paragraphs the parts left out get an extra pass, and one more try if still missing
            for attempt in (1, 2):
                missing = _uncited(content, given)
                if not missing:
                    break
                for group in _parts(missing, s.page_part_words):
                    refs = {_ref(p) for p in group}
                    rec = {"page": slug, "attempt": attempt, "asked": sorted(refs)}
                    try:
                        out = await llm.generate_json(
                            system,
                            prompts.with_schema(schema, prompts.write_page_prompt(
                                slug=slug, title=title, ptype=ptype, focus=focus, existing_md=None, material=page_material,
                                linkable=linkable, source_slug=source_slug, source_paragraphs="\n\n".join(group),
                                auto_gaps=True, fill=True, earlier_parts="\n".join(re.findall(r"^#{2,4} .*$", content, re.M)),
                            )),
                            prompts.FILL_SCHEMA,
                        )
                        kept = cited_only(_fix_breaks(out["content_md"]), refs)
                        content = _join_parts([content, kept])
                        rec |= {"returned": out["content_md"], "kept_words": len(kept.split())}
                    except Exception as e:
                        log.warning("ingest: page %s fill pass %s failed: %s", slug, attempt, e)
                        rec["error"] = f"{type(e).__name__}: {e}"
                    rec["still_missing"] = sorted({_ref(p) for p in _uncited(content, group)})
                    fill_passes.append(rec)
            if still := list(dict.fromkeys(_ref(p) for p in _uncited(content, given))):
                missed.append({"page": slug, "paragraphs": still, "reason": "not written up after two extra passes"})

        if given and source_slug:
            content = await check_and_fix(
                "section", content, lambda x: (checks.section_failures(x, given, para_kinds, source_slug, chk, _covers)
                                               if chk else []) + cite_failures(x),
                sources_text="\n\n".join(given), parse=lambda r: _fix_breaks(r).strip(),
                ok=lambda old, new: not ({_ref(p) for p in _uncited(new, given)} - {_ref(p) for p in _uncited(old, given)}))

        if ptype == "source" and owner and sec_of and chk and chk.source_parts:
            informed = {sl for sl, x in sec_of.items() if own.get(x["num"]) or also.get(x["num"])}
            args = dict(fields=fields, authority=authority, informed=informed, sections=set(sec_of),
                        source_slug=source["slug"], c=chk)
            if skipped := checks.source_failures(content, **args)[1]:
                log.info("ingest: source page %s: not checked: %s", slug, "; ".join(skipped))
            content = await check_and_fix("source page", content, lambda x: checks.source_failures(x, **args)[0] + cite_failures(x),
                                          sources_text="\n\n".join(authority), parse=lambda r: _fix_breaks(r).strip(),
                                          may_shrink=True)  # a source page with too many takeaways must lose some

        if extra:  # one short line per also-recorded paragraph, linking to its main page
            main_page = {x["num"]: sl for sl, x in sec_of.items()}

            def item(i: int) -> str:
                link = f"(main page: [[{para_sub.get(i) or main_page.get(owner.get(i), 'overview')}]])"
                return re.sub(r"^(\[[^\]]+\])", lambda m: f"{m.group(1)} {link}", paras[i], count=1)

            def also_lines(reply: str, refs: set[str]) -> list[str]:
                # one entry per line, also when the reply runs bullets together ("...|2.1]]- Designation: ...")
                kept = cited_only(re.sub(r"\]\]\s*[-*]\s+", "]]\n- ", _fix_breaks(reply)), refs)
                # every paragraph comes from the source being uploaded, whichever source the reply names
                return [re.sub(r"\[\[source-[^\]|#]+\|", f"[[{source_slug}|", ln.strip())
                        for ln in kept.split("\n") if ln.strip() and not re.match(r"^#{1,4} ", ln)]

            lines: list[str] = []
            for attempt in (1, 2):
                todo = [i for i in extra if _uncited("\n".join(lines), [paras[i]])]
                if not todo:
                    break
                for group in _parts([item(i) for i in todo], s.page_part_words):
                    refs = {_ref(p) for p in group}
                    rec = {"page": slug, "attempt": attempt, "kind": "also recorded", "asked": sorted(refs)}
                    try:
                        out = await llm.generate_json(
                            system,
                            prompts.with_schema(schema, prompts.also_record_prompt(
                                slug=slug, title=title, items="\n\n".join(group), linkable=linkable, source_slug=source_slug)),
                            prompts.FILL_SCHEMA,
                        )
                        new_lines = also_lines(out["content_md"], refs)
                        lines += new_lines
                        rec |= {"returned": out["content_md"], "kept_words": len(" ".join(new_lines).split())}
                    except Exception as e:
                        log.warning("ingest: page %s also-record pass %s failed: %s", slug, attempt, e)
                        rec["error"] = f"{type(e).__name__}: {e}"
                    fill_passes.append(rec)
            # a line that folds the main page and the paragraph number into one link ([[main-page|4.3.7]]) gets the
            # usual form: see [[main-page]] [[source|4.3.7]]
            lines = [ln if store.LINK_RE.search(ln.replace("[[source-", "")) is None or re.search(r"\[\[source-[^\]|]+\|", ln)
                     else re.sub(r"\[\[((?!source-)[^\]|#]+)\|([^\]]+)\]\]", lambda m: f"see [[{m.group(1)}]] [[{source_slug}|{m.group(2)}]]", ln)
                     for ln in lines]
            # check: every paragraph marked "also record here" has a line citing it; if not, the lines go back
            missing_also = lambda x: [f"Paragraph {_ref(paras[i])} is marked to be also recorded on this page, but no line "
                                      "cites it." for i in extra if _uncited(x, [paras[i]])]
            all_refs = {_ref(paras[i]) for i in extra}
            lines = [ln for ln in (await check_and_fix(
                "also recorded", "\n".join(lines), missing_also, out_schema=prompts.FILL_SCHEMA,
                sources_text="\n\n".join(item(i) for i in extra if _uncited("\n".join(lines), [paras[i]])),
                parse=lambda r: "\n".join(also_lines(r, all_refs)))).split("\n") if ln.strip()]
            if still := [_ref(paras[i]) for i in extra if _uncited("\n".join(lines), [paras[i]])]:
                missed.append({"page": slug, "paragraphs": list(dict.fromkeys(still)), "reason": "not recorded after two tries and the check"})

        if sec and (old_also or extra):  # earlier uploads' lines first; a line for the same paragraph is replaced
            new = lines if extra else []
            replaced = {_also_key(ln) for ln in new}
            content = _with_also(content, [ln for ln in old_also if _also_key(ln) not in replaced] + new)
        if auto_gaps and given:
            content += _not_covered(content, given, "paragraphs of this section") or "\n\nNot yet covered: none"
        elif len(groups) > 1:
            content += _not_covered(content, given)
        first = outs[0] if outs else {"title": cur["title"] if cur else title,
                                       "summary": cur["summary"] if cur else f"{title}: items also recorded here",
                                       "change_note": f"Also recorded from {ex.title}"}
        return Op(
            op="update" if cur else "create", slug=slug, title=first["title"] or title, type=ptype, summary=first["summary"],
            content_md=content, tags=list(dict.fromkeys(t for o in outs for t in o["tags"])) or (cur["tags"] if cur else []),
            base_version=cur["version"] if cur else None, change_note=first["change_note"],
        )

    fields = {k: v for k, v in (ex.meta.get("document") or {}).items() if v}
    source_focus = f"Source page. One-line summary: {plan['source_summary']}" + (
        "\nRecorded for this source: " + "; ".join(f"{k}: {v}" for k, v in fields.items()) if fields else "")

    async def write_index(slug: str, title: str, outline: str) -> Op | None:
        """A split section's own page: the index of its subtopic pages, from what those pages say and cite."""
        cur = existing.get(slug)
        out = await llm.generate_json(system, prompts.with_schema(schema, prompts.write_page_prompt(
            slug=slug, title=title, ptype="topic", focus=prompts.index_prompt_focus(title),
            existing_md=cur["content_md"] if cur else None, material=outline, linkable=linkable, source_slug=source["slug"],
        )), prompts.PAGE_SCHEMA)
        content = _fix_breaks(out["content_md"]).strip()
        if not content:
            raise RuntimeError(f"index page {slug} came back empty")
        return Op(op="update" if cur else "create", slug=slug, title=out["title"] or title, type="topic",
                  summary=out["summary"], content_md=content, tags=out["tags"], base_version=cur["version"] if cur else None,
                  change_note=out["change_note"])

    def outline(sec_slug: str, written: dict) -> str:
        """Each subtopic page with its headings and the clauses cited under each: the material for the index."""
        lines = []
        for sl in index_of.get(sec_slug, []):
            if not (o := written.get(sl)):
                continue
            lines.append(f"[[{sl}]] {o.title}")
            n = len(lines)
            for block in re.split(r"(?m)^(?=#{2,4} )", o.content_md):
                head = re.match(r"#{2,4} (.*)", block)
                labs = list(dict.fromkeys(m.group(2) for m in store.LINK_RE.finditer(block)
                                          if m.group(1).startswith("source-") and m.group(2)))
                if labs:  # under its heading, or (a page without sub-headings) its opening words
                    name = head.group(1).strip() if head else " ".join(store.LINK_RE.sub("", block).split()[:25]) + " ..."
                    lines.append(f"- {name}: cites {', '.join(labs[:40])}")
            if len(lines) == n:
                lines.append("- (no citations on this page)")
        return "\n".join(lines)

    async def write_safe(slug, *args):
        try:
            return await write(slug, *args)
        except Exception as e:  # one page that keeps failing should not sink the whole ingest
            log.warning("ingest: page %s failed: %s", slug, e)
            failed_pages.append({"slug": slug, "error": f"{type(e).__name__}: {e}"})
            return None

    ops = [o for o in await llm.gather_limited(
        [write_safe(source["slug"], ex.title, "source", source_focus, None)]
        + [write_safe(i["slug"], i["title"], i["type"], i["focus"], source["slug"]) for i in items if i["slug"] not in index_of]
    ) if o]
    if index_of:  # split sections: their own pages become the index of the subtopic pages just written
        written = {o.slug: o for o in ops}

        async def index_safe(i):
            try:
                return await write_index(i["slug"], i["title"], outline(i["slug"], written))
            except Exception as e:
                log.warning("ingest: index page %s failed: %s", i["slug"], e)
                failed_pages.append({"slug": i["slug"], "error": f"{type(e).__name__}: {e}"})
                return None

        ops += [o for o in await llm.gather_limited([index_safe(i) for i in items if i["slug"] in index_of]) if o]
    if not ops:
        raise RuntimeError(f"Page writing failed for every page: {failed_pages[:3]}")
    if failed_pages:
        await ctx.progress(failed_pages=failed_pages)
    if missed:
        await ctx.progress(missed_paragraphs=missed)
    # Links to pages that will not exist (never planned, or failed) become plain text; the source stays linkable
    valid = set(existing) | {o.slug for o in ops} | {source["slug"]}
    for o in ops:
        o.content_md = _unlink(o.content_md, valid)
    # every citation must name a source that holds the clause it cites
    citations = await citecheck.check_ops(wiki_id, ops)
    if citations["corrected"] or citations["flagged"]:
        await ctx.progress(citations=citations)

    # 5. Commit
    await ctx.progress(stage="commit")
    summary = f"Ingest: {ex.title}"
    result = await store.commit(wiki_id, "ingest", summary, ops, mode, job_id=ctx.id, source_id=source["id"])
    if result.get("saved_answers_to_check"):
        await ctx.progress(saved_answers_to_check=result["saved_answers_to_check"])
    detail = f"Source [[{source['slug']}]] ({ex.kind}, {len(ex.sections)} sections). {plan['source_summary']}\n" + "\n".join(
        f"- {o.op} [[{o.slug}]]: {o.change_note}" for o in ops
    )
    await store.add_log(wiki_id, "ingest", ex.title, detail + f"\n\nMode: {mode} ({result['status']})")
    label = lambda i: _ref(paras[i]) or f"paragraph {i + 1}"
    routing = {f"{x['num']:02d} {x['name']}": [label(i) for i in own.get(x["num"], [])] for x in sections} if owner else {}
    subtopics = {sl: [label(i) for i in sub["paras"]] for sl, sub in sub_of.items()}
    also_recorded = {f"{x['num']:02d} {x['name']}": [label(i) for i in also[x["num"]]] for x in sections if x["num"] in also}
    return {"source": source["slug"], "mode": mode, "failed_sections": failed, "failed_pages": failed_pages, "empty_retries": empty_retries, "check_fixes": check_fixes, "routing": routing, "subtopics": subtopics, "unassigned": unassigned,
            "also_recorded": also_recorded, "missed_paragraphs": missed, "citations": citations, "fill_passes": fill_passes, "pages": [{"op": o.op, "slug": o.slug} for o in ops], **json.loads(json.dumps(result, default=str))}


async def run_safe(ctx: JobContext, wiki: dict, source: dict, ex: Extracted, mode: str) -> dict:
    """Run ingest; on failure remove the source (if no page uses it) so the upload can be retried."""
    try:
        return await run(ctx, wiki, source, ex, mode)
    except Exception:
        async with get_pool().connection() as conn:
            row = await (
                await conn.execute(
                    """delete from wiki.sources s where s.id = %s
                       and not exists (select 1 from wiki.page_sources ps where ps.source_id = s.id) returning meta->'file' as file""",
                    (source["id"],),
                )
            ).fetchone()
        if row:
            await storage.remove(row["file"])
        raise
