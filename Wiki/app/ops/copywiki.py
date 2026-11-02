"""Copy a wiki under a new slug: its settings and schema, sources, pages with every version, links, flags and search
index (the stored embeddings, so nothing is embedded again). The copy's sources share their originals' stored files.
Its log, jobs and changesets start empty: the log records the copy. No AI call is made."""
from psycopg import sql

from ..db import get_pool
from ..wiki import store

# table -> (columns set to a new value, the join that maps old ids to the copy's, the filter on the original)
TABLES = {
    "sources": ({"id": "sm.new", "wiki_id": "%(new)s"}, "join smap sm on sm.old = t.id", "t.wiki_id = %(old)s"),
    "pages": ({"id": "pm.new", "wiki_id": "%(new)s"}, "join pmap pm on pm.old = t.id", "t.wiki_id = %(old)s"),
    "page_versions": ({"page_id": "pm.new"}, "join pmap pm on pm.old = t.page_id", "true"),
    "links": ({"wiki_id": "%(new)s", "from_page_id": "pm.new"}, "join pmap pm on pm.old = t.from_page_id", "true"),
    "page_sources": ({"page_id": "pm.new", "source_id": "sm.new"},
                     "join pmap pm on pm.old = t.page_id join smap sm on sm.old = t.source_id", "true"),
    "page_chunks": ({"wiki_id": "%(new)s", "page_id": "pm.new"}, "join pmap pm on pm.old = t.page_id", "true"),
    "page_flags": ({"page_id": "pm.new"}, "join pmap pm on pm.old = t.page_id", "true"),
}


async def _columns(conn, table: str) -> list[str]:
    """The columns a copy writes: every column but generated and identity ones."""
    rows = await (await conn.execute(
        """select column_name from information_schema.columns where table_schema = 'wiki' and table_name = %s
           and is_generated = 'NEVER' and is_identity = 'NO' order by ordinal_position""", (table,))).fetchall()
    return [r["column_name"] for r in rows]


async def copy(wiki: dict, slug: str, name: str, description: str | None = None) -> dict:
    """The new wiki, with how many rows of each kind were copied. Raises psycopg's UniqueViolation if slug is taken."""
    async with get_pool().connection() as conn, conn.transaction():
        keep = [c for c in await _columns(conn, "wikis") if c not in ("id", "slug", "name", "description", "created_at")]
        new = await (await conn.execute(
            sql.SQL("insert into wiki.wikis (slug, name, description, {cols}) select %s, %s, %s, {cols} "
                    "from wiki.wikis where id = %s returning *").format(cols=sql.SQL(", ").join(map(sql.Identifier, keep))),
            (slug, name, wiki["description"] if description is None else description, wiki["id"]))).fetchone()
        ids = {"old": wiki["id"], "new": new["id"]}
        await conn.execute("create temp table pmap (old uuid primary key, new uuid not null) on commit drop")
        await conn.execute("create temp table smap (old uuid primary key, new uuid not null) on commit drop")
        await conn.execute("insert into pmap select id, gen_random_uuid() from wiki.pages where wiki_id = %(old)s", ids)
        await conn.execute("insert into smap select id, gen_random_uuid() from wiki.sources where wiki_id = %(old)s", ids)
        counts = {}
        for table, (set_to, join, where) in TABLES.items():
            cols = await _columns(conn, table)
            picked = sql.SQL(", ").join(sql.SQL(set_to[c]) if c in set_to else sql.SQL("t.{}").format(sql.Identifier(c)) for c in cols)
            cur = await conn.execute(
                sql.SQL("insert into wiki.{tbl} ({cols}) select {picked} from wiki.{tbl} t {join} where {where}").format(
                    tbl=sql.Identifier(table), cols=sql.SQL(", ").join(map(sql.Identifier, cols)), picked=picked,
                    join=sql.SQL(join), where=sql.SQL(where)), ids)
            counts[table] = cur.rowcount
        await store.add_log(new["id"], "edit", f"Wiki copied from {wiki['slug']}",
                            "\n".join(f"- {t.replace('_', ' ')}: {n}" for t, n in counts.items()), conn=conn)
    return {**new, "copied": counts}
