import json
import re

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .. import llm, prompts, retrieval
from ..config import get_settings
from ..ingest.models import ALL_TYPES

router = APIRouter(tags=["query"])
CITE_RE = re.compile(r"\[([^\[\]]+)\]")


class QueryIn(BaseModel):
    question: str = Field(min_length=3)
    top_k: int | None = Field(None, ge=1, le=50)
    source_types: list[str] | None = Field(None, description=f"Restrict to these types: {', '.join(ALL_TYPES)}")
    include_editorial: bool = Field(False, description="Include notes/intro/Appendix C (excluded by default)")


async def _retrieve(q: QueryIn) -> list[dict]:
    return await retrieval.search(q.question, q.top_k or get_settings().top_k, q.source_types, q.include_editorial)


def _cited(answer: str, rows: list[dict]) -> list[dict]:
    refs = {x.strip() for m in CITE_RE.findall(answer) for x in m.split(",")}
    hit = [r for r in rows if r["para_ref"] in refs or retrieval.chunk_id(r) in refs]
    return [retrieval.citation(r) for r in (hit or rows)]


@router.post("/query")
async def query(q: QueryIn):
    rows = await _retrieve(q)
    if not rows:
        return {"answer": "No relevant passages found.", "citations": []}
    answer = await llm.generate(prompts.QUERY_SYSTEM, prompts.query_prompt(q.question, retrieval.format_context(rows)))
    return {"answer": answer, "citations": _cited(answer, rows)}


@router.post("/query/stream")
async def query_stream(q: QueryIn):
    rows = await _retrieve(q)

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
