"""Synthesis pages from an Ask chat: one consolidated summary of the chat's wiki answers.

The draft uses only the wiki answers (RAG answers are never sent here) and only the citations that appeared in them. Its
record of the questions, dates and Sources settings is written by code, not by the model. Every draft, edit and save is
checked: the citation check (a clause must be in the source it names), citations that were not in the wiki answers, and
links to pages that do not exist. Nothing is written to the wiki until save()."""
import re
from collections import Counter

from .. import llm, prompts
from ..db import get_pool
from ..wiki import citecheck, saved, store
from ..wiki.store import Op, slugify

LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
RECORD_HEADING = "## Questions answered"


def _links(md: str) -> list[tuple[str, str]]:
    return [(m.group(1).strip(), (m.group(2) or "").strip()) for m in LINK_RE.finditer(md or "")]


FRAMEWORK_RE = re.compile(r"^([a-z]+-\d+[a-z]?)-")  # ifrs-9-measurement -> ifrs-9


def slug_for(chat_id: str, answers: list[dict], wiki_pages: list[str], wiki_name: str) -> str:
    """<framework>-synthesis-<question-id>: the framework of the wiki pages the answers link to (else of the wiki's own
    pages, e.g. ifrs-9), the id from the chat, so a chat always gives the same page."""
    def common(slugs):
        c = Counter(m.group(1) for x in slugs if not x.startswith("source-") and (m := FRAMEWORK_RE.match(x)))
        return c.most_common(1)[0][0] if c else None
    framework = common(s for a in answers for s, _ in _links(a["answer"])) or common(wiki_pages) or slugify(wiki_name)
    return f"{framework}-synthesis-{re.sub(r'[^a-z0-9]', '', chat_id.lower())[:8]}"


def record(answers: list[dict]) -> str:
    """The questions, the date each was answered and its Sources setting (written by code, so always exact)."""
    rows = [f"{i}. {a['searched']} — answered {a['date'][:10]}, Sources: {'Standard only' if a['sources'] == 'standard' else 'All'}"
            for i, a in enumerate(answers, 1)]
    return f"{RECORD_HEADING}\n\n" + "\n".join(rows)


async def check(wiki: dict, content: str, answers: list[dict]) -> dict:
    """Problems in a draft (nothing is changed): wrongly attributed or unknown citations, citations that were not in the
    wiki answers, and links to pages that do not exist."""
    names = await citecheck.document_names(wiki["id"])
    _, fixed, flagged = citecheck.check(content, await citecheck.sources(wiki["id"], names), names)
    allowed = {x for a in answers for x in _links(a["answer"])}
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


async def draft(wiki: dict, chat_id: str, chat_title: str, answers: list[dict]) -> dict:
    """answers: the chat's wiki answers, oldest first: {searched, answer, sources, date}."""
    body = "\n\n".join(f"<answer n=\"{i}\" question=\"{a['searched']}\">\n{a['answer']}\n</answer>" for i, a in enumerate(answers, 1))
    out = await llm.generate_json(
        prompts.MAINTAINER_SYSTEM,
        prompts.with_schema(wiki["schema_md"], prompts.synthesis_prompt(chat_title, body)),
        prompts.SYNTHESIS_SCHEMA,
    )
    content = f"{record(answers)}\n\n{out['content_md'].strip()}"
    names = [p["slug"] for p in await store.list_pages(wiki["id"]) if p["type"] != "synthesis"]
    page = {"slug": slug_for(chat_id, answers, names, wiki["name"]), "title": out["title"].strip(), "summary": out["summary"].strip(),
            "tags": out.get("tags") or [], "content_md": content}
    async with get_pool().connection() as conn:
        cur = await (await conn.execute("select version from wiki.pages where wiki_id = %s and slug = %s", (wiki["id"], page["slug"]))).fetchone()
    return {**page, "exists": bool(cur), "version": cur["version"] if cur else None, **await check(wiki, content, answers)}


async def save(wiki: dict, page: dict, answers: list[dict]) -> dict:
    """Save as a synthesis page (a saved answer). The same chat gives the same page name, so saving again updates it."""
    result = await check(wiki, page["content_md"], answers)
    cur = await store.get_page(wiki["id"], page["slug"])
    if cur and cur["type"] != "synthesis":
        raise ValueError(f"A {cur['type']} page is already called {page['slug']}")
    op = Op(op="update" if cur else "create", slug=page["slug"], title=page["title"], type="synthesis", summary=page["summary"],
            content_md=page["content_md"], tags=list(dict.fromkeys([saved.SAVED_TAG, *page.get("tags", [])])),
            base_version=cur["version"] if cur else None,
            change_note=f"Synthesis of an Ask chat ({len(answers)} wiki answer(s))")
    res = await store.commit(wiki["id"], "query", f"Synthesis: {page['title']}", [op], "auto")
    if res.get("conflicts"):
        raise ValueError(f"The page changed while you were editing: {res['conflicts'][0]['reason']}")
    async with get_pool().connection() as conn:  # saved with problems: needs checking, and not read until saved cleanly
        row = await (await conn.execute("select id from wiki.pages where wiki_id = %s and slug = %s", (wiki["id"], page["slug"]))).fetchone()
        await saved.set_citation_problems(conn, row["id"], result["problems"])
    return {"slug": page["slug"], "status": res["status"], "needs_checking": bool(result["problems"]), **result}
