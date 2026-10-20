import json
import re
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .. import llm, prompts, retrieval
from ..config import get_settings
from ..ingest.models import ALL_TYPES, STANDARD_TYPES
from .collections import collection_dep

router = APIRouter(tags=["query"])
CITE_RE = re.compile(r"\[([^\[\]]+)\]")


class ParagraphSearchIn(BaseModel):
    text: str = Field(min_length=3)
    k: int = Field(8, ge=1, le=30)
    filenames: list[str] | None = Field(None, description="Only these source files (e.g. '13 - IFRS 9 Financial Instruments.pdf')")


@router.post("/search/paragraphs")
async def search_paragraphs(body: ParagraphSearchIn):
    """The paragraphs closest in meaning to a text, by the stored passage embeddings (any collection; each file's
    paragraph once). No answer is generated; editorial notes and introductions are left out. Used by the benchmark's
    rubric tag check."""
    import numpy as np
    from ..db import get_pool
    emb = np.asarray(await llm.embed_query(body.text), dtype=np.float32)
    async with get_pool().connection() as conn:
        rows = await (await conn.execute(
            """select d.filename, k.para_ref, k.source_type, k.embedding <=> %s as distance
               from chunks k join documents d on d.id = k.document_id
               where k.para_ref is not null and k.source_type not in ('note', 'intro', 'back_matter', 'appendix_c')
                 and (%s::text[] is null or d.filename = any(%s::text[]))
               order by k.embedding <=> %s limit %s""",
            (emb, body.filenames, body.filenames, emb, body.k * 4))).fetchall()
    out, seen = [], set()
    for r in rows:
        key = (r["filename"], r["para_ref"])
        if key not in seen:
            seen.add(key)
            out.append({"filename": r["filename"], "para_ref": r["para_ref"], "source_type": r["source_type"],
                        "similarity": round(1 - float(r["distance"]), 4)})
        if len(out) >= body.k:
            break
    return out


class QueryIn(BaseModel):
    question: str = Field(min_length=3)
    top_k: int | None = Field(None, ge=1, le=50)
    source_types: list[str] | None = Field(None, description=f"Restrict to these types: {', '.join(ALL_TYPES)}")
    include_editorial: bool = Field(False, description="Include notes/intro/Appendix C (excluded by default)")
    sources: Literal["standard", "all"] = Field(
        "all", description="standard = only the Standard itself (Part A); all = also documents published with it (Parts B and C)")


async def _retrieve(q: QueryIn, col: dict) -> list[dict]:
    types = q.source_types
    if q.sources == "standard":  # Part A only, whatever else the collection holds
        types = [t for t in (types or STANDARD_TYPES) if t in STANDARD_TYPES]
    return await retrieval.search(q.question, q.top_k or get_settings().top_k, types, q.include_editorial,
                                  collection_id=col["id"])


def _cited(answer: str, rows: list[dict]) -> list[dict]:
    refs = {x.strip() for m in CITE_RE.findall(answer) for x in m.split(",")}
    hit = [r for r in rows if r["para_ref"] in refs or retrieval.chunk_id(r) in refs]
    return [retrieval.citation(r) for r in (hit or rows)]


@router.post("/collections/{c}/query")
async def query(q: QueryIn, col: dict = Depends(collection_dep)):
    """Answer from the passages of one collection. `read` lists every passage given to the model (after the Sources
    setting); `usage` lists the AI calls made for it, with their tokens."""
    usage = llm.track_usage()
    rows = await _retrieve(q, col)
    read = [{"chunk_id": retrieval.chunk_id(r), "para_ref": r["para_ref"], "source_type": r["source_type"], "page": r["page"],
             "document_id": str(r["document_id"]), "content": r["content"]} for r in rows]
    if not rows:
        return {"answer": "No relevant passages found.", "citations": [], "read": [], "usage": usage}
    answer = await llm.generate(prompts.QUERY_SYSTEM, prompts.query_prompt(q.question, retrieval.format_context(rows)))
    return {"answer": answer, "citations": _cited(answer, rows), "read": read, "usage": usage}


@router.post("/collections/{c}/query/stream")
async def query_stream(q: QueryIn, col: dict = Depends(collection_dep)):
    rows = await _retrieve(q, col)

    async def events():
        if not rows:
            yield {"event": "token", "data": json.dumps("No relevant passages found.")}
            yield {"event": "citations", "data": "[]"}
            yield {"event": "done", "data": ""}
            return
        parts = []
        async for t in llm.stream(prompts.QUERY_SYSTEM, prompts.query_prompt(q.question, retrieval.format_context(rows))):
            parts.append(t)
            yield {"event": "token", "data": json.dumps(t)}
        yield {"event": "citations", "data": json.dumps(_cited("".join(parts), rows))}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(events())
