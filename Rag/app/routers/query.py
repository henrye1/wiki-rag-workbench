import json
import re
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .. import llm, prompts, retrieval
from ..bulk import QUESTION_RE
from ..config import get_settings
from ..ingest.models import NON_BINDING_TYPES, STANDARD_TYPES
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
               where k.para_ref is not null and k.source_type <> all(%s::text[])
                 and (%s::text[] is null or d.filename = any(%s::text[]))
               order by k.embedding <=> %s limit %s""",
            (emb, list(NON_BINDING_TYPES), body.filenames, body.filenames, emb, body.k * 4))).fetchall()
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
    include_editorial: bool = Field(False, description="Include notes/intro/Appendix C (excluded by default)")
    sources: Literal["standard", "all"] = Field(
        "all", description="standard = only the Standard itself (Part A); all = also documents published with it (Parts B and C)")
    retrieval: Literal["whole", "per_question"] = Field(
        "whole", description="whole = one search for the whole question (top_k passages, a setting); per_question = when the "
        "question lists numbered questions (Q1. ..., Q2. ...), one search for its first line and one per question, as the "
        "bulk run searches (bulk_k_per_query each, up to bulk_max_chunks), answered with the same prompt")
    instructions: str | None = Field(None, max_length=40000, description="The chat's skills: added to the answer "
                                     "instruction (never to what is searched); none by default")


def _queries(question: str) -> list[str]:
    """The searches of a per-question retrieval: the question's first line, then each numbered question; the whole
    question when it lists none."""
    qs = QUESTION_RE.findall(question)
    return [question.strip().splitlines()[0]] + qs if qs else [question]


async def _retrieve(q: QueryIn, col: dict) -> list[dict]:
    s = get_settings()
    types = list(STANDARD_TYPES) if q.sources == "standard" else None  # Part A only, whatever else the collection holds
    if q.retrieval == "per_question":
        return await retrieval.search_each(_queries(q.question), s.bulk_k_per_query, s.bulk_max_chunks, types,
                                           q.include_editorial, collection_id=col["id"])
    return await retrieval.search(q.question, s.top_k, types, q.include_editorial, collection_id=col["id"])


def _prompt(q: QueryIn, rows: list[dict]) -> str:
    """What the model is given, the same for the answer and its stream."""
    return prompts.query_prompt(q.question, retrieval.format_context(rows))


def _system(q: QueryIn) -> str:
    return prompts.with_skills(prompts.QUERY_SYSTEM, q.instructions)


NOTHING = "No relevant passages found."


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
        return {"answer": NOTHING, "citations": [], "read": [], "usage": usage}
    answer = await llm.generate(_system(q), _prompt(q, rows))
    return {"answer": answer, "citations": _cited(answer, rows), "read": read, "usage": usage}


@router.post("/collections/{c}/query/stream")
async def query_stream(q: QueryIn, col: dict = Depends(collection_dep)):
    rows = await _retrieve(q, col)

    async def events():
        if not rows:
            yield {"event": "token", "data": json.dumps(NOTHING)}
            yield {"event": "citations", "data": "[]"}
            yield {"event": "done", "data": ""}
            return
        parts = []
        async for t in llm.stream(_system(q), _prompt(q, rows)):
            parts.append(t)
            yield {"event": "token", "data": json.dumps(t)}
        yield {"event": "citations", "data": json.dumps(_cited("".join(parts), rows))}
        yield {"event": "done", "data": ""}

    return EventSourceResponse(events())
