"""Query: choose pages -> read them -> cited answer; optionally file the answer back as a synthesis page.

How pages are chosen is the wiki's answer_method: search_pick (a search's top pages plus the model's picks from the
index, read at once), browse (the model reads the page list, chooses pages, reads them and follows their links in
rounds until it has enough; only the pages the answer cites are listed) or search_browse (browse, with a shortlist
from a search of every page's text beside the page list: its scores and matching passages guide the choice, and
nothing on it has to be read).

Synthesis pages are never chosen as one of the pages for a question. Saved answers (synthesis pages filed with the
Save button) relevant to the question are read in addition, as earlier answers to check against those pages."""
import hashlib
import logging
import re
from collections.abc import AsyncIterator

from .. import llm, prompts
from ..config import get_settings
from ..db import get_pool
from ..wiki import checks, citecheck, saved, search, store
from ..wiki.store import Op, slugify

log = logging.getLogger(__name__)


async def _select_pages(wiki: dict, question: str) -> list[dict]:
    """The pages for a question: search top 5 + the AI's picks from the index. Synthesis pages are never among them."""
    s = get_settings()
    wiki_id = wiki["id"]
    synth = {p["slug"] for p in await store.list_pages(wiki_id) if p["type"] == "synthesis"}
    hits = await search.search_pages(wiki_id, question, s.query_top_k)
    if synth & {h["slug"] for h in hits[:5]}:  # look further so the top 5 are five other pages
        hits = await search.search_pages(wiki_id, question, s.query_top_k + len(synth))
    hits = [h for h in hits if h["slug"] not in synth]
    # subtopic pages are not navigation targets: they are reached from their section page's index (and by search)
    index = await store.compact_index(wiki_id, exclude_types=("synthesis", "subtopic"))
    picked = await llm.generate_json(
        prompts.MAINTAINER_SYSTEM, prompts.select_prompt(question, index, s.query_max_pages), prompts.SELECT_SCHEMA
    )
    order: list[str] = []
    for slug in [h["slug"] for h in hits[:5]] + [slugify(x) for x in picked["slugs"]]:
        if slug not in order and slug not in synth:
            order.append(slug)
    order = await _with_subtopics(wiki_id, question, order[: s.query_max_pages + 5])
    pages = {p["slug"]: p for p in await store.get_pages(wiki_id, order[: s.query_max_pages + 5])}
    return [pages[x] for x in order if x in pages]


def _shortlist_md(hits: list[dict]) -> str:
    one = lambda x: " ".join(x.split())
    return "\n".join(f"{h['slug']} | {h['score']:.4f} | {h['label_rank'] or '-'} | {h['keyword_rank'] or '-'} | "
                     f"{h['meaning_rank'] or '-'} | {h['title']} | {one(h['excerpt'] or '')}" for h in hits)


async def _browse(wiki: dict, question: str, sources: str, shortlist: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """The pages for a question, chosen the way a reader uses a wiki: from the page list (every page's title and
    one-line summary, subtopic pages included) and the search shortlist where given, then by following links on the
    pages read, until the model has enough. The limits are safety nets. Returns the pages read and, per round, what was
    chosen and why."""
    s = get_settings()
    listed = [p for p in await store.list_pages(wiki["id"]) if p["type"] != "synthesis"]
    listed.sort(key=lambda p: (p["type"] != "overview", p["slug"]))  # a subtopic page follows its section page
    page_list = "\n".join(f"{p['slug']} | {p['type']} | {p['title']} | {p['summary']}" for p in listed)
    known = {p["slug"] for p in listed}
    found = _shortlist_md(shortlist or [])
    read: list[dict] = []
    rounds: list[dict] = []
    for rnd in range(1, s.browse_max_rounds + 1):
        left = s.browse_max_pages - len(read)
        try:
            out = await llm.generate_json(prompts.MAINTAINER_SYSTEM, prompts.with_schema(wiki["schema_md"], prompts.browse_prompt(
                question, page_list, _pages_md(read), left, found)), prompts.BROWSE_SCHEMA)
        except Exception as e:
            log.warning("query: choosing pages, round %s failed: %s", rnd, e)
            rounds.append({"round": rnd, "error": f"{type(e).__name__}: {e}"})
            break
        have = {p["slug"] for p in read}
        want = [x for x in dict.fromkeys(slugify(x) for x in out["read"]) if x in known and x not in have][:left]
        got = {p["slug"]: p for p in await _restrict(wiki, await store.get_pages(wiki["id"], want), sources)} if want else {}
        new, words = [], sum(len(p["content_md"].split()) for p in read)
        for x in want:
            if x in got and (not read or words + len(got[x]["content_md"].split()) <= s.browse_max_words):
                read.append(got[x])
                new.append(x)
                words += len(got[x]["content_md"].split())
        rounds.append({"round": rnd, "chose": out["read"], "read": new, "enough": out["enough"], "why": out["why"],
                       "words_read": words})
        if out["enough"] or not new or len(read) >= s.browse_max_pages:
            break
    return read, rounds


async def _with_subtopics(wiki_id, question: str, order: list[str]) -> list[str]:
    """Where a chosen page is a split section's index, read it and then only the subtopic pages that bear on the
    question (picked from that section's subtopic pages), placed right after the index."""
    subs = [p for p in await store.list_pages(wiki_id) if p["type"] == "subtopic"]
    out: list[str] = []
    for slug in order:
        if slug not in out:
            out.append(slug)
        mine = [p for p in subs if p["slug"].startswith(slug + "-")]
        if not mine or slug.startswith(tuple(p["slug"] for p in subs)):
            continue
        listing = "\n".join(f"{p['slug']} | subtopic | {p['title']} | {p['summary']}" for p in mine)
        try:
            got = await llm.generate_json(prompts.MAINTAINER_SYSTEM, prompts.select_prompt(question, listing, 3), prompts.SELECT_SCHEMA)
        except Exception as e:
            log.warning("query: choosing subtopic pages of %s failed: %s", slug, e)
            continue
        valid = {p["slug"] for p in mine}
        out += [x for x in dict.fromkeys(slugify(x) for x in got["slugs"]) if x in valid and x not in out]
    return out


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


def browses(wiki: dict) -> bool:
    """Pages are chosen in rounds by the model (browse, search_browse), not read at once (search_pick)."""
    return wiki.get("answer_method") in ("browse", "search_browse")


async def _read(wiki: dict, question: str, sources: str, use_saved: bool) -> tuple[list[dict], list[dict], list[dict]]:
    """The pages for the question and, if use_saved, the saved answers read with them (both under the Sources
    setting), and the rounds of choosing (browse and search_browse; under search_browse the first entry is the
    shortlist)."""
    if wiki.get("answer_method") == "search_browse":
        hits = await search.shortlist(wiki["id"], question, get_settings().shortlist_size)
        pages, rounds = await _browse(wiki, question, sources, hits)
        rounds = [{"shortlist": [{k: h[k] for k in ("slug", "score", "label_rank", "keyword_rank", "meaning_rank")} for h in hits]},
                  *rounds]
    elif browses(wiki):
        pages, rounds = await _browse(wiki, question, sources)
    else:
        pages, rounds = await _restrict(wiki, await _select_pages(wiki, question), sources), []
    extra = await _restrict(wiki, await _select_saved(wiki, question), sources) if use_saved and pages else []
    return pages, extra, rounds


def listed(wiki: dict, answer: str, pages: list[dict]) -> list[dict]:
    """The pages shown with an answer: every page read, marked cited or not; under browse and search_browse, only the
    cited ones (and the saved answers read with them, which are never cited but are recorded as read). There a page
    counts as cited when the answer links it or cites a source paragraph the page cites: answers cite clauses, not pages."""
    out = _cited(answer, pages)
    if not browses(wiki):
        return out
    used = checks.cites(answer)
    for p, page in zip(out, pages):
        p["cited"] = p["cited"] or (not p["saved"] and bool(used & checks.cites(page["content_md"])))
    return [p for p in out if p["cited"] or p["saved"]]


def _rounds_md(rounds: list[dict]) -> str:
    found = "".join("\nShortlist: " + (", ".join(f"[[{h['slug']}]]" for h in r["shortlist"]) or "nothing found")
                    for r in rounds if "shortlist" in r)
    return found + "".join(f"\nRound {r['round']}: " + (", ".join(f"[[{x}]]" for x in r["read"]) or "nothing new")
                           + (" (enough)" if r.get("enough") else "") for r in rounds if "read" in r)


def _prompt(wiki: dict, question: str, pages: list[dict], extra: list[dict]) -> str:
    ask = prompts.query_prompt(question, _pages_md(pages)) if not extra else prompts.query_saved_prompt(question, _pages_md(pages), _pages_md(extra))
    return prompts.with_schema(wiki["schema_md"], ask)


async def read_text(wiki: dict, read: list[dict], sources: str) -> list[dict]:
    """The exact text an answer read, rebuilt from each page's recorded version (and the Sources setting), with whether it
    still matches the hash recorded when the answer was given."""
    standard = await _standard_slugs(wiki["id"]) if sources == "standard" else None
    out = []
    async with get_pool().connection() as conn:
        for r in read:
            row = await (await conn.execute(
                """select v.content_md from wiki.page_versions v join wiki.pages p on p.id = v.page_id
                   where p.wiki_id = %s and p.slug = %s and v.version = %s""", (wiki["id"], r.get("slug"), r.get("version")))).fetchone()
            if not row:
                out.append({"slug": r.get("slug"), "version": r.get("version"), "text": None, "matches": False, "reason": "version not found"})
                continue
            md = standard_only(row["content_md"], standard) if standard is not None else row["content_md"]
            same = hashlib.sha256(md.encode()).hexdigest() == r.get("sha256")
            out.append({"slug": r.get("slug"), "version": r.get("version"), "saved": bool(r.get("saved")), "text": md, "matches": same,
                        **({} if same else {"reason": "the rebuilt text differs from what was read"})})
    return out


def _read_record(pages: list[dict]) -> list[dict]:
    """What was given to the model: each page's version and a hash of its text after the Sources setting."""
    return [{"slug": p["slug"], "title": p["title"], "type": p["type"], "version": p.get("version"), "saved": bool(p.get("saved")),
             "words": len(p["content_md"].split()), "sha256": hashlib.sha256(p["content_md"].encode()).hexdigest()} for p in pages]


async def answer(wiki: dict, question: str, save: bool = False, mode: str = "auto", sources: str = "all",
                 use_saved: bool = True) -> dict:
    usage = llm.track_usage()
    pages, extra, rounds = await _read(wiki, question, sources, use_saved)
    if not pages:
        text = ("The wiki has no Standard (Part A) material relevant to this question." if sources == "standard"
                else "The wiki has no pages relevant to this question yet.")
    else:
        text = await llm.generate(prompts.QUERY_SYSTEM, _prompt(wiki, question, pages, extra))
    result = {"answer": text, "pages": listed(wiki, text, pages + extra), "read": _read_record(pages + extra),
              "usage": list(usage), **({"rounds": rounds} if browses(wiki) else {})}
    saved = await save_answer(wiki, question, text, mode) if save and pages else None
    if saved:
        result["saved"] = saved
    await store.add_log(wiki["id"], "query", question[:200], f"Sources: {sources}. Pages read: " + ", ".join(f"[[{p['slug']}]]" for p in pages)
                        + (". Saved answers read: " + ", ".join(f"[[{p['slug']}]]" for p in extra) if extra else "")
                        + _rounds_md(rounds) + (f"\n\nSaved as [[{saved['slug']}]] ({saved['status']})" if saved else ""))
    return result


async def stream_answer(wiki: dict, question: str, sources: str = "all", use_saved: bool = True) -> tuple[list[dict], AsyncIterator[str]]:
    pages, extra, rounds = await _read(wiki, question, sources, use_saved)
    await store.add_log(wiki["id"], "query", question[:200], f"Sources: {sources}. Pages read: " + ", ".join(f"[[{p['slug']}]]" for p in pages)
                        + (". Saved answers read: " + ", ".join(f"[[{p['slug']}]]" for p in extra) if extra else "") + _rounds_md(rounds))
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
