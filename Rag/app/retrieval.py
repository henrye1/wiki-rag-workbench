import numpy as np

from . import llm
from .db import get_pool
from .ingest.models import NON_BINDING_TYPES

SOURCE_LABELS = {
    "standard": "Standard",
    "appendix_a": "Appendix A (defined term)",
    "appendix_b": "Application Guidance",
    "general": "Document",
    "note": "Editorial note",
    "intro": "Introduction",
    "appendix_c": "Appendix C",
    "back_matter": "Back matter",
}


async def search(
    query: str,
    k: int,
    include_types: list[str] | None = None,
    include_editorial: bool = False,
    embedding: list[float] | None = None,
    collection_id=None,
) -> list[dict]:
    """Hybrid search over one collection (all collections when collection_id is None)."""
    if embedding is None:
        embedding = await llm.embed_query(query)
    exclude = None if (include_editorial or include_types) else list(NON_BINDING_TYPES)
    async with get_pool().connection() as conn:
        cur = await conn.execute(
            "select * from hybrid_search(%s, %s, %s, %s, %s, p_collection_id => %s)",
            (query, np.asarray(embedding, dtype=np.float32), k, include_types, exclude, collection_id),
        )
        return await cur.fetchall()


def chunk_id(row: dict) -> str:
    return f"C{row['id']}"


def cite_key(row: dict) -> str:
    return row["para_ref"] or chunk_id(row)


def format_context(rows: list[dict], with_ids: bool = False) -> str:
    blocks = []
    for r in rows:
        kind = SOURCE_LABELS.get(r["source_type"], r["source_type"])
        ids = f" | passage id {chunk_id(r)}" if with_ids else ""
        blocks.append(f"[{cite_key(r)}] ({kind}, page {r['page']}{ids})\n{r['content']}")
    return "\n\n---\n\n".join(blocks)


def citation(row: dict) -> dict:
    return {
        "chunk_id": chunk_id(row),
        "para_ref": row["para_ref"],
        "source_type": row["source_type"],
        "page": row["page"],
        "heading": row["heading"],
        "snippet": row["content"][:300],
        "score": round(float(row.get("score") or 0), 5),
    }
