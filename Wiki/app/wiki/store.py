"""Wiki persistence: pages + versions, links, search chunks, changesets, index/log rendering."""
import re
from dataclasses import dataclass, field
from uuid import UUID

import numpy as np

from .. import llm, storage
from ..config import get_settings
from ..db import get_pool
from ..sources.text import split_long

PAGE_TYPES = ("overview", "topic", "concept", "entity", "comparison", "synthesis", "source")
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")


class NotFound(Exception):
    pass


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:80] or "page"


def extract_links(md: str) -> set[str]:
    return {slugify(m.group(1)) for m in LINK_RE.finditer(md)}


# ---------- wikis ----------

async def get_wiki(slug: str) -> dict:
    async with get_pool().connection() as conn:
        row = await (await conn.execute("select * from wiki.wikis where slug = %s", (slug,))).fetchone()
    if not row:
        raise NotFound(f"Wiki '{slug}' not found")
    return row


async def add_log(wiki_id: UUID, kind: str, title: str, detail: str = "", conn=None):
    sql = "insert into wiki.log (wiki_id, kind, title, detail_md) values (%s, %s, %s, %s)"
    if conn is not None:
        await conn.execute(sql, (wiki_id, kind, title, detail))
        return
    async with get_pool().connection() as c:
        await c.execute(sql, (wiki_id, kind, title, detail))


# ---------- pages ----------

async def get_page(wiki_id: UUID, slug: str) -> dict | None:
    async with get_pool().connection() as conn:
        return await (
            await conn.execute("select * from wiki.pages where wiki_id = %s and slug = %s", (wiki_id, slug))
        ).fetchone()


async def get_pages(wiki_id: UUID, slugs: list[str]) -> list[dict]:
    if not slugs:
        return []
    async with get_pool().connection() as conn:
        return await (
            await conn.execute("select * from wiki.pages where wiki_id = %s and slug = any(%s)", (wiki_id, list(slugs)))
        ).fetchall()


async def list_pages(wiki_id: UUID, with_content: bool = False) -> list[dict]:
    cols = "*" if with_content else "id, slug, title, type, summary, tags, version, updated_at"
    async with get_pool().connection() as conn:
        return await (
            await conn.execute(f"select {cols} from wiki.pages where wiki_id = %s order by type, slug", (wiki_id,))
        ).fetchall()


async def backlinks(wiki_id: UUID, slug: str) -> list[dict]:
    async with get_pool().connection() as conn:
        return await (
            await conn.execute(
                """select p.slug, p.title from wiki.links l join wiki.pages p on p.id = l.from_page_id
                   where l.wiki_id = %s and l.to_slug = %s order by p.title""",
                (wiki_id, slug),
            )
        ).fetchall()


async def page_sources(page_id: UUID) -> list[dict]:
    async with get_pool().connection() as conn:
        return await (
            await conn.execute(
                """select s.slug, s.title, s.kind, s.uri from wiki.page_sources ps join wiki.sources s on s.id = ps.source_id
                   where ps.page_id = %s order by s.created_at""",
                (page_id,),
            )
        ).fetchall()


def _chunks(title: str, summary: str, md: str) -> list[str]:
    max_words = get_settings().chunk_max_words
    sections = re.split(r"\n(?=#{1,3} )", md)
    out = []
    for sec in sections:
        for part in split_long(sec.strip(), max_words):
            if part:
                out.append(f"{title}\n{part}")
    return out or [f"{title}\n{summary}"]


# ---------- changesets ----------

@dataclass
class Op:
    op: str  # create | update | delete
    slug: str
    title: str | None = None
    type: str | None = None
    summary: str | None = None
    content_md: str | None = None
    tags: list[str] = field(default_factory=list)
    base_version: int | None = None
    change_note: str = ""


async def create_changeset(
    wiki_id: UUID, kind: str, summary: str, ops: list[Op], job_id: UUID | None = None, source_id: UUID | None = None
) -> UUID:
    async with get_pool().connection() as conn, conn.transaction():
        cs = await (
            await conn.execute(
                "insert into wiki.changesets (wiki_id, job_id, source_id, kind, summary) values (%s,%s,%s,%s,%s) returning id",
                (wiki_id, job_id, source_id, kind, summary),
            )
        ).fetchone()
        async with conn.cursor() as cur:
            await cur.executemany(
                """insert into wiki.changeset_ops (changeset_id, op, slug, title, type, summary, content_md, tags, base_version, change_note)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                [(cs["id"], o.op, o.slug, o.title, o.type, o.summary, o.content_md, o.tags, o.base_version, o.change_note) for o in ops],
            )
    return cs["id"]


async def get_changeset(changeset_id: UUID) -> tuple[dict, list[dict]]:
    async with get_pool().connection() as conn:
        cs = await (await conn.execute("select * from wiki.changesets where id = %s", (changeset_id,))).fetchone()
        if not cs:
            raise NotFound("Changeset not found")
        ops = await (
            await conn.execute("select * from wiki.changeset_ops where changeset_id = %s order by id", (changeset_id,))
        ).fetchall()
    return cs, ops


async def apply_changeset(changeset_id: UUID, force: bool = False) -> dict:
    """Apply a pending changeset. Ops whose page changed since they were written are skipped as conflicts unless force."""
    cs, op_rows = await get_changeset(changeset_id)
    if cs["status"] != "pending":
        raise ValueError(f"Changeset is {cs['status']}")
    wiki_id = cs["wiki_id"]
    ops = [Op(**{k: r[k] for k in Op.__dataclass_fields__}) for r in op_rows]

    # Embeddings are computed before the transaction (network calls)
    to_embed = {o.slug: _chunks(o.title or o.slug, o.summary or "", o.content_md or "") for o in ops if o.op != "delete"}
    flat = [c for cs_ in to_embed.values() for c in cs_]
    vectors = await llm.embed(flat) if flat else []
    vec_iter = iter(vectors)
    embedded = {slug: [(c, next(vec_iter)) for c in chunks] for slug, chunks in to_embed.items()}

    applied, conflicts = [], []
    async with get_pool().connection() as conn, conn.transaction():
        for o in ops:
            page = await (
                await conn.execute("select * from wiki.pages where wiki_id = %s and slug = %s for update", (wiki_id, o.slug))
            ).fetchone()
            if page and not force:
                if o.op == "create":
                    conflicts.append({"slug": o.slug, "reason": f"page was created elsewhere since (now v{page['version']})"})
                    continue
                if o.base_version is not None and page["version"] != o.base_version:
                    conflicts.append({"slug": o.slug, "reason": f"page is at v{page['version']}, op written against v{o.base_version}"})
                    continue
            if o.op == "delete":
                if page:
                    await conn.execute("delete from wiki.pages where id = %s", (page["id"],))
                    applied.append({"slug": o.slug, "op": "delete"})
                continue
            ptype = o.type if o.type in PAGE_TYPES else (page["type"] if page else "concept")
            if page:
                row = await (
                    await conn.execute(
                        """update wiki.pages set title=%s, type=%s, summary=%s, content_md=%s, tags=%s,
                           version=version+1, updated_at=now() where id=%s returning id, version""",
                        (o.title or page["title"], ptype, o.summary if o.summary is not None else page["summary"],
                         o.content_md, o.tags or page["tags"], page["id"]),
                    )
                ).fetchone()
                action = "update"
            else:
                row = await (
                    await conn.execute(
                        """insert into wiki.pages (wiki_id, slug, title, type, summary, content_md, tags)
                           values (%s,%s,%s,%s,%s,%s,%s) returning id, version""",
                        (wiki_id, o.slug, o.title or o.slug, ptype, o.summary or "", o.content_md or "", o.tags),
                    )
                ).fetchone()
                action = "create"
            pid = row["id"]
            await conn.execute(
                """insert into wiki.page_versions (page_id, version, title, type, summary, content_md, tags, change_note, job_id)
                   select id, version, title, type, summary, content_md, tags, %s, %s from wiki.pages where id = %s""",
                (o.change_note, cs["job_id"], pid),
            )
            await _reindex_page(conn, wiki_id, pid, o.content_md or "", embedded[o.slug])
            if cs["source_id"]:
                await conn.execute(
                    "insert into wiki.page_sources (page_id, source_id) values (%s,%s) on conflict do nothing", (pid, cs["source_id"])
                )
            applied.append({"slug": o.slug, "op": action, "version": row["version"]})
        await conn.execute("update wiki.changesets set status='applied', applied_at=now() where id=%s", (changeset_id,))
        detail = "\n".join(f"- {a['op']} [[{a['slug']}]]" for a in applied)
        if conflicts:
            detail += "\n\nConflicts (skipped):\n" + "\n".join(f"- [[{c['slug']}]]: {c['reason']}" for c in conflicts)
        await add_log(wiki_id, "apply", cs["summary"] or f"{cs['kind']} changeset", detail, conn=conn)
    return {"changeset_id": str(changeset_id), "applied": applied, "conflicts": conflicts}


async def _reindex_page(conn, wiki_id: UUID, page_id: UUID, md: str, chunks: list[tuple[str, list[float]]]):
    await conn.execute("delete from wiki.links where from_page_id = %s", (page_id,))
    links = extract_links(md)
    if links:
        async with conn.cursor() as cur:
            await cur.executemany(
                "insert into wiki.links (wiki_id, from_page_id, to_slug) values (%s,%s,%s) on conflict do nothing",
                [(wiki_id, page_id, s) for s in links],
            )
        # Sources cited via [[source-...]] links count as page sources too
        await conn.execute(
            """insert into wiki.page_sources (page_id, source_id)
               select %s, s.id from wiki.sources s where s.wiki_id = %s and s.slug = any(%s)
               on conflict do nothing""",
            (page_id, wiki_id, [s for s in links if s.startswith("source-")]),
        )
    await conn.execute("delete from wiki.page_chunks where page_id = %s", (page_id,))
    async with conn.cursor() as cur:
        await cur.executemany(
            "insert into wiki.page_chunks (wiki_id, page_id, content, embedding) values (%s,%s,%s,%s)",
            [(wiki_id, page_id, c, np.asarray(v, dtype=np.float32)) for c, v in chunks],
        )


async def discard_changeset(changeset_id: UUID) -> str | None:
    """Discard a pending changeset. For an ingest, the source is removed too (if no page uses it) so it can be re-ingested."""
    async with get_pool().connection() as conn, conn.transaction():
        cs = await (
            await conn.execute(
                "update wiki.changesets set status='discarded' where id=%s and status='pending' returning kind, source_id",
                (changeset_id,),
            )
        ).fetchone()
        if not cs:
            raise ValueError("Changeset not found or not pending")
        if cs["kind"] == "ingest" and cs["source_id"]:
            row = await (
                await conn.execute(
                    """delete from wiki.sources s where s.id = %s
                       and not exists (select 1 from wiki.page_sources ps where ps.source_id = s.id)
                       returning slug, meta->'file' as file""",
                    (cs["source_id"],),
                )
            ).fetchone()
            if row:
                await storage.remove(row["file"])
            return row["slug"] if row else None
    return None


async def commit(wiki_id: UUID, kind: str, summary: str, ops: list[Op], mode: str,
                 job_id: UUID | None = None, source_id: UUID | None = None) -> dict:
    """Create a changeset and apply it now (auto) or leave it pending (review)."""
    if not ops:
        return {"changeset_id": None, "status": "empty"}
    cs_id = await create_changeset(wiki_id, kind, summary, ops, job_id, source_id)
    if mode == "auto":
        res = await apply_changeset(cs_id)
        return {**res, "status": "applied"}
    return {"changeset_id": str(cs_id), "status": "pending", "ops": [{"op": o.op, "slug": o.slug} for o in ops]}


# ---------- index / log ----------

async def render_index(wiki: dict) -> str:
    pages = await list_pages(wiki["id"])
    lines = [f"# {wiki['name']} — Index", ""]
    if wiki["description"]:
        lines += [wiki["description"], ""]
    for t in PAGE_TYPES:
        group = [p for p in pages if p["type"] == t]
        if not group:
            continue
        lines += [f"## {t.capitalize()} pages ({len(group)})", ""]
        lines += [f"- [[{p['slug']}|{p['title']}]] — {p['summary']}" for p in group]
        lines.append("")
    return "\n".join(lines)


async def compact_index(wiki_id: UUID, limit_chars: int = 60000) -> str:
    """Compact catalog for LLM prompts: slug | type | title | summary."""
    pages = await list_pages(wiki_id)
    out, size = [], 0
    for p in pages:
        line = f"{p['slug']} | {p['type']} | {p['title']} | {p['summary']}"
        size += len(line)
        if size > limit_chars:
            out.append(f"... ({len(pages) - len(out)} more pages not shown)")
            break
        out.append(line)
    return "\n".join(out) or "(wiki is empty)"


async def render_log(wiki: dict, limit: int = 500) -> str:
    async with get_pool().connection() as conn:
        rows = await (
            await conn.execute("select * from wiki.log where wiki_id = %s order by ts desc limit %s", (wiki["id"], limit))
        ).fetchall()
    lines = [f"# {wiki['name']} — Log", ""]
    for r in reversed(rows):
        lines.append(f"## [{r['ts']:%Y-%m-%d %H:%M}] {r['kind']} | {r['title']}")
        if r["detail_md"]:
            lines += ["", r["detail_md"]]
        lines.append("")
    return "\n".join(lines)
