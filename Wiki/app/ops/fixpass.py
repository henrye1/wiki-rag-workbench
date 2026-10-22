"""The check-and-fix pass shared by ingest and re-check: check a page, send it back with the list of failures (at most
twice), keep a rewrite only when it is better. The words the checks look for come from the schema (wiki/checks.py)."""
import logging
import re
from uuid import UUID

from .. import llm, prompts
from ..db import get_pool
from ..wiki import checks, citecheck

log = logging.getLogger(__name__)
LABEL_RE = re.compile(r"^\[([^\]\n]+)\]", re.M)


async def cite_context(wiki_id: UUID, section_names: list[str]) -> dict:
    """What the citation checks compare against: each source's paragraph labels, and the wiki's own source and section
    names (a citation naming one of those cites no clause)."""
    async with get_pool().connection() as conn:
        rows = await (await conn.execute("select slug, title, text, meta from wiki.sources where wiki_id = %s", (wiki_id,))).fetchall()
    names = set(section_names)
    for r in rows:
        names.add(r["title"])
        names.update(v for v in ((r["meta"] or {}).get("document") or {}).values() if v)
    return {"matchers": {r["slug"]: m for r in rows if (m := citecheck._matcher(r["text"]))},
            "labels": {r["slug"]: set(LABEL_RE.findall(r["text"] or "")) for r in rows},
            "names": names}


def cite_failures(text: str, ctx: dict, chk: checks.Checks | None) -> list[str]:
    """Citations the citation check would flag, and citations that cite something other than a clause."""
    _, _, flagged = citecheck.check(text, ctx["matchers"])
    out = [f'The citation [[{src}|{label}]] does not match a paragraph of that source ({reason}); cite the paragraph '
           "it states, by its own label." for (src, label, reason) in flagged]
    return out + checks.citation_failures(text, ctx["labels"], ctx["names"], chk)


async def fix_rounds(*, schema: str, slug: str, title: str, text: str, check, sources_text: str, linkable: str, parse,
                     kind: str, record: list, out_schema=prompts.PAGE_SCHEMA, ok=lambda old, new: True,
                     may_shrink: bool = False) -> str:
    """Check the page; if anything fails, send it back with the list, at most twice. A rewrite is kept only if it has
    fewer failures, loses no citation, stays about the same length (a fix changes what was listed, not the whole page;
    may_shrink when a failure asks for something to be taken out) and passes ok."""
    rounds = []
    for rnd in (1, 2):
        failures = check(text)
        if not failures:
            break
        rec = {"round": rnd, "failures": failures}
        try:
            out = await llm.generate_json(prompts.MAINTAINER_SYSTEM, prompts.with_schema(schema, prompts.fix_page_prompt(
                slug=slug, title=title, content_md=text or "(nothing yet)", failures=failures, linkable=linkable,
                source_paragraphs=sources_text or "(none)")), out_schema)
            new = parse(out["content_md"])
            after = check(new)
            lost = [] if may_shrink else sorted(checks.cites(text) - checks.cites(new))
            n_old, n_new = len(text.split()), len(new.split())
            keep = (bool(new.strip()) and len(after) < len(failures) and not lost and ok(text, new)
                    and n_new <= 1.5 * n_old + 200 and (may_shrink or n_new >= 0.8 * n_old))
            rec |= {"kept": keep, "fixed": len(failures) - len(after) if keep else 0, "still": after, "words": [n_old, n_new],
                    **({"lost_citations": lost} if lost else {})}
            if keep:
                text = new
            log.info("page %s %s check, round %s: %s failures, %s fixed, rewrite %s", slug, kind, rnd,
                     len(failures), len(failures) - len(after), "kept" if keep else "discarded")
        except Exception as e:
            log.warning("page %s %s check, round %s failed: %s", slug, kind, rnd, e)
            rec["error"] = f"{type(e).__name__}: {e}"
        rounds.append(rec)
    if rounds:
        record.append({"page": slug, "kind": kind, "found": len(rounds[0]["failures"]), "still": len(check(text)),
                       "rounds": rounds})
    return text
