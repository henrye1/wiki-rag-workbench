"""Ingest: source -> notes -> plan -> page writes -> changeset."""
import asyncio
import collections
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
    """Paragraph group from its label: 5.5.3 -> 5.5, B5.5.17 -> B5.5, defined terms ("<prefix>: <term>") together by
    their prefix; unlabelled stand alone."""
    m = re.match(r"^\[([^\]]+)\]", para)
    ref = m.group(1).strip() if m else ""
    if ": " in ref:
        return ref.split(":", 1)[0]
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
    """Whether a citation label (e.g. "4.2.1(a)", "paragraphs B4.1.1–B4.1.26", "<prefix>:credit loss") cites ref."""
    if ": " in ref:  # a defined term ("<prefix>: <term>"): cited where its term is
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
CITE_RUN_ON = re.compile(r"(\]\]\)?[.;:]?)(?=[A-Z])")  # "...|5.5.7]].The objective ...": the paragraph break was left out
BULLET_RUN_ON = re.compile(r"(\]\]\)?[.;:]?|(?<=\w):|^#{2,4} [^\n*\u2022\[]*?\S)[ \t]*(?=[*\u2022-]\s)", re.M)  # "...]].* Next", "...]])* Next", "include:* An", "### Key takeaways* An"
TABLE_RUN_ON = re.compile(r"^.*\|\|\s*:?-{3}.*$", re.M)  # a table on one line: "...: | A | B ||---|---|| 1 | 2 |"


def _unflatten_table(m: re.Match) -> str:
    """A table whose rows were run onto one line: each row on its own line, the table apart from the text before it."""
    line = m.group(0)
    start = store.LINK_RE.sub(lambda x: "x" * len(x.group(0)), line).index("|")  # the first "|" outside a link
    lead, rows = line[:start].rstrip(), line[start:].replace("||", "|\n|")
    return f"{lead}\n\n{rows}" if lead else rows


def _restore_tables(text: str, paras: list[str]) -> str:
    """A source table (a paragraph whose lines are rows of cells split by "|") that the page holds with its rows run
    onto one line, with or without the cells' outer bars and a header rule: put back as a table, a row per line,
    apart from the text around it."""
    for p in paras:
        lines = [ln.strip() for ln in re.sub(r"^\[[^\]]+\]\s*", "", p).split("\n")]
        # a markdown row has outer bars; the reader's rows do not (an empty first cell starts the line with a bar)
        rows = [[c.strip() for c in (ln[1:-1] if ln.startswith("|") and ln.endswith("|") else ln).split("|")] for ln in lines]
        if len(rows) < 2 or any(len(r) < 2 for r in rows) or len({len(r) for r in rows}) > 1:
            continue
        cell = lambda c: re.escape(c.rstrip(".")).replace("\\ ", r"\s+") + r"\.?" if c else ""  # a closing stop may go
        row = lambda r: r"\|?[ \t]*" + r"[ \t]*\|[ \t]*".join(map(cell, r)) + r"[ \t]*\|?"
        rule = r"(?:[ \t]*\|?[ \t]*:?-{3,}:?(?:[ \t]*\|[ \t]*:?-{3,}:?)*[ \t]*\|?)?"
        pat = re.compile(row(rows[0]) + rule + "".join(r"[ \t]*" + row(r) for r in rows[1:]))
        m = pat.search(text)
        if not m:
            continue
        table = "\n".join("| " + " | ".join(r) + " |" for r in rows[:1]) + "\n" + "|" + "---|" * len(rows[0]) + "\n" + \
            "\n".join("| " + " | ".join(r) + " |" for r in rows[1:])
        before, after = text[: m.start()].rstrip(" \t"), text[m.end():].lstrip(" \t")
        text = (before + ("\n\n" if before and not before.endswith("\n\n") else "") + table
                + ("\n\n" if after and not after.startswith("\n") else "") + after)
    return text


def _fix_breaks(text: str) -> str:
    """Put back line breaks the model left out: escaped "\\n" as text, a heading run on after a sentence, or a heading
    run together with the text under it (a heading line that cites something is two lines), or the next paragraph run
    on straight after a citation or a sentence (or a bullet run on after a citation or a heading), or a table's rows
    run onto one line."""
    fixed = text.replace("\\n", "\n")
    fixed = HEADING_IN_TEXT.sub(r"\n\n\1", fixed)
    fixed = HEADING_RUN_ON.sub(r"\1\n\2", fixed)
    fixed = CITE_RUN_ON.sub(r"\1\n\n", fixed)
    fixed = BULLET_RUN_ON.sub(r"\1\n", fixed)
    fixed = TABLE_RUN_ON.sub(_unflatten_table, fixed)
    fixed = checks.SENTENCE_RUN_ON.sub("\n\n", fixed)
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


def _example_runs(idx: list[int], item_of: dict[int, str]) -> list[list[int]]:
    """The paragraphs as labelled examples, in order: a run per example, with the unlabelled paragraphs after it."""
    runs: list[list[int]] = []
    for i in idx:
        if not runs or (item_of.get(i) and item_of.get(i) != item_of.get(runs[-1][0])):
            runs.append([i])
        else:
            runs[-1].append(i)
    return runs


def _pack_items(idx: list[int], item_of: dict[int, str], words: list[int], limit: int, extra_words: int = 0) -> list:
    """A group of labelled examples over the size limit, split between examples only: each example (with the
    unlabelled paragraphs after it) stays whole, and examples go in order onto pages up to the limit. Returns
    (part number, paragraphs) per page; a group under the limit is one page (part 0)."""
    runs = _example_runs(idx, item_of)
    if sum(words[i] for i in idx) + extra_words <= limit or len(runs) < 2:
        return [(0, idx)]
    pages, size = [[]], 0
    for run in runs:
        w = sum(words[i] for i in run)
        if pages[-1] and size + w > limit:
            pages.append([])
            size = 0
        pages[-1] += run
        size += w
    return [(n, page) for n, page in enumerate(pages, start=1)]


def _join_small(parts: list, words: list[int], minimum: int, limit: int | None = None, floor: int = 0) -> tuple[list, list]:
    """Groups under the minimum joined to the group before them under the same parent heading (or the one after, if
    first), until none is under it or none can be joined. A join that would go over the limit goes to the other side
    instead; if both would, the small group stays as it is. A group named by no more than floor names (a whole paper,
    where each path starts with its paper) joins nothing. Returns (groups, [(joined, into)])."""
    parts = [(list(n), list(i), [n[-1]] if n else []) for n, i in parts]  # (path, paragraphs, headings it holds)
    joined, alone = [], set()  # alone: small groups that cannot join either side without going over
    size = lambda idx: sum(words[i] for i in idx)
    while True:
        for k, (names, idx, heads) in enumerate(parts):
            if size(idx) >= minimum or tuple(heads) in alone or len(names) <= floor:
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


def _drop_title(paths: list[list[str]]) -> list[list[str]]:
    """A heading on top of every paragraph's path is the document's title heading, not a heading group: left off."""
    tops = {p[0] for p in paths if p}
    if len(tops) != 1 or sum(1 for p in paths if p) < 2:
        return paths
    title = tops.pop()
    return [p[1:] if p and p[0] == title else p for p in paths]


def _footnote_of(paras: list[str], form: str | None) -> dict[int, int]:
    """Each footnote (labelled in the schema's form for it, e.g. "ED:<clause>") -> the paragraph it belongs to."""
    if not form or "<clause>" not in form:
        return {}
    rx = re.compile(re.escape(form).replace(re.escape("<clause>"), "(.+)") + "$")
    at: dict[str, int] = {}
    for k, p in enumerate(paras):
        at.setdefault(_ref(p), k)
    return {i: at[m.group(1)] for i, p in enumerate(paras) if (m := rx.match(_ref(p))) and m.group(1) in at}


def _sub_names(title: str, split: bool = True) -> list[str]:
    """A subtopic page's group names, read back from its title ("<section>: <name> – <name>"); split: each heading of a
    joined group on its own."""
    names = title.split(": ", 1)[-1].split(" \u2013 ")
    return [h for n in names for h in n.split(HEADS_SEP)] if split else names


def _sub_slug(sec_slug: str, names: list[str], slug_words: int | None) -> str:
    """A subtopic slug: the heading's own number where it has one (6.3 -> <section>-6-3), else its first words."""
    head = names[-1].split(HEADS_SEP)[0] if names else ""  # a joined group: its first heading
    if m := NUMBERED.match(head):
        return slugify(f"{sec_slug}-{m.group(1).replace('.', '-')}")
    words = head.split()[:slug_words] if slug_words else head.split()
    # no longer than slugify allows, like every slug (links to it are read that way): whole words off the end
    while len(words) > 1 and len(slugify(f"{sec_slug}-{' '.join(words)}")) < len(f"{sec_slug}-" + slugify(' '.join(words))):
        words = words[:-1]
    return slugify(f"{sec_slug}-{' '.join(words)}")


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


async def _source_paths(wiki_id) -> dict[str, dict]:
    """Each source's paragraph labels with their heading path (title heading left off) and, for a labelled example,
    the example it belongs to."""
    async with get_pool().connection() as conn:
        rows = await (await conn.execute("select slug, title, text, meta from wiki.sources where wiki_id = %s", (wiki_id,))).fetchall()
    out = {}
    for r in rows:
        sp = [b.strip() for b in re.split(r"\n\s*\n", r["text"] or "") if b.strip()]
        hp = (r["meta"] or {}).get("heading_paths") or []
        paths = _drop_title(_anchored_paths(sp, hp if len(hp) == len(sp) else [[] for _ in sp], (r["meta"] or {}).get("para_kinds")))
        out[r["slug"]] = {"path": {}, "para": {}, "title": ((r["meta"] or {}).get("document") or {}).get("part") or r["title"]}
        for p, pa in zip(sp, paths):
            if _ref(p):
                out[r["slug"]]["path"].setdefault(_ref(p), pa)
                out[r["slug"]]["para"].setdefault(_ref(p), p)
    return out


async def split_written(wiki_id, chk, sections: list[dict], pages: dict[str, dict], targets: set[str]) -> tuple[list, list]:
    """The schema's rule after writing, wherever a page is written: a section or subtopic page whose write-up is over
    the page size limit by more than the schema's margin is split again. Its blocks move word for word, grouped by
    the source heading of the paragraph each cites (at the highest level where they differ, small groups joined as
    usual); a page of labelled examples splits between examples only. A section page becomes the index of its
    subtopic pages; a subtopic page keeps its slug for its first piece. pages: slug -> the page as it now stands
    (slug, type, title, summary, content_md, tags, version). Returns (ops, what was split)."""
    limit = chk.page_size_limit if chk else None
    if not limit:
        return [], []
    cap = limit * (1 + chk.resplit_margin)
    section_slug = {sl: sec for sl, p in pages.items() if p["type"] == "topic" and (sec := _section_for(sections, p["title"], sl))}
    subs_of = lambda sec_slug: [x for x in pages if x.startswith(sec_slug + "-") and pages[x]["type"] == "subtopic"]
    todo = [sl for sl in targets if sl in pages and pages[sl]["type"] in ("topic", "subtopic")
            and not (sl in section_slug and subs_of(sl)) and not checks.holds_no_claims(chk, sl)
            and len(_split_also(pages[sl]["content_md"])[0].split()) > cap]
    if not todo:
        return [], []
    src = await _source_paths(wiki_id)
    apart = chk.papers_apart  # each block's path starts with its paper: groups form within one paper only
    ops: dict[str, Op] = {}
    report = []
    for sl in todo:
        p = pages[sl]
        home = sl if sl in section_slug else max((x for x in section_slug if sl.startswith(x + "-")), key=len, default=None)
        if not home:
            continue
        sec = section_slug[home]
        body, lines = _split_also(p["content_md"])
        body = "\n".join(x for x in body.split("\n") if not x.startswith("Not yet covered"))
        blocks = _blocks(body)
        paths, items, last = [], [], []
        for b in blocks:  # the heading path of the paragraph the block cites; a block citing none goes with the one before
            m = next((m for m in store.LINK_RE.finditer(b) if m.group(1) in src and m.group(2)), None)
            lab = re.sub(r"(?:\s*\([^)]*\))+$", "", m.group(2).strip()) if m else ""
            path = src[m.group(1)]["path"].get(lab) if m else None
            if apart and path is not None:
                path = [m.group(1)] + path
            last = path if path is not None else last
            paths.append(last)
            items.append(checks.example_item(last, src[m.group(1)]["para"].get(lab, ""), chk) if m else None)
        words = [len(b.split()) for b in blocks]
        idx = list(range(len(blocks)))
        base = _sub_names(p["title"], split=False) if p["type"] == "subtopic" else []
        if any(items):  # labelled examples: whole examples onto pages up to the limit
            item_of = {k: x for k, x in enumerate(items) if x}
            packed = _pack_items(idx, item_of, words, limit)
            group = (base[-1] if base else sec["name"]).rsplit(" (", 1)[0]
            taken = [int(m.group(1)) for x in subs_of(home) if (m := re.search(rf"{re.escape(group)} \((\d+)\)", pages[x]["title"]))]
            # this page keeps its own name; a new piece takes the next number of its group
            parts = [([base[-1]] if base and k == 0 else [f"{group} ({max(taken, default=0) + k + (0 if base else 1)})"], part)
                     for k, (n, part) in enumerate(packed)]
        else:
            parts = _size_split(idx, paths, words, limit)
            if len(parts) > 1 and chk.subtopic_minimum:
                parts = _join_small(parts, words, chk.subtopic_minimum, limit, floor=1 if apart else 0)[0]
            if apart:  # a paper is a group's first name only where the page held more than one: its headings name it,
                # or, for the whole paper, its title
                parts = [([n for n in names if n not in src] or [src[names[0]]["title"]] if names else names, part)
                         for names, part in parts]
        if len(parts) < 2:
            report.append({"page": sl, "words": sum(words), "split": False, "why": "no heading or example to split by"})
            continue
        pieces = []
        for k, (names, part) in enumerate(parts):
            if base:  # a subtopic page's pieces: its own groups, then the heading (or numbered examples) each holds
                names = base[:-1] + names if any(items) else (base if k == 0 else base + names[-1:])
            if p["type"] == "subtopic" and k == 0:
                psl = sl
            else:
                psl = _sub_slug(home, names, chk.slug_words)
                if psl in pages or psl in ops or psl in (x[0] for x in pieces):
                    psl = _sub_slug(sl, names[-1:], chk.slug_words)
            text = "\n\n".join(blocks[i] for i in part)
            if k == 0 and lines:
                text = _with_also(text, lines)
            title = f"{sec['name']}: {' – '.join(names)}"
            cur = pages.get(psl)
            ops[psl] = Op(op="update" if cur else "create", slug=psl, type="subtopic", title=title, summary=title,
                          content_md=text, tags=(cur or p).get("tags") or [], base_version=cur.get("version") if cur else None,
                          change_note=f"Split from {sl}: over the page size limit once written")
            pieces.append((psl, title, text))
        report.append({"page": sl, "words": sum(words), "split": True, "into": [x[0] for x in pieces]})
        log.info("page %s is %s words once written, over %s: split into %s", sl, sum(words), int(cap), ", ".join(x[0] for x in pieces))
        # the section's index: every subtopic page, those just made included
        now = {x: {"slug": x, "title": ops[x].title if x in ops else pages[x]["title"],
                   "content_md": ops[x].content_md if x in ops else pages[x]["content_md"]}
               for x in dict.fromkeys(subs_of(home) + [x for x in ops if x.startswith(home + "-")])}
        hp = pages[home]
        order = lambda x: hp["content_md"].find(f"[[{x}") % (len(hp["content_md"]) + 1) if f"[[{x}" in hp["content_md"] else len(hp["content_md"]) + 1
        content, summary = _index_md(sec["name"], [now[x] for x in sorted(now, key=order)], {k: v["title"] for k, v in src.items()})
        ops[home] = Op(op="update", slug=home, type="topic", title=hp["title"], summary=summary, content_md=content,
                       tags=hp.get("tags") or [], base_version=hp.get("version"), change_note=f"Index of {len(now)} subtopic pages")
    return list(ops.values()), report


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
    An earlier "also recorded" line moves to the sub-page of the section it points to. Returns, per section, what
    moved where."""
    out = {}
    for sec_slug, subs in index_of.items():
        cur = existing.get(sec_slug)
        if not cur or any(x.startswith(sec_slug + "-") and existing[x]["type"] == "subtopic" for x in existing):
            continue  # nothing held yet, or already an index
        held, old_lines = _split_also(cur["content_md"])
        body = "\n".join(l for l in held.split("\n") if not l.startswith("Not yet covered"))
        blocks = [b for b in _blocks(body) if store.LINK_RE.search(b) and re.search(r"\[\[source-", b)]
        if not blocks and not old_lines:
            continue
        lines_to: dict[str, list[str]] = {}
        for ln in old_lines:  # to the subtopic page of the section the line points to (its main page's section)
            page = next((m.group(1) for m in store.LINK_RE.finditer(ln) if not m.group(1).startswith("source-")), "")
            home = max((x for x in sec_of if page == x or page.startswith(x + "-")), key=len, default=None)
            sl = _sub_slug(sec_slug, [sec_of[home]["name"]], chk.slug_words if chk else None) if home else subs[0]
            if sl not in sub_of:
                sub_of[sl] = {"sec": sec_of[sec_slug], "names": [sec_of[home]["name"]], "paras": []}
            lines_to.setdefault(sl, []).append(ln)
        for sl, lns in lines_to.items():  # earlier lines first; a new line for the same paragraph replaces its old one
            if sl in written:
                page_body, new = _split_also(written[sl].content_md)
                renewed = {_also_key(x) for x in new}
                written[sl].content_md = _with_also(page_body, [x for x in lns if _also_key(x) not in renewed] + new)
            else:
                sec = sec_of[sec_slug]
                written[sl] = Op(op="update" if sl in existing else "create", slug=sl, type="subtopic",
                                 title=f"{sec['name']}: {sub_of[sl]['names'][-1]}", summary=f"{sec['name']}: {sub_of[sl]['names'][-1]}",
                                 content_md=_with_also("", lns), tags=[], base_version=existing[sl]["version"] if sl in existing else None,
                                 change_note="Lines moved from the section page when it was split")
                ops.append(written[sl])
            if sl not in subs:
                subs.append(sl)
        if not blocks:
            out[sec_slug] = {"blocks": 0, "lines": {sl: len(x) for sl, x in lines_to.items()}, "to": {}, "new_pages": [], "cites": set()}
            continue
        cited = {m.group(1) for b in blocks for m in store.LINK_RE.finditer(b) if m.group(1).startswith("source-")}
        async with get_pool().connection() as conn:
            rows = await (await conn.execute("select slug, title, text, meta from wiki.sources where wiki_id = %s and slug = any(%s)",
                                             (wiki_id, list(cited)))).fetchall()
        src = {}
        for r in rows:
            sp = [b.strip() for b in re.split(r"\n\s*\n", r["text"] or "") if b.strip()]
            hp = (r["meta"] or {}).get("heading_paths") or []
            paths = _drop_title(_anchored_paths(sp, hp if len(hp) == len(sp) else [[] for _ in sp], (r["meta"] or {}).get("para_kinds")))
            path_of, last = {}, []
            for p, pa in zip(sp, paths):  # a paragraph with no heading of its own is under the one before it
                last = pa or last
                if _ref(p):
                    path_of[_ref(p)] = last
            src[r["slug"]] = {"title": r["title"], "path": path_of}
        to: dict[str, list[str]] = {}
        # papers kept apart (the schema's Checks list): a block goes only to a sub-page of its own paper
        apart = bool(chk and chk.papers_apart)
        made: dict[str, str] = {}  # a sub-page made here for one paper's blocks -> that paper
        papers = lambda x: {made[x]} if x in made else {c.split("|", 1)[0] for c in checks.cites(written[x].content_md)} \
            if x in written else set()
        for b in blocks:
            m = next((m for m in store.LINK_RE.finditer(b) if m.group(1) in src and m.group(2)), None)
            paper = m.group(1) if m else None
            path = src[m.group(1)]["path"].get(re.sub(r"(?:\s*\([^)]*\))+$", "", m.group(2).strip()), []) if m else []
            heads_of = lambda x: [h for n in sub_of[x]["names"] for h in n.split(HEADS_SEP)]
            match = [sl for sl in subs if sub_of.get(sl) and any(h in path for h in heads_of(sl))
                     and (not apart or paper in papers(sl))]
            own = [sl for sl in subs if not apart or paper in papers(sl)]
            if match:  # the sub-page whose heading is deepest on the block's path
                sl = max(match, key=lambda x: max(path.index(h) for h in heads_of(x) if h in path))
            elif path or (paper and not own):  # a sub-page named after the cited paragraph's nearest heading (or its paper's title)
                names = path[-1:] or [src[paper]["title"]]
                sl = _sub_slug(sec_slug, names, chk.slug_words if chk else None)
                if apart and paper and sl in sub_of and paper not in papers(sl):  # another paper's page of that name
                    names = [src[paper]["title"], *path[-1:]]
                    sl = _sub_slug(sec_slug, names, chk.slug_words if chk else None)
                if sl not in sub_of:
                    sub_of[sl] = {"sec": sec_of[sec_slug], "names": names, "paras": []}
                if apart and paper:
                    made.setdefault(sl, paper)
            else:  # the source has no headings: the section's first sub-page (of its paper)
                sl = (own or subs)[0]
            to.setdefault(sl, []).append(b)
        new_pages = []
        for sl, bs in to.items():
            text = "\n\n".join(bs)
            if sl in written:  # added word for word, before the page's "Not yet covered" line
                written[sl].content_md = _add_blocks(written[sl].content_md, text)
            else:
                sec = sec_of[sec_slug]
                named = " – ".join(sub_of[sl]["names"])
                o = Op(op="update" if sl in existing else "create", slug=sl, type="subtopic",
                       title=f"{sec['name']}: {named}", summary=f"{sec['name']}: {named}",
                       content_md=text, tags=[], base_version=existing[sl]["version"] if sl in existing else None,
                       change_note="Moved from the section page when it was split")
                ops.append(o)
                written[sl] = o
                new_pages.append(sl)
            if sl not in subs:
                subs.append(sl)
        out[sec_slug] = {"blocks": len(blocks), "to": {sl: len(bs) for sl, bs in to.items()}, "new_pages": new_pages,
                         "lines": {sl: len(x) for sl, x in lines_to.items()}, "cites": checks.cites("\n\n".join(blocks))}
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
    """Join a page's parts, dropping any block that repeats one already kept: from an earlier part, or from the same
    reply (a long reply can write a run of its blocks twice). A bare heading may recur ("Fact pattern" under each
    example); a block that cites a source may not."""
    seen: set[str] = set()
    out = []
    for t in map(_fix_breaks, texts):
        for b in (b for b in re.split(r"\n\s*\n", t.strip()) if b.strip()):
            k = _norm(b)
            if k and k in seen and (re.search(r"\[\[source-", b) or not re.fullmatch(r"#{1,6} [^\n]*", b.strip())):
                continue
            seen.add(k)
            out.append(b)
    return "\n\n".join(out)


def _under_headings(md: str, add: str) -> str:
    """Text added to a page: a section under a heading the page already has goes at the end of that heading's part
    of the page, its own sub-headings placed the same way inside it, not at the end of the page (where the heading
    would appear a second time). A heading added with no text of its own adds nothing; the rest goes at the end."""
    same = lambda h: " ".join(re.sub(r"[^\w]+", " ", h.casefold()).split())
    heads = lambda t: list(re.finditer(r"(?m)^(#{1,4}) ([^\n]+)$", t))
    add = add.strip()
    hs = heads(add)
    if not hs:
        return _join_parts([md, add]) if add else md
    top = min(len(h.group(1)) for h in hs)
    if pre := add[:hs[0].start()].strip():
        md = _join_parts([md, pre])
    starts = [h for h in hs if len(h.group(1)) == top]
    for k, h in enumerate(starts):
        sec = add[h.start(): starts[k + 1].start() if k + 1 < len(starts) else len(add)].strip()
        body = sec[h.end() - h.start():].strip()
        at = next((x for x in heads(md) if same(x.group(2)) == same(h.group(2))), None)
        if not at:
            md = _join_parts([md, sec])
            continue
        if not body:
            continue  # the heading alone: the page has it already
        nxt = re.compile(rf"(?m)^#{{1,{len(at.group(1))}}} ").search(md, at.end())
        end = nxt.start() if nxt else len(md)
        inside = md[at.end():end].strip()
        if heads(body):
            merged = _under_headings(inside, body)
        elif sub := heads(inside):  # text of the heading itself: before its first sub-heading
            merged = _join_parts([inside[:sub[0].start()].strip(), body]) + "\n\n" + inside[sub[0].start():]
        else:
            merged = _join_parts([inside, body])
        md = md[:at.end()] + "\n" + merged + ("\n\n" + md[end:].lstrip() if md[end:].strip() else "")
    return md


def _cited_only(text: str, refs: set[str]) -> str:
    """The blocks (or bullet lines) of a reply that cite one of refs, so an extra pass cannot rewrite the page."""
    blocks = [b for b in re.split(r"\n\s*\n|\n(?=\s*[-*] )", text.strip()) if b.strip()]
    # a bare heading has no citation; a heading run together with its text ("...InstrumentsAn entity shall ...") does
    bare = lambda b: re.match(r"^#{2,4} ", b) and not store.LINK_RE.search(b)
    keep = [b for b in blocks if bare(b) or any(
        _covers(m.group(2), r) for m in store.LINK_RE.finditer(b) if m.group(2) for r in refs)]
    while keep and bare(keep[-1]):
        keep.pop()
    return "\n\n".join(keep)


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
    foot = _footnote_of(paras, checks.footnote_form(chk))  # a footnote goes wherever its paragraph goes
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
            # the whole passage: a fact late in a long passage or table weighs in its routing too
            lines = "\n".join(f"{i} | {heads[i] or '-'} | {' '.join(paras[i].split())}" for i in batch)
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
        owner.update({i: owner[j] for i, j in foot.items() if j in owner})
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
    line_to: dict[int, dict[int, int]] = {}  # split section -> its also-recorded lines -> the section each points to
    hp0 = ex.meta.get("heading_paths") or []
    paths0 = _drop_title(_anchored_paths(paras, hp0 if len(hp0) == len(paras) else [[] for _ in paras], ex.meta.get("para_kinds")))
    item_early = {i: x for i in range(len(paras)) if (x := checks.example_item(paths0[i], paras[i], chk))}
    for num, grouped_by in (chk.split.items() if chk and owner else []):
        parent = next((x for x in sections if x["num"] == num), None)
        mine = [i for i, n in sorted(owner.items()) if n == num]
        if parent and also.get(num):  # a line recorded here points to its paragraph's own section: grouped by it
            line_to[num] = {i: owner[i] for i in also[num] if owner.get(i) not in (None, num)}
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
        for run in _example_runs(mine, item_early):  # a labelled example is never split: where most of it went
            votes = [got[i] for i in run if i in got]
            if votes:
                top = max(set(votes), key=lambda g: (votes.count(g), -votes.index(g)))
                got.update({i: top for i in run})
        group_of.update(got)
        log.info("ingest: section %s split into %s groups (%s of %s paragraphs grouped)", num, len(set(got.values())),
                 len(got), len(mine))

    group_of.update({i: group_of[j] for i, j in foot.items() if j in group_of})

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
    apart = bool(chk and chk.papers_apart)
    sub_fixed: dict[int, str] = {}  # paragraph -> an existing subtopic page of its (already split) section
    item_of: dict[int, str] = {}  # paragraph -> the labelled example it belongs to (the schema's example labels)
    if limit and owner:
        hp = ex.meta.get("heading_paths") or []
        paths = _drop_title(_anchored_paths(paras, hp if len(hp) == len(paras) else [[] for _ in paras], ex.meta.get("para_kinds")))
        words = [len(p.split()) for p in paras]
        split_basis.update(paths=paths, words=words)
        item_of.update({i: x for i in range(len(paras)) if (x := checks.example_item(paths[i], paras[i], chk))})
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
                if key and any(item_of.get(i) for i in idx):  # labelled examples: split between examples only
                    packed = _pack_items(idx, item_of, words, limit, 0)
                    if len(packed) > 1:
                        for n, part in packed:
                            for i in part:
                                group_name[i] = [*key[:-1], f"{key[-1]} ({n})"]
                        log.info("ingest: section %s (%s) is over %s words: split between examples into %s pages", num,
                                 " / ".join(key), limit, len(packed))
                    continue
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
        # a section an earlier upload split stays an index: each new paragraph goes to a subtopic page: the one holding
        # the paragraph its heading or text refers to, else the one whose heading is on its path, else one for its
        # nearest heading (small ones joined like any other)
        for num, sl in slug_of.items():
            olds = {x: _sub_names(existing[x]["title"]) for x in existing
                    if x.startswith(sl + "-") and existing[x]["type"] == "subtopic"}
            todo = [i for i, n in sorted(owner.items()) if n == num and not group_name.get(i) and i not in foot]
            if not olds or not todo or num in additive:
                continue
            holds = {x: {c.split("|", 1)[1] for c in checks.cites(existing[x]["content_md"])} for x in olds}
            # papers kept apart (the schema's Checks list): only a subtopic page that holds this paper takes its paragraphs
            mine_too = {x for x in olds if not apart or any(c.startswith(source["slug"] + "|") for c in checks.cites(existing[x]["content_md"]))}
            last: list[str] = []
            free = []
            for i in todo:
                path = last = paths[i] or last  # a paragraph with no heading of its own is under the one before it
                refs = [r.rstrip(".") for r in REFERS.findall(" ".join(path) + " " + paras[i])]
                by_ref = collections.Counter(x for r in refs for x in mine_too if r in holds[x])
                match = [x for x, heads in olds.items() if x in mine_too and any(h in path for h in heads)]
                if by_ref:
                    sub_fixed[i] = by_ref.most_common(1)[0][0]
                elif match:
                    sub_fixed[i] = max(match, key=lambda x: max(path.index(h) for h in olds[x] if h in path))
                else:
                    free.append((i, path))
            near: dict[tuple, list[int]] = {}
            for i, path in free:
                near.setdefault(tuple(path), []).append(i)
            parts = [(list(path), idx) for path, idx in near.items()]
            if len(parts) > 1 and chk.subtopic_minimum:
                parts, joined = _join_small(parts, words, chk.subtopic_minimum, limit)
                joins.extend({"section": num, "joined": a, "into": b} for a, b in joined)
            for names, part in parts:
                for i in part:
                    if names:
                        group_name[i] = names
                    elif mine_too:  # no heading anywhere: the section's first subtopic page (that holds this paper)
                        sub_fixed[i] = next(x for x in olds if x in mine_too)
                    else:  # no heading anywhere and no page of this paper yet: a page named after the paper
                        group_name[i] = [ex.title]
            log.info("ingest: section %s already split: %s new paragraphs to its subtopic pages, %s to new ones", num,
                     len(todo) - len(free), len(free))
    for i, j in foot.items():  # a footnote goes to the subtopic page of the paragraph it belongs to
        group_name.pop(i, None)
        sub_fixed.pop(i, None)
        if j in sub_fixed:
            sub_fixed[i] = sub_fixed[j]
        elif group_name.get(j):
            group_name[i] = group_name[j]
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
            if apart and sl in existing and not any(c.startswith(source["slug"] + "|") for c in checks.cites(existing[sl]["content_md"])):
                sl = _sub_slug(slug_of[owner[i]], [ex.title, *names], chk.slug_words if chk else None)  # another paper's page
            sub_of.setdefault(sl, {"sec": by_num[owner[i]], "names": names, "paras": []})["paras"].append(i)
    for num, lines in line_to.items():  # a split section's lines: on the subtopic page of the section each points to
        if num not in slug_of:
            continue
        for i, g in sorted(lines.items()):
            sl = _sub_slug(slug_of[num], [by_num[g]["name"]], chk.slug_words if chk else None)
            sub = sub_of.setdefault(sl, {"sec": by_num[num], "names": _sub_names(existing[sl]["title"], split=False)
                                         if sl in existing else [by_num[g]["name"]], "paras": []})
            sub.setdefault("also", []).append(i)
    for sl, sub in sub_of.items():  # the title names every heading the page holds: its labelled examples, and the
        # nearest heading of a paragraph added to it by reference
        named = " · ".join(sub["names"])
        sub["heads"] = [h for h in dict.fromkeys([item_of[i] for i in sub["paras"] if i in item_of] + [
            split_basis["paths"][i][-1] for i in sub["paras"] if i in sub_fixed and split_basis.get("paths")
            and split_basis["paths"][i]]) if h and h not in named]
    title_of = lambda sub: f"{sub['sec']['name']}: {' – '.join(sub['names'])}" + "".join(f" · {h}" for h in sub["heads"])
    index_of: dict[str, list[str]] = {}  # split section page -> its subtopic pages written now
    for sl, sub in sub_of.items():
        index_of.setdefault(slug_of[sub["sec"]["num"]], []).append(sl)
        items.append({"action": "update" if sl in existing else "create", "slug": sl, "type": "subtopic",
                      "title": title_of(sub),
                      "focus": f"Section {sub['sec']['num']:02d}: {sub['sec']['name']}, subtopic {' – '.join(sub['names'])}"})
    for sec_slug, subs in index_of.items():
        sec = sec_of[sec_slug]
        splits.append({"section": f"{sec['num']:02d} {sec['name']}", "page": sec_slug,
                       "by": "size" if not (chk and sec["num"] in chk.split) else chk.split[sec["num"]],
                       "pages": [{"slug": x, "paragraphs": len(sub_of[x]["paras"]), "lines": len(sub_of[x].get("also", [])),
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
        cur_body, old_also = _split_also(cur["content_md"]) if cur and (sec or sub) else (cur["content_md"] if cur else None, [])
        background, auto_gaps, page_material = [], False, material
        # papers kept apart (the schema's Checks list): a page that holds other papers keeps their text as it is, and
        # this paper's text, written on its own under its own headings, goes after it
        others = cur_body if (chk and chk.papers_apart and source_slug and (sec or sub) and cur_body
                              and {c.split("|", 1)[0] for c in checks.cites(cur_body)} - {source_slug}) else None
        # paragraphs also recorded here as one line each (on the subtopic page of a split section, the lines it groups)
        extra = sub.get("also", []) if sub else also.get(sec["num"], []) if sec else []
        if sec or sub:  # a section (or subtopic) page writes up only its own paragraphs; a few related ones are context
            mine = sub["paras"] if sub else own.get(sec["num"], [])
            given = [paras[i] for i in mine]
            if not given and not extra:  # nothing from this source: leave an existing page alone, otherwise say the section is empty
                if cur:
                    return None
                return Op(op="create", slug=slug, title=title, type=ptype, summary="Empty: no source content yet", tags=[],
                          content_md=chk.empty_text if chk and chk.empty_text else
                          f"This section is empty: no paragraph of [[{source_slug}]] belongs to it.",
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
            # the current page goes to the first part only: it is integrated once, and a later part (given the parts written
            # so far) adds only what its own paragraphs say
            prompt = prompts.with_schema(schema, prompts.write_page_prompt(
                slug=slug, title=title, ptype=ptype, focus=focus, existing_md=cur_body if n == 1 and not others else None,
                material=page_material, linkable=linkable, source_slug=source_slug,
                source_paragraphs="\n\n".join(group) or None, background_paragraphs="\n\n".join(background) or None,
                auto_gaps=auto_gaps, part=part,
                earlier_parts="\n\n".join(o["content_md"] for o in outs), others_md=others if n == 1 else None,
            ))
            try:
                out = await llm.generate_json(system, prompt, prompts.PAGE_SCHEMA)
                if not out["content_md"].strip():  # an empty reply is retried once
                    log.warning("ingest: page %s%s came back empty; retrying once", slug, f" part {n}/{len(groups)}" if part else "")
                    out = await llm.generate_json(system, prompt, prompts.PAGE_SCHEMA)
                    empty_retries.append({"page": slug, "part": n if part else None, "empty_again": not out["content_md"].strip()})
                    if not out["content_md"].strip():
                        log.warning("ingest: page %s came back empty again", slug)
                if n > 1:  # a later part keeps only what cites its own paragraphs: it cannot restate the parts before it
                    out = {**out, "content_md": _cited_only(_fix_breaks(out["content_md"]), {_ref(p) for p in group})}
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
        if sec or sub:
            content = _split_also(content)[0]  # the section is rebuilt below from the kept and the new lines
            if not given and cur:  # only lines to also record: the page itself stays as it is
                content = cur_body

        cited_only = _cited_only

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
                        content = _under_headings(content, kept)  # under its heading if the page has it
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
                                               if chk else []) + checks.repeat_failures(x) + cite_failures(x)
                + ([] if checks.absence_allowed_on(chk, ptype, title) else checks.absence_failures(x, chk, "\n\n".join(given))),
                sources_text="\n\n".join(given), parse=lambda r: _fix_breaks(r).strip(),
                ok=lambda old, new: not ({_ref(p) for p in _uncited(new, given)} - {_ref(p) for p in _uncited(old, given)}))
        if others and given:  # the other papers' text first, as it was; this paper's after it
            content = _join_parts([others, content])

        if ptype == "source" and owner and sec_of and chk and chk.source_parts:
            informed = {sl for sl, x in sec_of.items() if own.get(x["num"]) or also.get(x["num"])}
            args = dict(fields=fields, authority=authority, informed=informed, sections=set(sec_of),
                        source_slug=source["slug"], c=chk, labels=src_labels)
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
            fold = lambda lines: [
                ln if store.LINK_RE.search(ln.replace("[[source-", "")) is None or re.search(r"\[\[source-[^\]|]+\|", ln)
                else re.sub(r"\[\[((?!source-)[^\]|#]+)\|([^\]]+)\]\]", lambda m: f"see [[{m.group(1)}]] [[{source_slug}|{m.group(2)}]]", ln)
                for ln in lines]
            lines = fold(lines)
            # check: every paragraph marked "also record here" has a line citing it. The list is long, so it is never
            # rewritten as a whole: only the missing lines are asked for, a few at a time, and added with their citation
            if gaps := [i for i in extra if _uncited("\n".join(lines), [paras[i]])]:
                rec = {"page": slug, "kind": "also recorded", "found": len(gaps)}
                for k in range(0, len(gaps), 5):
                    group = [item(i) for i in gaps[k:k + 5]]
                    refs = {_ref(p) for p in group}
                    try:
                        out = await llm.generate_json(system, prompts.with_schema(schema, prompts.also_record_prompt(
                            slug=slug, title=title, items="\n\n".join(group), linkable=linkable, source_slug=source_slug)),
                            prompts.FILL_SCHEMA)
                        lines += [ln for ln in also_lines(out["content_md"], refs) if not _uncited(ln, [paras[i] for i in gaps])]
                    except Exception as e:
                        log.warning("ingest: page %s also-record backstop failed: %s", slug, e)
                lines = fold(lines)
                rec["still"] = sum(1 for i in extra if _uncited("\n".join(lines), [paras[i]]))
                check_fixes.append(rec)
            if still := [_ref(paras[i]) for i in extra if _uncited("\n".join(lines), [paras[i]])]:
                missed.append({"page": slug, "paragraphs": list(dict.fromkeys(still)), "reason": "not recorded after two tries and the backstop"})

        if (sec or sub) and (old_also or extra):  # earlier uploads' lines first; a line for the same paragraph is replaced
            new = lines if extra else []
            replaced = {_also_key(ln) for ln in new}
            content = _with_also(content, [ln for ln in old_also if _also_key(ln) not in replaced] + new)
        gap_note = not (chk and chk.absence)  # absence phrases in the schema: a page notes no gaps (the report does)
        if gap_note and auto_gaps and given:
            content += _not_covered(content, given, "paragraphs of this section") or "\n\nNot yet covered: none"
        elif gap_note and len(groups) > 1:
            content += _not_covered(content, given)
        content = _restore_tables(content, paras)  # a table of this source the reply ran onto one line
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

    first, facts = [], ""
    if chk and chk.absence:  # the pages that may say a fact is absent are written knowing what the source page records
        first = [o for o in [await write_safe(source["slug"], ex.title, "source", source_focus, None)] if o]
        facts = ("\nWhat the source page records for this paper (its document facts, from the paper or recorded at "
                 "upload); each fact given here is known, so it is never written as absent:\n<source_page>\n"
                 + (first[0].content_md if first else "") + "\n</source_page>"
                 + ("\nRecorded for this source: " + "; ".join(f"{k}: {v}" for k, v in fields.items()) if fields else ""))
    told = lambda i: facts if facts and checks.absence_allowed_on(chk, i["type"], i["title"]) else ""
    ops = first + [o for o in await llm.gather_limited(
        ([] if chk and chk.absence else [write_safe(source["slug"], ex.title, "source", source_focus, None)])
        + [write_safe(i["slug"], i["title"], i["type"], i["focus"] + told(i), source["slug"]) for i in items if i["slug"] not in index_of]
    ) if o]
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
                rec["moved"] = {"blocks": m["blocks"], "to": m["to"], "lines": m.get("lines", {}), "earlier_citations": len(m["cites"]),
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
            clause=lambda c: fixpass.is_clause(c, cite_ctx), may_grow=True,
            parse=lambda r: _fix_breaks(r).strip(), kind="no claims", record=check_fixes,
            ok=lambda old, new: not checks.cites(new) - checks.cites(old))  # a fix adds no claim
    if not ops:
        raise RuntimeError(f"Page writing failed for every page: {failed_pages[:3]}")
    if failed_pages:
        await ctx.progress(failed_pages=failed_pages)
    if missed:
        await ctx.progress(missed_paragraphs=missed)
    # Links to pages that will not exist (never planned, or failed) become plain text; the source stays linkable
    # the schema's rule after writing: a page over the size limit by more than its margin is split again
    now = {sl: dict(p) for sl, p in existing.items()} | {o.slug: {"slug": o.slug, "type": o.type, "title": o.title,
           "summary": o.summary, "content_md": o.content_md, "tags": o.tags,
           "version": existing.get(o.slug, {}).get("version")} for o in ops}
    more, resplit = await split_written(wiki_id, chk, sections, now, {o.slug for o in ops if o.type in ("topic", "subtopic")})
    for x in more:  # an op for the same page is replaced by the split's
        ops = [o for o in ops if o.slug != x.slug] + [x]
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
            "also_recorded": also_recorded, "missed_paragraphs": missed, "restored": restored, "resplit": resplit, "citations": citations, "fill_passes": fill_passes, "pages": [{"op": o.op, "slug": o.slug} for o in ops], **json.loads(json.dumps(result, default=str))}


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
