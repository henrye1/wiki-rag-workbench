"""Stale-claim check (Checks: Newer version): when an upload is a newer version of an earlier source, the pages that cite
a paragraph of the earlier source whose text the newer one changes or no longer holds, with the old and new wording.
A report only: it reads the sources and pages and changes nothing; no model call. Off when the schema has no Newer
version list."""
import re
from uuid import UUID

from ..db import get_pool
from ..wiki import checks, store

LABELLED = re.compile(r"^\[([^\]]+)\]\s*")  # a paragraph's own label, as the reader stores it: "[<label>] <text>"


def by_label(text: str) -> dict[str, str]:
    """label -> the paragraph's text (without its label), passages sharing a label joined, as the page checks read a
    source (pagecheck.sources)."""
    out: dict[str, list[str]] = {}
    for b in (b.strip() for b in re.split(r"\n\s*\n", text or "")):
        if m := LABELLED.match(b):
            out.setdefault(m.group(1).strip(), []).append(b[m.end():].strip())
    return {k: "\n\n".join(v) for k, v in out.items()}


def _details(meta: dict | None) -> dict[str, str]:
    return {k.casefold(): " ".join(str(v).split()).casefold() for k, v in ((meta or {}).get("document") or {}).items() if v}


def earlier_version(new_meta: dict | None, others: list[dict], rule: dict) -> dict | None:
    """The most recent other source with the same document details as the new one (rule["same"]), or None. others:
    [{slug, title, meta, sha256, created_at}]; with rule["given"], a detail must be given on both."""
    mine = _details(new_meta)
    if rule.get("given") and not all(mine.get(k) for k in rule["same"]):
        return None
    fits = [o for o in others if all(_details(o.get("meta")).get(k, "") == mine.get(k, "") for k in rule["same"])
            and (not rule.get("given") or all(_details(o.get("meta")).get(k) for k in rule["same"]))]
    return max(fits, key=lambda o: o["created_at"]) if fits else None


def compare(old: dict[str, str], new: dict[str, str], pages: list[dict], old_slug: str, spacing: bool) -> dict:
    """The earlier source's paragraphs the newer one changes or no longer holds, and each page citing one of them."""
    same = (lambda a, b: " ".join(a.split()) == " ".join(b.split())) if spacing else (lambda a, b: a == b)
    gone = {lab: {"label": lab, "status": "removed", "old": txt, "new": None} for lab, txt in old.items() if lab not in new}
    changed = {lab: {"label": lab, "status": "changed", "old": txt, "new": new[lab]} for lab, txt in old.items()
               if lab in new and not same(txt, new[lab])}
    stale = {**changed, **gone}
    hits = []
    for p in pages:
        labs = sorted({c.split("|", 1)[1] for c in checks.cites(p.get("content_md") or "") if c.split("|", 1)[0] == old_slug}
                      & set(stale), key=_order(list(old)))
        if labs:
            hits.append({"slug": p["slug"], "title": p.get("title"), "paragraphs": [stale[x] for x in labs]})
    return {"changed": len(changed), "removed": len(gone), "pages": sorted(hits, key=lambda h: h["slug"])}


def _order(labels: list[str]):
    at = {x: i for i, x in enumerate(labels)}
    return lambda x: at.get(x, len(at))


async def report(wiki_id: UUID, source: dict, text: str, meta: dict | None, chk: checks.Checks | None) -> dict | None:
    """For an upload: the earlier version it replaces and the pages citing what changed, or None where the schema has
    no Newer version list or the upload is no newer version of a source of the wiki."""
    rule = chk.newer_version if chk else {}
    if not rule:
        return None
    async with get_pool().connection() as conn:
        others = await (await conn.execute(
            "select slug, title, meta, created_at from wiki.sources where wiki_id = %s and id <> %s",
            (wiki_id, source["id"]))).fetchall()
        earlier = earlier_version(meta, others, rule)
        if not earlier:
            return None
        old_text = (await (await conn.execute("select text from wiki.sources where wiki_id = %s and slug = %s",
                                              (wiki_id, earlier["slug"]))).fetchone())["text"]
    pages = await store.list_pages(wiki_id, with_content=True)
    out = compare(by_label(old_text), by_label(text), pages, earlier["slug"], rule.get("spacing", False))
    return {"earlier": {"slug": earlier["slug"], "title": earlier["title"]}, "same": rule["same"], **out}
