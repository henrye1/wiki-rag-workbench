"""Checking a client statement (the watchdog), as the schema's Workflow: Answer and check sets out: the pages are read
as for a question, the clauses the statement relies on are found, and one verdict from the schema's Client-statement
verdicts is given, each clause cited and the passage it rests on quoted word for word from the source. The verdict is
checked (a clause the source holds; a quote found in it, word for word) and sent back once with its failures. It is
recorded as a finding, closed only by a named reviewer; it never changes a page."""
import re
from uuid import UUID

from psycopg.types.json import Jsonb

from .. import llm, prompts
from ..config import get_settings
from ..db import get_pool
from ..wiki import checks
from . import answering, pagecheck


class NoVerdicts(ValueError):
    """The wiki's schema gives no Client-statement verdicts list."""


def verdict_schema(chk) -> dict:
    return {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": list(chk.verdicts)},
            "clauses": {"type": "array", "items": {"type": "object", "properties": {
                "citation": {"type": "string", "description": "[[source-<source-name>|<clause reference>]]"},
                "quote": {"type": "string", "description": "the passage it rests on, word for word from the source paragraph"}},
                "required": ["citation", "quote"]}},
            "reasoning": {"type": "string"},
        },
        "required": ["verdict", "clauses", "reasoning"],
    }


def _plain(x: str) -> str:
    x = re.sub(r"[‘’]", "'", re.sub(r"[“”]", '"', x or ""))
    return " ".join(re.sub(r"[–—]", "-", x).split())


def quote_failures(clauses: list[dict], srcs: dict, chk) -> list[str]:
    """A verdict's clauses: each a citation of a paragraph its source holds, with a quote found in that paragraph word for
    word (spacing and quotation-mark styles aside); a verdict citing no clause."""
    out = [] if clauses else ["The verdict cites no clause; every verdict cites the clause it rests on and quotes it."]
    for c in clauses:
        cited = answering._source_cites(c.get("citation") or "")
        if not cited:
            out.append(f'"{c.get("citation")}" is not a clause citation ([[source-<source-name>|<clause reference>]]).')
            continue
        text = _plain(" ".join(p for sl, lab in cited for p in answering.passages_cited(srcs, sl, lab)))
        if not text:
            out.append(f"{c['citation']} cites a paragraph the source does not hold.")
        elif not c.get("quote") or _plain(c["quote"]) not in text:
            out.append(f"The quote given for {c['citation']} is not found word for word in that paragraph; quote the "
                       "paragraph's own words.")
    return out


def source_md(pages: list[dict], srcs: dict, max_words: int) -> str:
    """The source paragraphs the pages read cite, in full, for quoting (at most max_words, in the order cited)."""
    out, words = [], 0
    for sl, lab in dict.fromkeys(x for p in pages for x in answering._source_cites(p["content_md"])):
        for passage in answering.passages_cited(srcs, sl, lab):
            n = len(passage.split())
            if words + n > max_words:
                return "\n\n".join(out)
            out.append(f'<paragraph source="{sl}" label="{lab}">\n{passage}\n</paragraph>')
            words += n
    return "\n\n".join(dict.fromkeys(out))


def prompt(statement: str, pages_md: str, sources_md: str, chk) -> str:
    return (f"<wiki_pages>\n{pages_md}\n</wiki_pages>\n\n<source_paragraphs>\n{sources_md}\n</source_paragraphs>\n\n"
            "Check the client statement below against the standard, as the schema's Workflow: Answer and check sets out "
            "for checking a client statement: find the clause or clauses it relies on, compare the statement with what "
            "they say, and give one verdict from: " + "; ".join(f'"{v}"' for v in chk.verdicts) + ". Cite each clause "
            "as the pages cite it, [[source-<source-name>|<clause reference>]], and quote the passage it rests on word "
            "for word from the source paragraph given above. Say briefly why.\n\n"
            f"<client_statement>\n{statement}\n</client_statement>")


async def check_statement(wiki: dict, statement: str, sources: str = "all") -> dict:
    """The verdict on a client statement, checked and recorded as an open finding. Changes no page."""
    from . import query
    chk = checks.load(wiki["schema_md"])
    if not (chk.verdicts):
        raise NoVerdicts("This wiki's schema has no Client-statement verdicts list in its Checks.")
    pages, _, rounds = await query._read(wiki, statement, sources, use_saved=False)
    srcs = await pagecheck.sources(wiki["id"])
    ask = prompts.with_schema(wiki["schema_md"], prompt(statement, query._pages_md(pages),
                                                        source_md(pages, srcs, get_settings().browse_max_words // 3), chk))
    out = await llm.generate_json(prompts.MAINTAINER_SYSTEM, ask, verdict_schema(chk))
    found = fails = quote_failures(out["clauses"], srcs, chk)
    if fails:
        again = await llm.generate_json(prompts.MAINTAINER_SYSTEM, ask + "\n\nYour earlier verdict failed these checks; "
                                        "give it again so that it passes them:\n" + "\n".join(f"- {f}" for f in fails)
                                        + f"\n\n<earlier_verdict>\n{out}\n</earlier_verdict>", verdict_schema(chk))
        left = quote_failures(again["clauses"], srcs, chk)
        if len(left) <= len(fails):
            out, fails = again, left
    read = [{"slug": p["slug"], "version": p.get("version")} for p in pages]
    async with get_pool().connection() as conn:
        row = await (await conn.execute(
            """insert into wiki.findings (wiki_id, statement, verdict, clauses, reasoning, check_failures, sources, pages_read)
               values (%s, %s, %s, %s, %s, %s, %s, %s) returning id, status, created_at""",
            (wiki["id"], statement, out["verdict"], Jsonb(out["clauses"]), out["reasoning"], Jsonb(fails), sources, Jsonb(read)))).fetchone()
    return {"finding_id": str(row["id"]), "status": row["status"], "verdict": out["verdict"], "clauses": out["clauses"],
            "reasoning": out["reasoning"], "checks": {"found": found, "left": fails}, "pages": read,
            "rounds": rounds}


async def findings(wiki_id: UUID, status: str | None = None) -> list[dict]:
    async with get_pool().connection() as conn:
        return await (await conn.execute(
            "select * from wiki.findings where wiki_id = %s and (%s::text is null or status = %s) order by created_at desc",
            (wiki_id, status, status))).fetchall()


async def review(wiki_id: UUID, finding_id: UUID, reviewer: str, decision: str, note: str = "") -> dict:
    """Close a finding: only a named reviewer does, and their name, decision and note are recorded with it."""
    if not reviewer.strip() or not decision.strip():
        raise ValueError("A finding is closed only by a named reviewer, with their decision.")
    async with get_pool().connection() as conn:
        row = await (await conn.execute(
            """update wiki.findings set status = 'closed', reviewer = %s, decision = %s, note = %s, reviewed_at = now()
               where id = %s and wiki_id = %s and status = 'open' returning *""",
            (reviewer.strip(), decision.strip(), note, finding_id, wiki_id))).fetchone()
    if not row:
        raise LookupError("No open finding with that id in this wiki.")
    return row
