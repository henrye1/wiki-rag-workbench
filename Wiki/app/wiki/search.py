from uuid import UUID

import numpy as np

from .. import llm
from ..db import get_pool


async def search_pages(wiki_id: UUID, query: str, k: int, embedding: list[float] | None = None) -> list[dict]:
    if embedding is None:
        embedding = await llm.embed_query(query)
    async with get_pool().connection() as conn:
        cur = await conn.execute(
            "select * from wiki.search_pages(%s, %s, %s, %s)",
            (wiki_id, query, np.asarray(embedding, dtype=np.float32), k),
        )
        return await cur.fetchall()


async def shortlist(wiki_id: UUID, query: str, k: int) -> list[dict]:
    """The pages whose text matches the query by its labels and numbers (as written), its words or its meaning, best
    first: each with its score, its best label, keyword and meaning ranks (None where it did not match that way) and
    the passage that matched."""
    embedding = await llm.embed_query(query)
    async with get_pool().connection() as conn:
        cur = await conn.execute(
            "select * from wiki.shortlist_pages(%s, %s, %s, %s)",
            (wiki_id, query, np.asarray(embedding, dtype=np.float32), k),
        )
        return await cur.fetchall()


async def search_many(wiki_id: UUID, queries: list[str], k: int) -> list[dict]:
    """Run several queries, merge by best score per page."""
    queries = [q for q in queries if q.strip()]
    if not queries:
        return []
    embeddings = await llm.embed(queries, task="RETRIEVAL_QUERY")
    best: dict[str, dict] = {}
    for q, e in zip(queries, embeddings):
        for r in await search_pages(wiki_id, q, k, e):
            if r["slug"] not in best or r["score"] > best[r["slug"]]["score"]:
                best[r["slug"]] = r
    return sorted(best.values(), key=lambda r: -r["score"])
