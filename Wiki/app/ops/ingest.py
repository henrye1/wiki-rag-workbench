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
from . import fixpass
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


def _uncited(content: str, paras: list[str]) -> list[str]:
    """The labelled paragraphs in paras that no citation on the page names (each chunk of an uncited paragraph)."""
    labels = [m.group(2) for m in store.LINK_RE.finditer(content) if m.group(2)]
    out, cited = [], {}
    for p in paras:
        ref = _ref(p)
        if not ref or re.fullmatch(r"p(age )?\d+", ref):
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


NUMBERED = re.compile(r"^(?:[A-Z][a-z]+\s+)?(\d+(?:\.\d+)*)\s")  # a numbered heading, "6.4 ..." or "Chapter 6 ..."


REFERS = re.compile(r"\bparagraphs?\s+([0-9][\w.]*|[A-Z]{1,3}\d[\w.]*)")  # "(paragraph 34)", "paragraphs 42A–42H"


def _anchored_paths(paras: list[str], heading_paths: list, kinds: dict | None = None) -> list[list[str]]:
    """Each paragraph's heading path (top heading first). A paragraph under no numbered heading whose label number
    (any letter prefix aside) falls under a numbered heading elsewhere in the source takes that heading's path, so
    guidance in an appendix sits with the requirement it is numbered after (B6.4.2 with "6.4 ..."). Otherwise a
    paragraph whose headings (or, failing those, its text) refer to a paragraph of another kind takes that paragraph's
    path ("Market risk (paragraph 40)" goes with paragraph 40)."""
    paths = [[h for _, h in hp] for hp in heading_paths]
    prefix: dict[str, list[str]] = {}
    for p in paths:
        for k, h in enumerate(p):
            if m := NUMBERED.match(h):
                prefix.setdefault(m.group(1), p[: k + 1])
    out = []
    for para, p in zip(paras, paths):
        num = re.sub(r"^[A-Za-z]+", "", _ref(para))
        if re.fullmatch(r"\d+(?:\.\d+)+", num):  # a numbered heading the paragraph's own number is not under was
            # carried over a gap in the source (an excerpt that jumps from 3.2.2 to 5.7.9): it is not this paragraph's
            under = lambda h: not (m := NUMBERED.match(h)) or num == m.group(1) or num.startswith(m.group(1) + ".")
            if not all(map(under, p)):
                p = [h for h in p if under(h)]
                p = p or [num.rsplit(".", 1)[0]]  # no heading left: the paragraph's own parent number (5.7.9 -> 5.7)
        if not any(NUMBERED.match(h) for h in p) and num:
            best = max((n for n in prefix if num.startswith(n + ".")), key=len, default=None)
            if best:
                p = prefix[best] + [h for h in p[-1:] if h not in prefix[best]]
        out.append(p)
    if kinds:
        at = {}
        for k, para in enumerate(paras):
            at.setdefault(_ref(para), k)
        for k, para in enumerate(paras):
            own = kinds.get(_ref(para))
            if not own or any(NUMBERED.match(h) for h in out[k]):
                continue
            for text in (" ".join(paths[k]), para):  # its headings first, then its text
                hit = next((at[r] for r in (m.rstrip(".") for m in REFERS.findall(text)) if r in at and kinds.get(r) not in (None, own)), None)
                if hit is not None:
                    out[k] = list(out[hit])
                    break
    return out


def _size_split(idx: list[int], paths: list[list[str]], words: list[int], limit: int, depth: int = 0,
                extra_words: int = 0, once: bool = False) -> list[tuple[list[str], list[int]]]:
    """Paragraphs over the size limit, split by the source's headings: at the highest heading level (from depth down)
    where they fall under more than one heading, each group split again one level down while still over the limit.
    Returns (heading names, paragraphs) per group; a paragraph with no heading at that level stays with the one before."""
    if sum(words[i] for i in idx) + extra_words <= limit:
        return [([], idx)]
    for d in range(depth, max((len(paths[i]) for i in idx), default=0)):
        heads = [paths[i][d] if d < len(paths[i]) else None for i in idx]
        if once:  # a paragraph with no heading at this level keeps its own heading (the level above) as its group
            heads = [h or (paths[i][d - 1] if 0 < d <= len(paths[i]) else None) for i, h in zip(idx, heads)]
        if len({h for h in heads if h}) > 1:
            groups: dict[str, list[int]] = {}
            last = next((h for h in heads if h), None)
            for i, h in zip(idx, heads):
                last = h or last
                groups.setdefault(last, []).append(i)
            out = []
            for name, part in groups.items():
                if once:  # one level only: with its parent heading, so small groups join only within the same parent
                    # the heading above this group's own heading, taken from a paragraph that has it
                    have = [paths[i] for i in part if name in paths[i]]
                    parent = (have[0][have[0].index(name) - 1] if have[0].index(name) > 0 else "") if have else \
                        next((paths[i][d - 1] for i in part if 0 < d <= len(paths[i])), "")
                    out.append(([parent, name], part))
                else:
                    out += [([name] + sub, p) for sub, p in _size_split(part, paths, words, limit, d + 1)]
            return out
    return [([], idx)]  # no heading to split by: it stays one page


def _join_small(parts: list, words: list[int], minimum: int, limit: int | None = None) -> tuple[list, list]:
    """Groups under the minimum joined to the group before them under the same parent heading (or the one after, if
    first), until none is under it or none can be joined. A join that would go over the limit goes to the other side
    instead; if both would, the small group stays as it is. Returns (groups, [(joined, into)])."""
    parts = [(list(n), list(i), [n[-1]] if n else []) for n, i in parts]  # (path, paragraphs, headings it holds)
    joined, alone = [], set()  # alone: small groups that cannot join either side without going over
    size = lambda idx: sum(words[i] for i in idx)
    while True:
        for k, (names, idx, heads) in enumerate(parts):
            if size(idx) >= minimum or tuple(heads) in alone:
                continue
            same = [j for j in range(len(parts)) if j != k and parts[j][0][:-1] == names[:-1]]
            before = max((j for j in same if j < k), default=None)
            after = min((j for j in same if j > k), default=None)
            fits = lambda j: j is not None and (not limit or size(parts[j][1]) + size(idx) <= limit)
            j = next((x for x in ((before, after) if before is not None else (after, before)) if fits(x)), None)
            if j is None:
                if before is not None or after is not None:
                    alone.add(tuple(heads))
                continue
            if j is not None:
                tn, ti, th = parts[j]
                order = sorted([(min(ti), th), (min(idx), heads)])  # headings in document order
                parts[j] = (tn, sorted(ti + idx), order[0][1] + order[1][1])
                joined.append((names[-1] if names else "", tn[-1] if tn else ""))
                del parts[k]
                break
        else:  # a joined group is named after every heading it holds, in document order
            return [(n[:-1] + [HEADS_SEP.join(h)] if n else n, i) for n, i, h in parts], joined


HEADS_SEP = " · "  # between the headings of a group joined from several


def _sub_names(title: str, split: bool = True) -> list[str]:
    """A subtopic page's group names, read back from its title ("<section>: <name> – <name>"); split: each heading of a
    joined group on its own."""
    names = title.split(": ", 1)[-1].split(" \u2013 ")
    return [h for n in names for h in n.split(HEADS_SEP)] if split else names


def _sub_slug(sec_slug: str, names: list[str], slug_words: int | None) -> str:
    """A subtopic slug: the heading's own number where it has one (6.3 -> <section>-6-3), else its first words."""
    head = names[-1].split(HEADS_SEP)[0] if names else ""  # a joined group: its first heading
    if m := NUMBERED.match(head):
        return f"{sec_slug}-{m.group(1).replace('.', '-')}"
    return f"{sec_slug}-{slugify(' '.join(head.split()[:slug_words]) if slug_words else head)}"


def _add_blocks(md: str, text: str) -> str:
    """A page with text added word for word at the end of its body: before its "Also recorded here" lines and its
    "Not yet covered" note."""
    body, also_lines = _split_also(md)
    head, sep, tail = body.partition("\n\nNot yet covered")
    return _with_also(f"{head}\n\n{text}{sep}{tail}", also_lines)


def _index_md(sec_name: str, subs: list[dict], titles: dict[str, str]) -> tuple[str, str]:
    """A split section's index page, built from its subtopic pages: each page's link and title, and under it each of
    its headings with the clauses cited there, named with their own source. It links every subtopic page and holds no
    claims: the clauses are listed, not cited, and nothing a subtopic page states (its summary included) is copied.
    Returns (content, one-line summary)."""
    blocks = []
    for p in subs:
        lines = [f"## [[{p['slug']}|{p['title']}]]"]
        for block in re.split(r"(?m)^(?=#{2,4} )", p["content_md"]):
            head = re.match(r"#{2,4} (.*)", block)
            by_src: dict[str, list[str]] = {}
            for m in store.LINK_RE.finditer(block):
                if m.group(1).startswith("source-") and m.group(2) and m.group(2) not in by_src.get(m.group(1), []):
                    by_src.setdefault(m.group(1), []).append(m.group(2).strip())
            if by_src:  # under its heading, or (a page without sub-headings) its opening words
                name = store.LINK_RE.sub(lambda m: m.group(2) or m.group(1), head.group(1)).strip() if head else \
                    " ".join(store.LINK_RE.sub("", block).split()[:25]) + " ..."
                lines.append(f"- {name}: cites " + "; ".join(f"{titles.get(src, src)} {', '.join(labs[:40])}"
                                                             for src, labs in by_src.items()))
        blocks.append("\n".join(x for x in lines if x))
    summary = f"{sec_name}: index of its subtopic pages: " + "; ".join(p["title"].split(": ", 1)[-1] for p in subs)
    return "\n\n".join(blocks), summary[:500]


def _blocks(md: str) -> list[str]:
    """A page's text as blocks (a heading stays with the block under it)."""
    out, held = [], []
    for b in (x.strip() for x in re.split(r"\n\s*\n", md) if x.strip()):
        if re.fullmatch(r"#{1,6} [^\n]*", b):
            held.append(b)
            continue
        out.append("\n\n".join(held + [b]))
        held = []
    return out + (["\n\n".join(held)] if held else [])


async def _move_old_write_ups(wiki_id, index_of: dict, sub_of: dict, existing: dict, written: dict, ops: list,
                              sec_of: dict, chk) -> dict:
    """A section page split for the first time may hold write-ups from earlier uploads. Each block moves, word for
    word, to the sub-page whose heading is on the heading path of the source paragraph the block cites; a block with
    no matching heading goes to a sub-page named after that paragraph's nearest heading, never the source's title.
    Returns, per section, what moved where."""
    out = {}
    for sec_slug, subs in index_of.items():
        cur = existing.get(sec_slug)
        if not cur or any(x.startswith(sec_slug + "-") and existing[x]["type"] == "subtopic" for x in existing):
            continue  # nothing held yet, or already an index
        body = "\n".join(l for l in _split_also(cur["content_md"])[0].split("\n") if not l.startswith("Not yet covered"))
        blocks = [b for b in _blocks(body) if store.LINK_RE.search(b) and re.search(r"\[\[source-", b)]
        if not blocks:
            continue
        cited = {m.group(1) for b in blocks for m in store.LINK_RE.finditer(b) if m.group(1).startswith("source-")}
        async with get_pool().connection() as conn:
            rows = await (await conn.execute("select slug, title, text, meta from wiki.sources where wiki_id = %s and slug = any(%s)",
                                             (wiki_id, list(cited)))).fetchall()
        src = {}
        for r in rows:
            sp = [b.strip() for b in re.split(r"\n\s*\n", r["text"] or "") if b.strip()]
            hp = (r["meta"] or {}).get("heading_paths") or []
            paths = _anchored_paths(sp, hp if len(hp) == len(sp) else [[] for _ in sp], (r["meta"] or {}).get("para_kinds"))
            path_of, last = {}, []
            for p, pa in zip(sp, paths):  # a paragraph with no heading of its own is under the one before it
                last = pa or last
                if _ref(p):
                    path_of[_ref(p)] = last
            src[r["slug"]] = {"title": r["title"], "path": path_of}
        to: dict[str, list[str]] = {}
        for b in blocks:
            m = next((m for m in store.LINK_RE.finditer(b) if m.group(1) in src and m.group(2)), None)
            path = src[m.group(1)]["path"].get(re.sub(r"(?:\s*\([^)]*\))+$", "", m.group(2).strip()), []) if m else []
            heads_of = lambda x: [h for n in sub_of[x]["names"] for h in n.split(HEADS_SEP)]
            match = [sl for sl in subs if sub_of.get(sl) and any(h in path for h in heads_of(sl))]
            if match:  # the sub-page whose heading is deepest on the block's path
                sl = max(match, key=lambda x: max(path.index(h) for h in heads_of(x) if h in path))
            elif path:  # a sub-page named after the cited paragraph's nearest heading
                sl = _sub_slug(sec_slug, path[-1:], chk.slug_words if chk else None)
                if sl not in sub_of:
                    sub_of[sl] = {"sec": sec_of[sec_slug], "names": path[-1:], "paras": []}
            else:  # the source has no headings: the section's first sub-page
                sl = subs[0]
            to.setdefault(sl, []).append(b)
        new_pages = []
        for sl, bs in to.items():
            text = "\n\n".join(bs)
            if sl in written:  # added word for word, before the page's "Not yet covered" line
                written[sl].content_md = _add_blocks(written[sl].content_md, text)
            else:
                sec = sec_of[sec_slug]
                o = Op(op="update" if sl in existing else "create", slug=sl, type="subtopic",
                       title=f"{sec['name']}: {sub_of[sl]['names'][-1]}", summary=f"{sec['name']}: {sub_of[sl]['names'][-1]}",
                       content_md=text, tags=[], base_version=existing[sl]["version"] if sl in existing else None,
                       change_note="Moved from the section page when it was split")
                ops.append(o)
                written[sl] = o
                new_pages.append(sl)
            if sl not in subs:
                subs.append(sl)
        out[sec_slug] = {"blocks": len(blocks), "to": {sl: len(bs) for sl, bs in to.items()}, "new_pages": new_pages,
                         "cites": checks.cites("\n\n".join(blocks))}
        log.info("ingest: section page %s split for the first time: %s earlier blocks moved to %s", sec_slug, len(blocks),
                 ", ".join(f"{sl} ({n})" for sl, n in out[sec_slug]["to"].items()))
    return out


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
    # stubs (the schema's stub forms: a deleted or left-out paragraph) go to no page: not written up, not checked
    stubs = {i for i, p in enumerate(paras) if checks.is_stub(p, chk)}
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
            owner.update({i: ex_sec["num"] for i, p in enumerate(paras) if (_ref(p) or i) in labelled and i not in stubs})
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

        todo = [i for i in range(len(paras)) if i not in owner and i not in stubs]
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
        cand = [i for i in range(len(paras)) if owner.get(i) != sec["num"] and i not in stubs]

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
    # a section that already has a page keeps it: a planned page for the same section is that page
    has_page: dict[int, str] = {}
    for sl, p in sorted(existing.items(), key=lambda kv: len(kv[0])):
        if p["type"] == "topic" and (sec := _section_for(sections, p["title"], sl)) and sec["num"] not in has_page:
            has_page[sec["num"]] = sl
    kept = []
    for i in items:
        sec = _section_for(sections, i["title"], i["slug"]) if i["type"] == "topic" else None
        if sec and sec["num"] in has_page and i["slug"] != has_page[sec["num"]]:
            if any(x["slug"] == has_page[sec["num"]] for x in kept):
                continue  # the section's page is planned already
            i = {**i, "slug": has_page[sec["num"]], "action": "update", "title": existing[has_page[sec["num"]]]["title"]}
        kept.append(i)
    items = kept
    seen |= {i["slug"] for i in items}
    sec_of: dict[str, dict] = {}  # topic page -> its section (one page per section)
    for i in items:
        sec = _section_for(sections, i["title"], i["slug"]) if i["type"] == "topic" else None
        if sec and sec["num"] not in {x["num"] for x in sec_of.values()}:
            sec_of[i["slug"]] = sec
    if sections:  # every section gets a page: its existing one, else named like the others (e.g. ifrs-9-<section>)
        covered = {x["num"] for x in sec_of.values()}
        named = {**{sl: s for s in sections for sl in [has_page.get(s["num"])] if sl}, **sec_of}
        prefix = next((sl[: -len(slugify(x["name"]))] for sl, x in named.items() if sl.endswith(slugify(x["name"]))), "")
        for sec in sections:
            slug = has_page.get(sec["num"]) or prefix + slugify(sec["name"])
            if sec["num"] in covered or slug in sec_of:
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
    group_name: dict[int, list[str]] = {i: [by_num[g]["name"]] for i, g in group_of.items() if g in by_num}
    # split by size (the schema's Checks list): a section (or one of its groups) whose paragraphs would make a page over
    # the limit is split by the source's own headings; what the page already holds counts too
    splits: list[dict] = []
    joins: list[dict] = []  # small groups joined to a neighbour (the schema's subtopic minimum)
    split_basis: dict = {}  # the heading paths and word counts the split used
    limit = chk.page_size_limit if chk else None
    sub_fixed: dict[int, str] = {}  # paragraph -> an existing subtopic page of its (already split) section
    if limit and owner:
        hp = ex.meta.get("heading_paths") or []
        paths = _anchored_paths(paras, hp if len(hp) == len(paras) else [[] for _ in paras], ex.meta.get("para_kinds"))
        words = [len(p.split()) for p in paras]
        split_basis.update(paths=paths, words=words)
        additive = {x["num"] for x in sections if re.search(r"\bADDITIVE\b", x["brief"])}  # its also-recorded lines stay together
        for num, sl in slug_of.items():
            mine = [i for i, n in sorted(owner.items()) if n == num]
            if not mine or num in additive:
                continue
            already = any(x.startswith(sl + "-") and existing[x]["type"] == "subtopic" for x in existing)
            held = len(existing[sl]["content_md"].split()) if sl in existing and not already else 0
            groups: dict[tuple, list[int]] = {}
            for i in mine:
                groups.setdefault(tuple(group_name.get(i, [])), []).append(i)
            for key, idx in groups.items():
                parts = _size_split(idx, paths, words, limit, extra_words=0 if key else held)
                if len(parts) > 1 and chk.subtopic_minimum:
                    parts, joined = _join_small(parts, words, chk.subtopic_minimum, limit)
                    joins.extend({"section": num, "joined": a, "into": b} for a, b in joined)
                if len(parts) > 1:
                    for names, part in parts:
                        for i in part:
                            group_name[i] = list(key) + names
                    log.info("ingest: section %s%s is over %s words: split by headings into %s pages", num,
                             f" ({' / '.join(key)})" if key else "", limit, len(parts))
        # a section an earlier upload split stays an index: each new paragraph goes to a subtopic page, the one whose
        # heading is on its heading path, else one for its top heading (split by size and joined like any other)
        for num, sl in slug_of.items():
            olds = {x: _sub_names(existing[x]["title"]) for x in existing
                    if x.startswith(sl + "-") and existing[x]["type"] == "subtopic"}
            todo = [i for i, n in sorted(owner.items()) if n == num and not group_name.get(i)]
            if not olds or not todo or num in additive:
                continue
            last: list[str] = []
            free = []
            for i in todo:
                path = last = paths[i] or last  # a paragraph with no heading of its own is under the one before it
                match = [x for x, heads in olds.items() if any(h in path for h in heads)]
                if match:
                    sub_fixed[i] = max(match, key=lambda x: max(path.index(h) for h in olds[x] if h in path))
                else:
                    free.append(i)
            tops: dict[tuple, list[int]] = {}
            for i in free:
                tops.setdefault(tuple((paths[i] or [""])[:1]), []).append(i)
            parts = [([*top, *names] if top != ("",) else names, part)
                     for top, idx in tops.items() for names, part in _size_split(idx, paths, words, limit, depth=1)]
            if len(parts) > 1 and chk.subtopic_minimum:
                parts, joined = _join_small(parts, words, chk.subtopic_minimum, limit)
                joins.extend({"section": num, "joined": a, "into": b} for a, b in joined)
            for names, part in parts:
                for i in part:
                    if names:
                        group_name[i] = names
                    else:  # no heading anywhere: the section's first subtopic page
                        sub_fixed[i] = next(iter(olds))
            log.info("ingest: section %s already split: %s new paragraphs to its subtopic pages, %s to new ones", num,
                     len(todo) - len(free), len(free))
    sub_of: dict[str, dict] = {}  # subtopic page -> its section, its group names and its paragraphs
    for i, sl in sorted(sub_fixed.items()):  # to a subtopic page an earlier upload made
        sub_of.setdefault(sl, {"sec": by_num[owner[i]], "names": _sub_names(existing[sl]["title"], split=False),
                               "paras": []})["paras"].append(i)
    for i, names in sorted(group_name.items()):
        if i in sub_fixed:
            continue
        if owner.get(i) in slug_of and names:
            sl = _sub_slug(slug_of[owner[i]], names, chk.slug_words if chk else None)
            if sl in sub_of and sub_of[sl]["names"] != names:  # two groups with the same short name: add the parent's
                sl = _sub_slug(_sub_slug(slug_of[owner[i]], names[:-1], chk.slug_words if chk else None), names, chk.slug_words if chk else None)
            sub_of.setdefault(sl, {"sec": by_num[owner[i]], "names": names, "paras": []})["paras"].append(i)
    index_of: dict[str, list[str]] = {}  # split section page -> its subtopic pages written now
    for sl, sub in sub_of.items():
        index_of.setdefault(slug_of[sub["sec"]["num"]], []).append(sl)
        items.append({"action": "update" if sl in existing else "create", "slug": sl, "type": "subtopic",
                      "title": f"{sub['sec']['name']}: {' – '.join(sub['names'])}",
                      "focus": f"Section {sub['sec']['num']:02d}: {sub['sec']['name']}, subtopic {' – '.join(sub['names'])}"})
    for sec_slug, subs in index_of.items():
        sec = sec_of[sec_slug]
        splits.append({"section": f"{sec['num']:02d} {sec['name']}", "page": sec_slug,
                       "by": ("size" if not (chk and sec["num"] in chk.split)
                              else "examples, then size" if any(len(sub_of[x]["names"]) > 1 for x in subs) else "examples"),
                       "pages": [{"slug": x, "paragraphs": len(sub_of[x]["paras"]),
                                  "source_words": sum(len(paras[i].split()) for i in sub_of[x]["paras"])} for x in subs],
                       "joined": [f"{j['joined']} -> {j['into']}" for j in joins if j["section"] == sec["num"]]})
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
    cite_ctx = await fixpass.cite_context(wiki_id, [x["name"] for x in sections])  # this source included
    src_labels = cite_ctx["labels"].get(source["slug"], set())
    cite_failures = lambda text: fixpass.cite_failures(text, cite_ctx, chk)
    fill_passes: list[dict] = []  # what each extra writing pass was asked for and returned
    missed: list[dict] = []  # paragraphs still not written up (or not also recorded) after the extra passes
    restored: list[dict] = []  # earlier write-ups a rewrite dropped and its fix rounds did not bring back: put back as they were

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
            return await fixpass.fix_rounds(schema=schema, slug=slug, title=title, text=text, check=check,
                                            sources_text=sources_text, linkable=linkable, parse=parse, kind=kind,
                                            record=check_fixes, out_schema=out_schema, ok=ok, may_shrink=may_shrink,
                                            clause=lambda c: fixpass.is_clause(c, cite_ctx))

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
                "section", content, lambda x: (checks.section_failures(x, given, para_kinds, source_slug, chk, _covers, src_labels)
                                               if chk else []) + cite_failures(x),
                sources_text="\n\n".join(given), parse=lambda r: _fix_breaks(r).strip(),
                ok=lambda old, new: not ({_ref(p) for p in _uncited(new, given)} - {_ref(p) for p in _uncited(old, given)}))

        if ptype == "source" and owner and sec_of and chk and chk.source_parts:
            informed = {sl for sl, x in sec_of.items() if own.get(x["num"]) or also.get(x["num"])}
            args = dict(fields=fields, authority=authority, informed=informed, sections=set(sec_of),
                        source_slug=source["slug"], c=chk)
            if skipped := checks.source_failures(content, **args)[1]:
                log.info("ingest: source page %s: not checked: %s", slug, "; ".join(skipped))
            content = await check_and_fix("source page", checks.detail_lines(content, chk),
                                          lambda x: checks.source_failures(x, **args)[0] + cite_failures(x),
                                          sources_text="\n\n".join(authority),
                                          parse=lambda r: checks.detail_lines(_fix_breaks(r).strip(), chk),
                                          may_shrink=True)  # a source page with too many takeaways must lose some

        if cur and not (chk and slug in chk.no_claim_pages):
            # a rewrite keeps every source paragraph the page cited before: one it dropped is sent back, then reported
            earlier = fixpass.earlier_cites(cur_body, cite_ctx)
            if dropped := earlier - checks.cites(content):
                texts = "\n\n".join(f"From [[{c.split('|', 1)[0]}]]: {cite_ctx['texts'][c.split('|', 1)[0]][c.split('|', 1)[1]]}"
                                     for c in sorted(dropped))
                old = "\n\n".join(b for b in _blocks(cur_body) if checks.cites(b) & dropped)
                content = await check_and_fix(
                    "earlier citations", content, lambda x: fixpass.kept_failures(x, earlier),
                    sources_text=f"{texts}\n\nWhat the page said about them before:\n\n{old}",
                    parse=(lambda r: checks.detail_lines(_fix_breaks(r).strip(), chk)) if ptype == "source" and chk
                    else (lambda r: _fix_breaks(r).strip()))
                if still := earlier - checks.cites(content):  # what the page said about them before, word for word
                    back = [b for b in _blocks(cur_body) if checks.cites(b) & still]
                    content = _add_blocks(content, "\n\n".join(back))
                    restored.append({"page": slug, "paragraphs": sorted(still), "blocks": len(back),
                                     "still_missing": sorted(earlier - checks.cites(content))})
                    if gone := sorted(earlier - checks.cites(content)):
                        missed.append({"page": slug, "paragraphs": gone, "reason": "cited before this upload, dropped on rewrite"})

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

    def index_page(sec_slug: str, written: dict) -> Op:
        """A split section's own page: the index of all its subtopic pages, those an earlier upload made included."""
        cur = existing.get(sec_slug)
        page = lambda x: ({"slug": x, "title": written[x].title, "summary": written[x].summary,
                           "content_md": written[x].content_md} if x in written else existing[x])
        subs = list(dict.fromkeys(index_of.get(sec_slug, []) + [
            x for x in existing if x.startswith(sec_slug + "-") and existing[x]["type"] == "subtopic"]))
        if cur:  # in the order the page listed them before; new ones after
            subs.sort(key=lambda x: (cur["content_md"].find(f"[[{x}") % (len(cur["content_md"]) + 1)
                                     if f"[[{x}" in cur["content_md"] else len(cur["content_md"]) + 1))
        content, summary = _index_md(sec_of[sec_slug]["name"], [page(x) for x in subs], cite_ctx["titles"])
        return Op(op="update" if cur else "create", slug=sec_slug, title=cur["title"] if cur else sec_of[sec_slug]["name"],
                  type="topic", summary=summary, content_md=content, tags=cur["tags"] if cur else [],
                  base_version=cur["version"] if cur else None, change_note=f"Index of {len(subs)} subtopic pages")

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
    resplit = []  # sub-pages over the limit once written, split again one level down
    if limit and split_basis and index_of:
        paths, words = split_basis["paths"], split_basis["words"]
        for o in [o for o in ops if o.slug in sub_of and len(o.content_md.split()) > limit and sub_of[o.slug]["paras"]]:
            sub = sub_of[o.slug]
            top = sub["names"][-1].split(HEADS_SEP)[0]
            depth = 1 + max((paths[i].index(top) for i in sub["paras"] if top in paths[i]), default=-1)
            parts = _size_split(sub["paras"], paths, words, 0, depth, once=True)
            if chk.subtopic_minimum and len(parts) > 1:
                parts, joined = _join_small(parts, words, chk.subtopic_minimum, limit)
                joins.extend({"section": sub["sec"]["num"], "joined": a, "into": b} for a, b in joined)
            if len(parts) < 2:
                continue  # no heading below to split by: the page stays as written
            sec_slug = slug_of[sub["sec"]["num"]]
            del sub_of[o.slug]  # replaced by its pieces: its plain slug is free again
            new = []
            for names, part in parts:
                full = sub["names"] + names[-1:]  # the parent heading was only for joining
                sl = _sub_slug(sec_slug, full, chk.slug_words)
                if sl in sub_of:
                    sl = _sub_slug(o.slug, names, chk.slug_words)
                sub_of[sl] = {"sec": sub["sec"], "names": full, "paras": part}
                for i in part:
                    para_sub[i] = sl
                new.append(sl)
            log.info("ingest: sub-page %s is %s words once written, over %s: split again into %s", o.slug,
                     len(o.content_md.split()), limit, ", ".join(new))
            resplit.append({"page": o.slug, "words": len(o.content_md.split()), "into": new})
            ops.remove(o)
            subs = index_of[sec_slug]
            subs[subs.index(o.slug):subs.index(o.slug) + 1] = new
            ops += [x for x in await llm.gather_limited([write_safe(
                sl, f"{sub['sec']['name']}: {' – '.join(sub_of[sl]['names'])}", "subtopic",
                f"Section {sub['sec']['num']:02d}: {sub['sec']['name']}, subtopic {' – '.join(sub_of[sl]['names'])}",
                source["slug"]) for sl in new]) if x]
        for x in splits:
            x["pages"] = [{"slug": sl, "paragraphs": len(sub_of[sl]["paras"]),
                           "source_words": sum(len(paras[i].split()) for i in sub_of[sl]["paras"])} for sl in index_of.get(x["page"], [])]
            x["split_again"] = [r for r in resplit if any(sl in index_of.get(x["page"], []) for sl in r["into"])]
    if index_of:  # split sections: their own pages become the index of the subtopic pages just written
        written = {o.slug: o for o in ops}
        moved = await _move_old_write_ups(wiki_id, index_of, sub_of, existing, written, ops, sec_of, chk)
        labels_here = {_ref(p) for p in paras if re.search(r"[A-Za-z.]", _ref(p))}  # not bare numbers: too common in text
        for sec_slug, subs in index_of.items():
            on_page = {_ref(paras[i]): sl for sl in subs for i in sub_of[sl]["paras"] if _ref(paras[i]) in labels_here}
            for sl in subs:
                if not (o := written.get(sl)):
                    continue
                text = " ".join(paras[i] for i in sub_of[sl]["paras"])
                refers = {on_page[lab] for lab in on_page if on_page[lab] != sl and re.search(rf"(?<![\w.]){re.escape(lab)}(?![\w]|\.\d)", text)}
                if refers := sorted(x for x in refers if f"[[{x}" not in o.content_md):
                    o.content_md += "\n\nRelated pages in this section: " + ", ".join(f"[[{x}]]" for x in refers)
            # coverage: every paragraph of the section is on exactly one of its pages, and that page cites it
            mine = [i for sl in subs for i in sub_of[sl]["paras"]]
            uncited = [_ref(paras[i]) for sl in subs if (o := written.get(sl)) for i in sub_of[sl]["paras"] if _uncited(o.content_md, [paras[i]])]
            rec = next(x for x in splits if x["page"] == sec_slug)
            rec["coverage"] = {"paragraphs": len(mine), "on_one_page": len(set(mine)) == len(mine),
                               "not_cited_on_their_page": list(dict.fromkeys(x for x in uncited if x)),
                               "pages_not_written": [sl for sl in subs if sl not in written]}
            if sec_slug in moved:  # what the page held before the split: every citation it had is on one of its pages
                m = moved[sec_slug]
                on_pages = set().union(*(checks.cites(written[sl].content_md) for sl in index_of[sec_slug] if sl in written))
                rec["moved"] = {"blocks": m["blocks"], "to": m["to"], "earlier_citations": len(m["cites"]),
                                "earlier_citations_missing": sorted(m["cites"] - on_pages)}
                rec["pages"] += [{"slug": sl, "paragraphs": 0, "source_words": 0, "moved_only": True}
                                 for sl in m["new_pages"]]

        indexes = [index_page(i["slug"], written) for i in items if i["slug"] in index_of]
        ops += indexes
        for o in indexes:  # built to hold no claims and link every subtopic page: checked all the same
            subs = {x.slug for x in ops if x.type == "subtopic" and x.slug.startswith(o.slug + "-")} | {
                x for x in existing if x.startswith(o.slug + "-") and existing[x]["type"] == "subtopic"}
            if checks.holds_no_claims(chk, o.slug, True) and (
                    bad := checks.no_claim_failures(o.content_md, subs, chk, cite_ctx["names"])):
                check_fixes.append({"page": o.slug, "kind": "no claims", "found": len(bad), "still": len(bad), "failures": bad})
    for top in [o for o in ops if chk and o.slug in chk.no_claim_pages]:
        # a page that holds no claims (the schema's Checks): each claim on it moves to the page that holds the paragraph
        # it cites (this upload's paragraphs: the page they were written up on; earlier ones: a page that cites them)
        on = {o.slug: o for o in ops}
        is_index = lambda sl: sl in index_of or any(x.startswith(sl + "-") and existing[x]["type"] == "subtopic" for x in existing)
        holders = [sl for sl in list(on) + [x for x in existing if x not in on] if sl not in chk.no_claim_pages and not is_index(sl)
                   and (on[sl].type if sl in on else existing[sl]["type"]) in ("topic", "subtopic")]
        cites_of = {sl: checks.cites(on[sl].content_md if sl in on else existing[sl]["content_md"]) for sl in holders}
        here = {f"{source['slug']}|{_ref(p)}": i for i, p in enumerate(paras) if _ref(p)}

        def home(cite: str) -> str | None:
            if (i := here.get(cite)) is not None and (sl := para_sub.get(i) or slug_of.get(owner.get(i))) in cites_of:
                return sl
            return next((sl for sl in holders if cite in cites_of[sl]), None)

        top.content_md, moves = fixpass.move_claims(top.slug, top.content_md, home, lambda sl: cites_of.get(sl, set()),
                                                    check_fixes, cite_ctx["names"])
        for sl, xs in moves.items():
            if sl not in on:
                cur = existing[sl]
                on[sl] = Op(op="update", slug=sl, title=cur["title"], type=cur["type"], summary=cur["summary"],
                            content_md=cur["content_md"], tags=cur["tags"] or [], base_version=cur["version"],
                            change_note=f"Claims moved here from [[{top.slug}]]")
                ops.append(on[sl])
            on[sl].content_md = _add_blocks(on[sl].content_md, "\n\n".join(xs))
        top.content_md = await fixpass.fix_rounds(
            schema=schema, slug=top.slug, title=top.title, text=top.content_md, sources_text="", linkable=linkable,
            check=lambda x: checks.no_claim_failures(x, set(sec_of), chk, cite_ctx["names"]) + cite_failures(x),
            clause=lambda c: fixpass.is_clause(c, cite_ctx),
            parse=lambda r: _fix_breaks(r).strip(), kind="no claims", record=check_fixes,
            ok=lambda old, new: not checks.cites(new) - checks.cites(old))  # a fix adds no claim
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
    # a page whose write-ups moved to other pages (a section page now an index, a page that holds no claims): what it
    # cited before must be cited on one of the wiki's pages after this upload
    final = {sl: p["content_md"] for sl, p in existing.items()} | {o.slug: o.content_md for o in ops}
    on_some_page = set().union(*map(checks.cites, final.values()))
    for o in ops:
        if o.slug in existing and (o.slug in index_of or (chk and o.slug in chk.no_claim_pages)):
            if gone := sorted(fixpass.earlier_cites(existing[o.slug]["content_md"], cite_ctx) - on_some_page):
                missed.append({"page": o.slug, "paragraphs": gone, "reason": "cited before this upload, on no page after it moved"})
    if missed:
        await ctx.progress(missed_paragraphs=missed)

    # 5. Commit
    await ctx.progress(stage="commit")
    summary = f"Ingest: {ex.title}"
    result = await store.commit(wiki_id, "ingest", summary, ops, mode, job_id=ctx.id, source_id=source["id"])
    if result.get("saved_answers_to_check"):
        await ctx.progress(saved_answers_to_check=result["saved_answers_to_check"])
    detail = f"Source [[{source['slug']}]] ({ex.kind}, {len(ex.sections)} sections). {plan['source_summary']}\n" + "\n".join(
        f"- {o.op} [[{o.slug}]]: {o.change_note}" for o in ops
    )
    if splits:
        detail += "\n\nSplit sections:\n" + "\n".join(
            f"- {x['section']} ({x['by']}): " + ", ".join(f"[[{p['slug']}]] ({p['paragraphs']} paragraphs, {p['source_words']} source words)"
                                                     for p in x["pages"]) for x in splits)
        await ctx.progress(splits=splits)
    await store.add_log(wiki_id, "ingest", ex.title, detail + f"\n\nMode: {mode} ({result['status']})")
    label = lambda i: _ref(paras[i]) or f"paragraph {i + 1}"
    routing = {f"{x['num']:02d} {x['name']}": [label(i) for i in own.get(x["num"], [])] for x in sections} if owner else {}
    subtopics = {sl: [label(i) for i in sub["paras"]] for sl, sub in sub_of.items()}
    also_recorded = {f"{x['num']:02d} {x['name']}": [label(i) for i in also[x["num"]]] for x in sections if x["num"] in also}
    return {"source": source["slug"], "mode": mode, "failed_sections": failed, "failed_pages": failed_pages, "empty_retries": empty_retries, "check_fixes": check_fixes, "routing": routing, "subtopics": subtopics, "splits": splits, "unassigned": unassigned, "stubs": [_ref(paras[i]) for i in sorted(stubs)],
            "also_recorded": also_recorded, "missed_paragraphs": missed, "restored": restored, "citations": citations, "fill_passes": fill_passes, "pages": [{"op": o.op, "slug": o.slug} for o in ops], **json.loads(json.dumps(result, default=str))}


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
