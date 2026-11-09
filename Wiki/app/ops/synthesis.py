"""Synthesis pages from an Ask chat: one consolidated summary of the chat's wiki answers; or of one answer, as a page of
its own or added to an existing synthesis page (whose questions and citations it keeps).

The draft uses only the wiki answers (RAG answers are never sent here) and only the citations that appeared in them. Its
record of the questions, dates and Sources settings is written by code, not by the model. Every draft, edit and save is
checked: the citation check (a clause must be in the source it names), citations that were not in the wiki answers, and
links to pages that do not exist. Nothing is written to the wiki until save()."""
import re
from collections import Counter

from .. import llm, prompts
from ..db import get_pool
from ..wiki import checks, citecheck, saved, store
from ..wiki.store import Op, slugify

LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
RECORD_HEADING = "## Questions answered"


def _links(md: str) -> list[tuple[str, str]]:
    return [(m.group(1).strip(), (m.group(2) or "").strip()) for m in LINK_RE.finditer(md or "")]


FRAMEWORK_RE = re.compile(r"^([a-z]+-\d+[a-z]?)-")  # ifrs-9-measurement -> ifrs-9


def slug_for(chat_id: str, answers: list[dict], wiki_pages: list[str], wiki_name: str, seq: int | None = None) -> str:
    """<framework>-synthesis-<question-id>: the framework of the wiki pages the answers link to (else of the wiki's own
    pages, e.g. ifrs-9), the id from the chat, so a chat always gives the same page; for one answer of the chat, the id
    and the answer's number in the chat, so that answer always gives the same page and never the chat's."""
    def common(slugs):
        c = Counter(m.group(1) for x in slugs if not x.startswith("source-") and (m := FRAMEWORK_RE.match(x)))
        return c.most_common(1)[0][0] if c else None
    framework = common(s for a in answers for s, _ in _links(a["answer"])) or common(wiki_pages) or slugify(wiki_name)
    return f"{framework}-synthesis-{re.sub(r'[^a-z0-9]', '', chat_id.lower())[:8]}{'' if seq is None else f'q{seq}'}"


def record(answers: list[dict], standard_label: str = "", earlier: list[str] | None = None) -> str:
    """The questions, the date each was answered and its Sources setting (written by code, so always exact); the
    Standard only setting by its label in the schema (Checks: Standard only). earlier: the questions an existing page
    already records, kept first."""
    rows = list(earlier or []) + [f"{a['searched']} — answered {a['date'][:10]}, Sources: "
                                  f"{(standard_label or a['sources']) if a['sources'] == 'standard' else 'All'}" for a in answers]
    return f"{RECORD_HEADING}\n\n" + "\n".join(f"{i}. {r}" for i, r in enumerate(rows, 1))


def split_record(content: str) -> tuple[list[str], str]:
    """A synthesis page's recorded questions (without their numbers) and the rest of its text."""
    m = re.match(rf"\s*{re.escape(RECORD_HEADING)}\s*\n((?:\s*\d+\.\s.*\n?)*)", content or "")
    if not m:
        return [], (content or "").strip()
    return [re.sub(r"^\s*\d+\.\s+", "", x) for x in m.group(1).splitlines() if x.strip()], content[m.end():].strip()


async def _into(wiki: dict, slug: str | None) -> dict | None:
    """The existing synthesis page an answer is added to (None when it is not added to one)."""
    if not slug:
        return None
    page = await store.get_page(wiki["id"], slug)
    if not page or page["type"] != "synthesis":
        raise ValueError(f"{slug} is not a synthesis page of this wiki")
    return page


async def check(wiki: dict, content: str, answers: list[dict], into: str | None = None) -> dict:
    """Problems in a draft (nothing is changed): wrongly attributed or unknown citations, citations that were not in the
    wiki answers (or, when the answer is added to an existing page, on that page), and links to pages that do not exist."""
    chk = await citecheck.schema_checks(wiki["id"])
    names = checks.document_name_re(chk)
    _, fixed, flagged = citecheck.check(content, await citecheck.sources(wiki["id"], names), names, chk)
    allowed = {x for a in answers for x in _links(a["answer"])}
    if page := await _into(wiki, into):
        allowed |= set(_links(page["content_md"]))
    slugs = {p["slug"] for p in await store.list_pages(wiki["id"])}
    problems = []
    for (src, to, lab), n in fixed.items():
        problems.append({"kind": "wrong source", "link": f"[[{src}|{lab}]]", "detail": f"the clause is in {to}, not {src}", "count": n})
    for (src, lab, why), n in flagged.items():
        problems.append({"kind": "citation to check", "link": f"[[{src}|{lab}]]", "detail": why, "count": n})
    for (slug, lab), n in Counter(_links(content)).items():
        if (slug, lab) not in allowed:
            problems.append({"kind": "not in the wiki answers", "link": f"[[{slug}{'|' + lab if lab else ''}]]",
                             "detail": "this citation did not appear in any wiki answer in the chat", "count": n})
        elif slug not in slugs:
            problems.append({"kind": "no such page", "link": f"[[{slug}]]", "detail": "the wiki has no page with this name", "count": n})
    return {"problems": problems, "corrections": [{"from": a, "to": b, "label": lab} for (a, b, lab) in fixed]}


async def draft(wiki: dict, chat_id: str, chat_title: str, answers: list[dict], seq: int | None = None,
                into: str | None = None) -> dict:
    """answers: the chat's wiki answers, oldest first: {searched, answer, sources, date}. seq: the number in the chat of
    the one answer drafted on its own; into: the existing synthesis page that answer is added to."""
    body = "\n\n".join(f"<answer n=\"{i}\" question=\"{a['searched']}\">\n{a['answer']}\n</answer>" for i, a in enumerate(answers, 1))
    base = await _into(wiki, into)
    earlier, base_text = split_record(base["content_md"]) if base else ([], "")
    ask = prompts.synthesis_add_prompt(base["title"], base_text, body) if base else prompts.synthesis_prompt(chat_title, body)
    out = await llm.generate_json(prompts.MAINTAINER_SYSTEM, prompts.with_schema(wiki["schema_md"], ask), prompts.SYNTHESIS_SCHEMA)
    chk = checks.load(wiki["schema_md"])
    content = f"{record(answers, chk.standard_only, earlier)}\n\n{out['content_md'].strip()}"
    names = [p["slug"] for p in await store.list_pages(wiki["id"]) if p["type"] != "synthesis"]
    page = {"slug": base["slug"] if base else slug_for(chat_id, answers, names, wiki["name"], seq),
            "title": base["title"] if base else out["title"].strip(), "summary": out["summary"].strip(),
            "tags": out.get("tags") or [], "content_md": content}
    async with get_pool().connection() as conn:
        cur = await (await conn.execute("select version from wiki.pages where wiki_id = %s and slug = %s", (wiki["id"], page["slug"]))).fetchone()
    return {**page, "exists": bool(cur), "version": cur["version"] if cur else None, "into": into,
            **await check(wiki, content, answers, into)}


async def save(wiki: dict, page: dict, answers: list[dict], into: str | None = None) -> dict:
    """Save as a synthesis page (a saved answer). The same chat gives the same page name, so saving again updates it;
    an answer added to an existing page saves that page as a new version (its earlier versions stay in its history)."""
    result = await check(wiki, page["content_md"], answers, into)
    cur = await store.get_page(wiki["id"], page["slug"])
    if cur and cur["type"] != "synthesis":
        raise ValueError(f"A {cur['type']} page is already called {page['slug']}")
    op = Op(op="update" if cur else "create", slug=page["slug"], title=page["title"], type="synthesis", summary=page["summary"],
            content_md=page["content_md"], tags=list(dict.fromkeys([saved.SAVED_TAG, *page.get("tags", [])])),
            base_version=cur["version"] if cur else None,
            change_note=f"Answer added to the synthesis ({len(answers)} wiki answer(s))" if into
            else f"Synthesis of an Ask chat ({len(answers)} wiki answer(s))")
    res = await store.commit(wiki["id"], "query", f"Synthesis: {page['title']}", [op], "auto")
    if res.get("conflicts"):
        raise ValueError(f"The page changed while you were editing: {res['conflicts'][0]['reason']}")
    async with get_pool().connection() as conn:  # saved with problems: needs checking, and not read until saved cleanly
        row = await (await conn.execute("select id from wiki.pages where wiki_id = %s and slug = %s", (wiki["id"], page["slug"]))).fetchone()
        await saved.set_citation_problems(conn, row["id"], result["problems"])
    return {"slug": page["slug"], "status": res["status"], "needs_checking": bool(result["problems"]), **result}
