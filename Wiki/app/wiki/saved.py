"""Saved answers: synthesis pages filed with the Save button.

They are read when answering in addition to the pages chosen for the question (never instead of one), never used as
source material by uploads, and flagged "needs checking" when a later change rewrites what the wiki says about a
paragraph they cite.
"""
import re
from uuid import UUID

from psycopg.types.json import Jsonb

SAVED_TAG = "saved-answer"
# Saved with the Save button: tagged when saved; older ones are recognised by how they were filed
SAVED_SQL = (
    f"p.type = 'synthesis' and ('{SAVED_TAG}' = any(p.tags) or exists (select 1 from wiki.page_versions v "
    "where v.page_id = p.id and v.version = 1 and v.change_note like 'Filed from query%%'))"
)
CITE_RE = re.compile(r"\[\[(source-[^\]|#]+)(?:#[^\]|]*)?\|([^\]]+)\]\]")


async def saved_answers(conn, wiki_id: UUID, readable_only: bool = False) -> list[dict]:
    """Saved answers; readable_only leaves out those saved with citation problems (not read until saved again cleanly)."""
    blocked = (" and not exists (select 1 from wiki.page_flags f where f.page_id = p.id and f.kind = 'citation_problems')"
               if readable_only else "")
    return await (
        await conn.execute(
            f"select p.id, p.slug, p.title, p.summary, p.type, p.content_md, p.updated_at from wiki.pages p "
            f"where p.wiki_id = %s and {SAVED_SQL}{blocked} order by p.updated_at desc",
            (wiki_id,),
        )
    ).fetchall()


async def set_citation_problems(conn, page_id, problems: list[dict]) -> None:
    """A synthesis saved with citation problems is flagged and not read; saving it again without problems clears it."""
    if not problems:
        await conn.execute("delete from wiki.page_flags where page_id = %s and kind = 'citation_problems'", (page_id,))
        return
    detail = {"why": f"saved with {len(problems)} citation problem(s)", "paragraphs": [x["link"] for x in problems][:50],
              "pages": [], "problems": problems[:50]}
    await conn.execute(
        """insert into wiki.page_flags (page_id, kind, detail) values (%s, 'citation_problems', %s)
           on conflict (page_id, kind) do update set detail = excluded.detail, updated_at = now()""",
        (page_id, Jsonb(detail)),
    )


def _statements(md: str) -> dict[tuple[str, str], set[str]]:
    """For each cited paragraph (source, label), the statements the page makes with that citation."""
    out: dict[tuple[str, str], set[str]] = {}
    pos = 0
    for m in CITE_RE.finditer(md or ""):
        text = md[pos : m.start()]
        pos = m.end()
        sentence = re.split(r"(?<=[.;:!?])\s+|\n", text.strip())[-1] if text.strip() else ""
        sentence = " ".join(re.sub(r"\[\[[^\]]*\]\]", "", sentence).split()).strip(" ,;")
        out.setdefault((m.group(1), m.group(2).strip()), set()).add(sentence)
    return out


def changed_clauses(old_md: str, new_md: str) -> set[tuple[str, str]]:
    """Paragraphs whose write-up on a page changed: a statement citing them was added, removed or reworded."""
    a, b = _statements(old_md), _statements(new_md)
    return {k for k in set(a) | set(b) if a.get(k, set()) != b.get(k, set())}


def _cites(md: str, clauses: set[tuple[str, str]]) -> list[str]:
    """The clauses of `clauses` that a page cites (same source, same paragraph label)."""
    mine = {(m.group(1), m.group(2).strip()) for m in CITE_RE.finditer(md or "")}
    return sorted(f"{s}|{lab}" for s, lab in mine & clauses)


async def flag_changed(conn, wiki_id: UUID, changes: dict[str, set[tuple[str, str]]], why: str) -> list[dict]:
    """Flag saved answers citing a paragraph whose write-up changed. changes: page slug -> its changed clauses."""
    allc = set().union(*changes.values()) if changes else set()
    if not allc:
        return []
    flagged = []
    for p in await saved_answers(conn, wiki_id):
        hit = _cites(p["content_md"], allc)
        if not hit:
            continue
        pages = sorted(s for s, c in changes.items() if _cites(p["content_md"], c))
        detail = {"why": why, "paragraphs": hit[:50], "pages": pages}
        await conn.execute(
            """insert into wiki.page_flags (page_id, kind, detail) values (%s, 'needs_checking', %s)
               on conflict (page_id, kind) do update set detail = excluded.detail, updated_at = now()""",
            (p["id"], Jsonb(detail)),
        )
        flagged.append({"slug": p["slug"], **detail})
    return flagged


async def flags(conn, wiki_id: UUID) -> dict[str, dict]:
    """Pages that need checking: saved with citation problems (shown first; not read) or a cited paragraph rewritten."""
    rows = await (
        await conn.execute(
            """select p.slug, f.kind, f.detail, f.updated_at from wiki.page_flags f join wiki.pages p on p.id = f.page_id
               where p.wiki_id = %s and f.kind in ('needs_checking', 'citation_problems')
               order by (f.kind = 'citation_problems')""",
            (wiki_id,),
        )
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:  # citation problems come last, so they win; the other flag is kept alongside
        entry = {**r["detail"], "kind": r["kind"], "since": r["updated_at"].isoformat(timespec="seconds")}
        out[r["slug"]] = {**entry, "also": out[r["slug"]]} if r["slug"] in out else entry
    return out
