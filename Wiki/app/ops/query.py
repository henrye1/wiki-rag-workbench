"""Query: choose pages -> read them -> cited answer; optionally file the answer back as a synthesis page.

How pages are chosen (the one way every wiki answers): a search of every page's text gives a shortlist (scores and
matching passages) beside the page list; the model chooses pages from both, reads them and follows their links in
rounds until it has enough. Only the pages the answer cites are listed with it.

Synthesis pages are never chosen as one of the pages for a question. Saved answers (synthesis pages filed with the
Save button) relevant to the question are read in addition, as earlier answers to check against those pages; one
flagged as needing checking, or saved with citation problems, is not read.

Where the schema lays answers out (its Answer layout), the answer follows the schema's Workflow: Answer and check
(answering.py): its instruction is built from the schema, a point it says is not addressed is searched for first, and it
is checked and sent back once with its failures. The Sources setting "Standard only" keeps the statements citing only
the Standard's own text, by paragraph kind (Checks: Standard only)."""
import hashlib
import logging
import re
from collections.abc import AsyncIterator

from .. import llm, prompts
from ..config import get_settings
from ..db import get_pool
from ..wiki import checks, citecheck, saved, search, store
from ..wiki.store import Op, slugify
from . import answering, fixpass, pagecheck, sourcemap
from .ingest import _sections

log = logging.getLogger(__name__)


def _shortlist_md(hits: list[dict]) -> str:
    one = lambda x: " ".join(x.split())
    return "\n".join(f"{h['slug']} | {h['score']:.4f} | {h['label_rank'] or '-'} | {h['keyword_rank'] or '-'} | "
                     f"{h['meaning_rank'] or '-'} | {h['title']} | {one(h['excerpt'] or '')}" for h in hits)


async def _browse(wiki: dict, question: str, sources: str, shortlist: list[dict]) -> tuple[list[dict], list[dict]]:
    """The pages for a question, chosen the way a reader uses a wiki: from the page list (every page's title and
    one-line summary, subtopic pages included) and the search shortlist, then by following links on the pages read,
    until the model has enough. The limits are safety nets. Returns the pages read and, per round, what was chosen
    and why."""
    s = get_settings()
    listed = [p for p in await store.list_pages(wiki["id"]) if p["type"] != "synthesis"]
    listed.sort(key=lambda p: (p["type"] != "overview", p["slug"]))  # a subtopic page follows its section page
    page_list = "\n".join(f"{p['slug']} | {p['type']} | {p['title']} | {p['summary']}" for p in listed)
    known = {p["slug"] for p in listed}
    found = _shortlist_md(shortlist)
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


# "Sources: Standard only" (the schema's Checks: Standard only): keep only the statements whose citations are all to
# the Standard's own text, by paragraph kind; a page also holds guidance, examples and notes, of other kinds
_SOURCE_CITE = re.compile(r"\[\[(source-[^\]|#]+)")
_HEADING = re.compile(r"^\s*#{1,6} ")


class NoStandardOnly(ValueError):
    """The wiki's schema gives no Standard only list, so the setting cannot be applied."""


async def _own_text(wiki: dict):
    """keep(slug, label): whether a citation cites the Standard's own text (a paragraph of no kind the schema's
    Paragraph kinds lists), as the schema's Standard only list sets out."""
    chk = checks.load(wiki["schema_md"])
    if not (chk.standard_only):
        raise NoStandardOnly(f"This wiki's schema has no {checks.ANSWER_LISTS['standard_only']!r} list in its Checks, so "
                             f"answers cannot be limited to {answering.own_text_label(chk)}.")
    srcs = await pagecheck.sources(wiki["id"])
    return lambda slug, label: answering.kind_of(srcs, chk, slug, label) == ""


def standard_only(md: str, keep) -> str:
    """The page text keeping headings and only the statements whose source citations all pass keep(slug, label)."""
    lines = []
    for line in md.split("\n"):
        if not line.strip() or _HEADING.match(line):
            lines.append(line)
            continue
        lead = (checks.BULLET.match(line) or [""])[0]
        parts = checks.sentences(line[len(lead):])  # the one sentence split (checks.sentences)
        kept = [p.strip() for p in parts if (cited := answering._source_cites(p)) and all(keep(sl, lab) for sl, lab in cited)]
        if kept:
            lines.append(lead + " ".join(kept))
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
    keep = await _own_text(wiki)
    out = []
    for p in pages:
        md = standard_only(p["content_md"], keep)
        if _SOURCE_CITE.search(md):
            out.append({**p, "content_md": md})
    return out


def _pages_md(pages: list[dict]) -> str:
    return "\n\n".join(
        f"<saved_answer slug=\"{p['slug']}\" title=\"{p['title']}\" saved=\"{p['updated_at']:%Y-%m-%d}\">\n{p['content_md']}\n</saved_answer>"
        if p.get("saved") else f"<page slug=\"{p['slug']}\" title=\"{p['title']}\" type=\"{p['type']}\">\n{p['content_md']}\n"
        + (f"<source_map>\n{p['source_map']}\n</source_map>\n" if p.get("source_map") else "") + "</page>"
        for p in pages)


async def _with_maps(wiki: dict, pages: list[dict]) -> list[dict]:
    """Each page read with its source map, where the schema's Source map line says yes; otherwise the pages as they are."""
    chk = checks.load(wiki["schema_md"])
    if not (chk and chk.source_map):
        return pages
    return [p if p.get("saved") or p.get("source_map") else {**p, "source_map": await sourcemap.for_answer(wiki["id"], p, chk)}
            for p in pages]


def _cited(answer: str, pages: list[dict]) -> list[dict]:
    linked = store.extract_links(answer)
    return [{"slug": p["slug"], "title": p["title"], "cited": p["slug"] in linked, "saved": bool(p.get("saved"))} for p in pages]


async def _read(wiki: dict, question: str, sources: str, use_saved: bool) -> tuple[list[dict], list[dict], list[dict]]:
    """The pages for the question and, if use_saved, the saved answers read with them (both under the Sources
    setting), and the rounds of choosing (the first entry is the search shortlist)."""
    hits = await search.shortlist(wiki["id"], question, get_settings().shortlist_size)
    pages, rounds = await _browse(wiki, question, sources, hits)
    rounds = [{"shortlist": [{k: h[k] for k in ("slug", "score", "label_rank", "keyword_rank", "meaning_rank")} for h in hits]},
              *rounds]
    extra = await _restrict(wiki, await _select_saved(wiki, question), sources) if use_saved and pages else []
    return pages, extra, rounds


def listed(wiki: dict, answer: str, pages: list[dict]) -> list[dict]:
    """The pages shown with an answer: the cited ones (and the saved answers read with them, which are never cited but
    are recorded as read). A page counts as cited when the answer links it or cites a source paragraph the page cites:
    answers cite clauses, not pages."""
    out = _cited(answer, pages)
    used = checks.cites(answer)
    for p, page in zip(out, pages):
        p["cited"] = p["cited"] or (not p["saved"] and bool(used & checks.cites(page["content_md"])))
    return [p for p in out if p["cited"] or p["saved"]]


def _rounds_md(rounds: list[dict]) -> str:
    """The shortlist and each round's pages read."""
    found = "".join("\nShortlist: " + (", ".join(f"[[{h['slug']}]]" for h in r["shortlist"]) or "nothing found")
                    for r in rounds if "shortlist" in r)
    return found + "".join(f"\nRound {r['round']}: " + (", ".join(f"[[{x}]]" for x in r["read"]) or "nothing new")
                           + (" (enough)" if r.get("enough") else "")
                           for r in rounds if "read" in r)


def _log_md(wiki: dict, sources: str, pages: list[dict], extra: list[dict], rounds: list[dict], report: dict | None = None) -> str:
    one = lambda x: " ".join(str(x).split())
    checked = ("" if report is None else
               "".join(f"\nNot addressed, searched for: {one(f['point'])} ({', '.join(f['terms'])}); found: "
                       + (", ".join(f"[[{x}]]" for x in f["pages"]) or "nothing") for f in report.get("not_addressed_search", []))
               + f"\nAnswer checks: {len(report['found'])} found, {len(report['left'])} left"
               + (f" (off: {', '.join(report['checks_off'])})" if report["checks_off"] else ""))
    return (f"Sources: {sources}. Pages read: " + ", ".join(f"[[{p['slug']}]]" for p in pages)
            + (". Saved answers read: " + ", ".join(f"[[{p['slug']}]]" for p in extra) if extra else "")
            + _rounds_md(rounds) + checked)


def _prompt(wiki: dict, question: str, pages: list[dict], extra: list[dict]) -> str:
    ask = prompts.query_prompt(question, _pages_md(pages)) if not extra else prompts.query_saved_prompt(question, _pages_md(pages), _pages_md(extra))
    return prompts.with_schema(wiki["schema_md"], ask)


async def read_text(wiki: dict, read: list[dict], sources: str) -> list[dict]:
    """The exact text an answer read, rebuilt from each page's recorded version (and the Sources setting), with whether it
    still matches the hash recorded when the answer was given."""
    keep = await _own_text(wiki) if sources == "standard" else None
    out = []
    async with get_pool().connection() as conn:
        for r in read:
            row = await (await conn.execute(
                """select v.content_md from wiki.page_versions v join wiki.pages p on p.id = v.page_id
                   where p.wiki_id = %s and p.slug = %s and v.version = %s""", (wiki["id"], r.get("slug"), r.get("version")))).fetchone()
            if not row:
                out.append({"slug": r.get("slug"), "version": r.get("version"), "text": None, "matches": False, "reason": "version not found"})
                continue
            md = standard_only(row["content_md"], keep) if keep is not None else row["content_md"]
            same = hashlib.sha256(md.encode()).hexdigest() == r.get("sha256")
            out.append({"slug": r.get("slug"), "version": r.get("version"), "saved": bool(r.get("saved")), "text": md, "matches": same,
                        **({} if same else {"reason": "the rebuilt text differs from what was read"})})
    return out


def _read_record(pages: list[dict]) -> list[dict]:
    """What was given to the model: each page's version and a hash of its text after the Sources setting."""
    return [{"slug": p["slug"], "title": p["title"], "type": p["type"], "version": p.get("version"), "saved": bool(p.get("saved")),
             "words": len(p["content_md"].split()), "sha256": hashlib.sha256(p["content_md"].encode()).hexdigest(),
             **({"source_map": p["source_map"]} if p.get("source_map") else {})} for p in pages]  # the map given with it, if any


def _nothing(wiki: dict, sources: str) -> str:
    chk = checks.load(wiki["schema_md"])
    return (f'Under "{chk.standard_only}", the wiki has no material relevant to this question.' if sources == "standard"
            else "The wiki has no pages relevant to this question yet.")


async def _checked(wiki: dict, chk, question: str, pages: list[dict], extra: list[dict], sources: str) -> tuple[str, list[dict], dict]:
    """An answer as the schema's Workflow: Answer and check sets out: written under the schema's instruction; each
    point it says is not addressed searched for in every section and subtopic page, and the answer written again with
    what was found; then checked, and sent back once with its failures; a point the rewrite leaves as not addressed that
    was not searched for yet is searched for then, before the answer is final. Its clause references are built, after each
    draft, from the citations that end its sentences. Returns the answer, the pages read (those the
    search found included) and the report of its checks."""
    system, schema = answering.instruction(chk, wiki["schema_md"]), wiki["schema_md"]
    srcs = await pagecheck.sources(wiki["id"])
    cite_ctx = await fixpass.cite_context(wiki["id"], [x["name"] for x in _sections(schema)])
    report: dict = {"checks_off": answering.checks_off(chk)}
    searched: list[dict] = []  # what the not-addressed search looked for, once it has run
    # each draft: its points not addressed end with what was searched for; its clause references are built from the
    # citations that end its sentences
    refs = lambda t: answering.with_references(answering.with_searched(t, chk, searched), chk)
    text = refs(await llm.generate(system, _prompt(wiki, question, pages, extra)))

    async def search_round(text: str, fails: list[str] | None) -> tuple[str, list[str] | None]:
        """The points left as not addressed that are not searched yet, searched for; the answer written again with what
        was found (after a fix round, kept unless it fails more). Each point then ends with what was searched for."""
        nonlocal pages
        if not (points := answering.unsearched(text, chk, searched)):
            return text, fails
        try:
            found, more = await answering.search_not_addressed(wiki, chk, points, {p["slug"] for p in pages},
                                                               lambda ps: _restrict(wiki, ps, sources))
        except Exception as e:
            log.warning("query: searching for the points not addressed failed: %s", e)
            report["not_addressed_search_error"] = f"{type(e).__name__}: {e}"
            return text, fails
        pages = pages + await _with_maps(wiki, more)
        searched.extend(found)
        report.setdefault("not_addressed_search", []).extend(
            {k: f[k] for k in ("point", "terms", "pages", "terms_missing") if k in f} for f in found)
        text = refs(text)  # what was searched for, on the points as they stand
        try:
            again = refs(await llm.generate(system, prompts.with_schema(schema, answering.search_prompt(
                question, _pages_md(pages), text, found, chk))))
        except Exception as e:
            log.warning("query: writing the answer again with what the search found failed: %s", e)
            report["not_addressed_rewrite_error"] = f"{type(e).__name__}: {e}"
            return text, None if fails is None else answering.failures(text, chk, srcs, cite_ctx)
        if fails is None:
            return again, None
        left = answering.failures(again, chk, srcs, cite_ctx)
        now = answering.failures(text, chk, srcs, cite_ctx)
        return (again, left) if len(left) <= len(now) else (text, now)

    text, _ = await search_round(text, None)
    fails = answering.failures(text, chk, srcs, cite_ctx)
    report["found"] = fails
    if fails:
        try:
            again = refs(await llm.generate(system, prompts.with_schema(schema, answering.fix_prompt(question, _pages_md(pages), text, fails))))
            left = answering.failures(again, chk, srcs, cite_ctx)
            if len(left) <= len(fails):  # the rewrite is kept unless it fails more
                text, fails = again, left
        except Exception as e:
            log.warning("query: the answer's fix pass failed: %s", e)
            report["fix_error"] = f"{type(e).__name__}: {e}"
    # a point the fix round left as not addressed that the search has not looked for: searched before the answer is final
    text, fails = await search_round(text, fails)
    report["left"] = fails
    return text, pages, report


async def _compose(wiki: dict, question: str, pages: list[dict], extra: list[dict], sources: str) -> tuple[str, list[dict], dict | None]:
    chk = checks.load(wiki["schema_md"])
    if not pages:
        return _nothing(wiki, sources), pages, None
    pages = await _with_maps(wiki, pages)
    if answering.ready(chk):
        return await _checked(wiki, chk, question, pages, extra, sources)
    return await llm.generate(prompts.QUERY_SYSTEM, _prompt(wiki, question, pages, extra)), pages, None


async def answer(wiki: dict, question: str, save: bool = False, mode: str = "auto", sources: str = "all",
                 use_saved: bool = True) -> dict:
    usage = llm.track_usage()
    pages, extra, rounds = await _read(wiki, question, sources, use_saved)
    text, pages, report = await _compose(wiki, question, pages, extra, sources)
    result = {"answer": text, "pages": listed(wiki, text, pages + extra), "read": _read_record(pages + extra),
              "usage": list(usage), "rounds": rounds,
              **({"answer_check": report} if report is not None else {})}
    saved = await save_answer(wiki, question, text, mode, sources) if save and pages else None
    if saved:
        result["saved"] = saved
    await store.add_log(wiki["id"], "query", question[:200], _log_md(wiki, sources, pages, extra, rounds, report)
                        + (f"\n\nSaved as [[{saved['slug']}]] ({saved['status']})" if saved else ""))
    return result


async def _once(text: str) -> AsyncIterator[str]:
    yield text


async def stream_answer(wiki: dict, question: str, sources: str = "all",
                        use_saved: bool = True) -> tuple[list[dict], AsyncIterator[str], dict | None]:
    """The pages read, the answer's text as it comes, and its check report. An answer the schema checks is given whole,
    once checked (it is not streamed as it is written: it may be written again)."""
    pages, extra, rounds = await _read(wiki, question, sources, use_saved)
    if answering.ready(checks.load(wiki["schema_md"])) or not pages:
        text, pages, report = await _compose(wiki, question, pages, extra, sources)
        await store.add_log(wiki["id"], "query", question[:200], _log_md(wiki, sources, pages, extra, rounds, report))
        return pages + extra, _once(text), report
    await store.add_log(wiki["id"], "query", question[:200], _log_md(wiki, sources, pages, extra, rounds))
    pages = await _with_maps(wiki, pages)
    return pages + extra, llm.stream(prompts.QUERY_SYSTEM, _prompt(wiki, question, pages, extra)), None


async def save_answer(wiki: dict, question: str, answer_md: str, mode: str, sources: str = "all") -> dict:
    """File one answer as a synthesis page: slug <framework>-synthesis-<question-id> (the question's own short id, the
    same each time the same question is saved, so saving again updates it), with the question and date recorded."""
    import datetime as dt
    from . import synthesis
    wiki_id = wiki["id"]
    index = await store.compact_index(wiki_id)
    out = await llm.generate_json(
        prompts.MAINTAINER_SYSTEM,
        prompts.with_schema(wiki["schema_md"], prompts.save_answer_prompt(question, answer_md, index)),
        prompts.PAGE_SCHEMA,
    )
    qid = hashlib.sha1(" ".join(question.split()).casefold().encode()).hexdigest()
    names = [p["slug"] for p in await store.list_pages(wiki_id) if p["type"] != "synthesis"]
    slug = synthesis.slug_for(qid, [{"answer": answer_md}], names, wiki["name"])
    cur = await store.get_page(wiki_id, slug)
    if cur and cur["type"] != "synthesis":
        raise ValueError(f"A {cur['type']} page is already called {slug}")
    chk = checks.load(wiki["schema_md"])
    record = synthesis.record([{"searched": question, "date": dt.date.today().isoformat(), "sources": sources}],
                              chk.standard_only)
    op = Op(op="update" if cur else "create", slug=slug, title=out["title"], type="synthesis", summary=out["summary"],
            content_md=f"{record}\n\n{out['content_md'].strip()}", tags=list(dict.fromkeys([saved.SAVED_TAG, *out["tags"]])),
            base_version=cur["version"] if cur else None, change_note=f"Filed from query: {question[:150]}")
    citations = await citecheck.check_ops(wiki_id, [op])  # every citation must name a source that holds the clause
    res = await store.commit(wiki_id, "query", f"Save answer: {out['title']}", [op], mode)
    return {"slug": slug, "status": res["status"], "changeset_id": res.get("changeset_id"), "citations": citations}
