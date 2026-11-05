"""Answers as the schema's Workflow: Answer and check sets out, with every word read from its Checks section: the
answer's layout (Answer layout), its openers (Openers), its force words (Answer force words), the kinds kept apart as
non-authoritative and how conflicting positions rank (Kind ranking). An answer is checked before it is given and sent
back once with its failures; a point it says the Standard does not address is searched for in the text of every
section and subtopic page first. A schema without an Answer layout list is answered as before (query.py)."""
import re

from .. import llm, prompts
from ..config import get_settings
from ..wiki import checks, search, store
from . import fixpass, pagecheck

BASE = pagecheck.BASE
RANGE = re.compile(r"\s*[–-]\s*")
BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}")


def ready(chk) -> bool:
    """Whether the schema lays answers out (Answer layout: its four parts)."""
    return bool(chk and len(chk.answer_headings) == 4)


def checks_off(chk) -> list[str]:
    """The answer lists the schema does not give, or gives in wording the engine cannot read: what uses them is off."""
    if not chk:
        return []
    answer_lists = set(checks.ANSWER_LISTS.values())
    return list(chk.answer_missing) + [x for x in chk.unreadable if x in answer_lists]


# ---------- what a citation cites ----------

def kind_of(srcs: dict, chk, slug: str, label: str) -> str | None:
    """The schema's kind name of the paragraph a citation cites; "" for the Standard's own text (a kind Paragraph kinds
    does not list); None where the wiki holds no such source."""
    info = srcs.get(slug)
    if info is None:
        return None
    whole = BASE(label.strip())  # a passage may be labelled with a range of its own ("IE148–IE159")
    lab = whole if whole in info["kinds"] or whole in info["by_label"] else BASE(RANGE.split(label.strip())[0])
    reader = info["kinds"].get(lab)
    if reader is None:  # text printed without a paragraph label, cited in its kind's own form ("ED:<clause>")
        reader = next((k for k, form in checks.label_forms(chk).items()
                       if (pre := form.split("<", 1)[0]) and lab.startswith(pre)), None)
    return chk.kinds.get(reader or "", "")


def own_text_name(chk) -> str:
    """How the schema's Kind ranking names the Standard's own text (the entry no paragraph kind has)."""
    names = set(chk.kinds.values())
    return next((x for rank in chk.kind_ranking for x in rank if x not in names), "")


def passages_cited(srcs: dict, slug: str, label: str) -> list[str]:
    """The source passages a citation cites (both ends of a range)."""
    by = (srcs.get(slug) or {}).get("by_label", {})
    if BASE(label.strip()) in by:  # a passage labelled with a range of its own ("IE148–IE159")
        return by[BASE(label.strip())]
    return [p for end in RANGE.split(label.strip()) if end for p in by.get(BASE(end), [])]


def _source_cites(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2).strip()) for m in store.LINK_RE.finditer(text) if m.group(1).startswith("source-") and m.group(2)]


# ---------- the layout ----------

def split_parts(answer: str, chk) -> tuple[str, list[str | None]]:
    """The text before the first heading, and the text under each of the layout's headings (None where it is missing)."""
    lines = answer.split("\n")
    at = {}
    for i, ln in enumerate(lines):
        if ln.strip() in chk.answer_headings and ln.strip() not in at:
            at[ln.strip()] = i
    order = sorted((i, h) for h, i in at.items())
    before = "\n".join(lines[: order[0][0]] if order else lines)
    parts: list[str | None] = []
    for h in chk.answer_headings:
        if h not in at:
            parts.append(None)
            continue
        i = at[h]
        nxt = next((j for j, _ in order if j > i), len(lines))
        parts.append("\n".join(lines[i + 1 : nxt]))
    return before, parts


def _level(heading: str) -> int:
    return len(heading) - len(heading.lstrip("#"))


def layout_failures(answer: str, chk) -> list[str]:
    out = []
    heads = chk.answer_headings
    seen = [ln.strip() for ln in answer.split("\n") if ln.strip() in heads]
    for h in heads:
        if seen.count(h) != 1:
            out.append(f'The heading "{h}" appears {seen.count(h)} times; the layout has it once.')
    if [h for h in heads if h in seen] != [h for h in dict.fromkeys(seen)]:
        out.append(f"The headings are not in the layout's order: {'; '.join(heads)}.")
    lvl = _level(heads[0])
    for ln in answer.split("\n"):
        s = ln.strip()
        if s.startswith("#") and _level(s) <= lvl and s not in heads:
            out.append(f'The heading "{s}" is not one of the layout\'s ({"; ".join(heads)}); use them only, with sub-headings under them.')
    before, parts = split_parts(answer, chk)
    if before.strip():
        out.append(f'Text comes before the first heading ("{" ".join(before.split())[:90]}"); every part goes under its heading.')
    for h, body in zip(heads, parts):
        if body is not None and not body.strip():
            out.append(f'The part under "{h}" is empty; a part with nothing in it says "{chk.answer_none}".')
    return out


# ---------- the sentences of an answer ----------

def _sentences(body: str, chk) -> list[str]:
    """The sentences of a part that state something: not headings, rules of a table, its header row, a lead-in ending in
    a colon, a line in bold only, or the layout's word for an empty part."""
    out = []
    lines = (body or "").split("\n")
    for i, raw in enumerate(lines):
        line = BULLET.sub("", raw).strip()
        if not line or line.startswith("#") or TABLE_RULE.match(line) or line == chk.answer_none:
            continue
        if line.startswith("|") and i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1].strip()):
            continue  # a table's header row
        if line.endswith(":") or re.fullmatch(r"\*\*[^*]+\*\*:?", line):
            continue
        out += [s.strip() for s in checks.sentences(line) if s.strip() and s.strip() != chk.answer_none]  # the one split
    return out


def citation_failures(body: str, chk) -> list[str]:
    """A sentence that cites no clause; a link to a page, or to a whole document, in place of a clause."""
    out = []
    for s in _sentences(body, chk):
        links = list(store.LINK_RE.finditer(s))
        if not any(m.group(1).startswith("source-") and m.group(2) for m in links):
            out.append(f'The sentence "{s[:90]}" cites no clause; end it with the clause it rests on, '
                       "[[source-<source-name>|<clause reference>]].")
        for m in links:
            if not m.group(1).startswith("source-"):
                out.append(f"[[{m.group(1)}]] cites a page, not a clause; cite the clause the page cites.")
            elif not m.group(2):
                out.append(f"[[{m.group(1)}]] cites a whole document, not a clause.")
    return list(dict.fromkeys(out))


def placement_failures(main: str, apart: str, chk, srcs: dict) -> list[str]:
    """Non-authoritative material (the layout's kinds) in the answer itself, and authoritative material under the
    non-authoritative heading: application guidance is authoritative and stays in the answer."""
    out = []
    own = own_text_name(chk) or "the Standard's own text"
    for s in _sentences(main, chk):
        for sl, lab in _source_cites(s):
            if (k := kind_of(srcs, chk, sl, lab)) and k in chk.non_authoritative:
                out.append(f'The sentence citing {lab} ("{s[:90]}") is from {k}, which is non-authoritative: it goes under '
                           f'"{chk.answer_headings[3]}", opening with its kind.')
    for s in _sentences(apart, chk):
        for sl, lab in _source_cites(s):
            k = kind_of(srcs, chk, sl, lab)
            if k is not None and k not in chk.non_authoritative:
                out.append(f'The sentence citing {lab} ("{s[:90]}") is from {k or own}, which is authoritative: it goes '
                           f'under "{chk.answer_headings[0]}"' + (", with its opener." if k else "."))
    return list(dict.fromkeys(out))


def references_failures(main: str, refs: str, apart: str) -> list[str]:
    """Every clause the answer relies on is listed under the clause references."""
    listed = {f"{sl}|{BASE(lab)}" for sl, lab in _source_cites(refs or "")}
    out = []
    for sl, lab in _source_cites((main or "") + "\n" + (apart or "")):
        if f"{sl}|{BASE(lab)}" not in listed:
            out.append(f"The clause references do not list [[{sl}|{lab}]], which the answer cites.")
    return list(dict.fromkeys(out))


def _has(text: str, word: str) -> bool:
    return bool(re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text, re.I))


def force_failures(body: str, chk, srcs: dict) -> list[str]:
    """A force word the cited paragraphs do not use where they use another of the same force ("must" for "shall"); a word
    of the schema's strict force (an obligation) where no cited paragraph states one."""
    out = []
    for s in _sentences(body, chk):
        cited = _source_cites(s)
        source = " ".join(p for sl, lab in cited for p in passages_cited(srcs, sl, lab))
        if not source:
            continue
        shown = store.LINK_RE.sub(" ", s)
        labs = ", ".join(lab for _, lab in cited)
        for group, words in chk.force_words.items():
            theirs = [w for w in words if _has(source, w)]
            for w in (w for w in words if _has(shown, w) and w not in theirs):
                if theirs:
                    out.append(f'The sentence citing {labs} ("{s[:90]}") says "{w}" where the paragraph says '
                               f'"{theirs[0]}"; copy the paragraph\'s own word.')
                elif group == chk.force_strict:
                    out.append(f'The sentence citing {labs} ("{s[:90]}") states an obligation ("{w}") that the paragraph '
                               "does not state.")
    return list(dict.fromkeys(out))


def not_addressed_points(body: str | None, chk) -> list[str]:
    return [BULLET.sub("", ln).strip() for ln in (body or "").split("\n")
            if BULLET.sub("", ln).strip() and BULLET.sub("", ln).strip() != chk.answer_none and not ln.strip().startswith("#")]


def searched_failures(body: str | None, chk) -> list[str]:
    """Each point left as not addressed says what was searched for, in the schema's form."""
    lead = chk.searched_form.split("<", 1)[0].strip()
    if not lead:
        return []
    return [f'The point "{p[:90]}" is said not to be addressed, but does not say what was searched for ("{lead} ...").'
            for p in not_addressed_points(body, chk) if lead not in p]


def failures(answer: str, chk, srcs: dict, cite_ctx: dict) -> list[str]:
    """Everything the schema's answer checks find in an answer."""
    out = layout_failures(answer, chk)
    _, (main, refs, gaps, apart) = split_parts(answer, chk)
    stated = "\n\n".join(x for x in (main, apart) if x)
    out += citation_failures(stated, chk)
    covers = lambda label, ref: pagecheck_covers(label, ref, chk)
    out += [f for f in pagecheck.section_check(chk=chk, covers=covers, srcs=srcs, held={}, cite_ctx=cite_ctx,
                                               absence_allowed=True)(stated)]
    out += fixpass.cite_failures(refs or "", cite_ctx, chk) if refs else []
    out += placement_failures(main or "", apart or "", chk, srcs)
    out += references_failures(main or "", refs or "", apart or "") if refs is not None else []
    out += force_failures(stated, chk, srcs) if chk.force_words else []
    out += searched_failures(gaps, chk)
    return list(dict.fromkeys(out))


def pagecheck_covers(label: str, ref: str, chk) -> bool:
    from .ingest import _covers
    return _covers(label, ref, not chk.range_ends)


# ---------- the instruction ----------

def instruction(chk) -> str:
    """The answer's system instruction: the schema's layout, openers, force words and ranking, in its own words."""
    h = chk.answer_headings
    names = sorted(set(chk.kinds.values()))
    main_kinds = [k for k in names if k not in chk.non_authoritative]
    openers = "; ".join(f"{k}: {' or '.join(repr(x) for x in v)}" for k, v in chk.openers.items())
    force = "; ".join(f"{g}: {', '.join(repr(w) for w in ws)}" for g, ws in chk.force_words.items())
    ranking = "; then ".join(", ".join(r) for r in chk.kind_ranking)
    return "\n".join(x for x in [
        "You answer questions using ONLY the wiki pages provided, as the schema's Workflow: Answer and check sets out. "
        "Do not use outside knowledge.",
        "- Every sentence that states something from a source ends with the clause it rests on, written "
        "[[source-<source-name>|<clause reference>]] exactly as the pages cite it. Never cite a page or a whole document.",
        f"- Lay the answer out under these headings, in this order, with no other heading at that level: {h[0]} (the "
        f"answer); {h[1]} (every clause the answer relies on, one per line, each as its citation); {h[2]} (each point "
        f"the standard does not address); {h[3]} (only material from {', '.join(chk.non_authoritative)}, each item "
        f"opening with what it is). Under a heading with nothing to put there, write \"{chk.answer_none}\".",
        f"- Material from {', '.join(main_kinds)} stays under {h[0]}, each sentence opening with what it is." if main_kinds else "",
        f"- A sentence from a paragraph of these kinds opens with its opener: {openers}. A sentence from the Standard's "
        "own paragraphs has no opener." if openers else "",
        f"- Copy each force word as the cited paragraph uses it, never replacing it ({force}). Use a word of "
        f"{chk.force_strict or 'obligation'} only where a paragraph you cite uses one, and the one it uses." if force else "",
        f"- Where the pages give conflicting positions, state both, each with its clause, and rank them by kind, highest "
        f"first: {ranking}." if ranking else "",
        f"- Before listing a point under {h[2]}, check every page given for it, Definitions included.",
    ] if x)


NOT_ADDRESSED_TERMS = {
    "type": "object",
    "properties": {"points": {"type": "array", "items": {"type": "object", "properties": {
        "point": {"type": "string"}, "terms": {"type": "array", "items": {"type": "string"}}},
        "required": ["point", "terms"]}}},
    "required": ["points"],
}


def terms_prompt(points: list[str]) -> str:
    return ("An answer says the standard does not address each point below. For each point, give the terms to search "
            "the wiki's pages for: its key words as the point puts them, and the words the standard would use for them, "
            "including any defined term. Return each point as given.\n\n<points>\n"
            + "\n".join(f"- {p}" for p in points) + "\n</points>")


def search_prompt(question: str, pages_md: str, draft: str, found: list[dict], chk) -> str:
    lines = "\n".join(f"- {f['point']}\n  If still not addressed, it ends: {f['searched']}" for f in found)
    return (f"<wiki_pages>\n{pages_md}\n</wiki_pages>\n\n<draft_answer>\n{draft}\n</draft_answer>\n\n"
            f"<not_addressed_search>\nThe draft says the points below are not addressed. The text of every section page and "
            "subtopic page was searched for each, and the pages the search found are among the pages above. Write the "
            "answer again: answer a point from the pages where they address it; list a point under "
            f"{chk.answer_headings[2]} only where they do not, ending it with the line given for it, word for word.\n"
            f"{lines}\n</not_addressed_search>\n\nQuestion: {question}")


def fix_prompt(question: str, pages_md: str, answer: str, fails: list[str]) -> str:
    return (f"<wiki_pages>\n{pages_md}\n</wiki_pages>\n\n<answer>\n{answer}\n</answer>\n\n"
            "The answer above fails these checks. Write it again so that it passes them, from the same pages, changing "
            "nothing the checks do not name:\n" + "\n".join(f"- {f}" for f in fails) + f"\n\nQuestion: {question}")


def terms_page_title(pages: list[dict], chk) -> str:
    """The title of the page that defines the wiki's terms (the page citing most of them in the Defined-term citation
    form), as the schema's Page summary names it."""
    held = {p["slug"]: len(checks.defined_terms(p["content_md"], chk)) for p in pages if p["type"] in ("topic", "subtopic")}
    best = max(held, key=held.get, default=None)
    return next((p["title"] for p in pages if p["slug"] == best and held[best]), "")


def searched_line(chk, terms: list[str], definitions: str) -> str:
    return (chk.searched_form.replace("<terms>", ", ".join(f'"{t}"' for t in terms))
            .replace("<definitions page>", definitions or "").replace(" ,", ",").strip())


async def search_not_addressed(wiki: dict, chk, points: list[str], have: set[str], restrict) -> tuple[list[dict], list[dict]]:
    """Each point an answer says is not addressed, searched for in the text of every section and subtopic page: what
    was searched for, the pages found, and the pages to read that were not read yet (under the Sources setting)."""
    s = get_settings()
    out = await llm.generate_json(prompts.MAINTAINER_SYSTEM, terms_prompt(points), NOT_ADDRESSED_TERMS)
    asked = {" ".join(x["point"].split()): x["terms"] for x in out["points"]}
    listed = {p["slug"]: p for p in await store.list_pages(wiki["id"])}
    sections = {sl for sl, p in listed.items() if p["type"] in ("topic", "subtopic")}
    everything = await store.list_pages(wiki["id"], with_content=True)
    definitions = terms_page_title(everything, chk)
    found, more = [], []
    for p in points:
        terms = asked.get(" ".join(p.split())) or [p]
        hits = [h for h in await search.shortlist(wiki["id"], " ".join(terms), s.shortlist_size) if h["slug"] in sections]
        new = [h["slug"] for h in hits[:5] if h["slug"] not in have and h["slug"] not in {m["slug"] for m in more}]
        more += await restrict(await store.get_pages(wiki["id"], new)) if new else []
        found.append({"point": p, "terms": terms, "pages": [h["slug"] for h in hits[:5]],
                      "searched": searched_line(chk, terms, definitions)})
    return found, more
