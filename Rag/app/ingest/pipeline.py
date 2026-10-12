import hashlib

import numpy as np
import pymupdf
from psycopg.types.json import Jsonb

from .. import llm, storage
from ..config import get_settings
from ..db import get_pool
from . import pdf_ifrs
from .models import Chunk
from .text import chunk_plain


class DuplicateDocument(Exception):
    def __init__(self, doc_id):
        self.doc_id = doc_id


def parse_file(filename: str, data: bytes) -> tuple[str, list[Chunk]]:
    max_words = get_settings().chunk_max_words
    if filename.lower().endswith(".pdf"):
        doc = pymupdf.open(stream=data, filetype="pdf")
        if pdf_ifrs.looks_like_ifrs(doc):
            return "ifrs", pdf_ifrs.parse(doc, max_words)
        return "generic_pdf", chunk_plain([p.get_text() for p in doc], max_words)
    return "text", chunk_plain([data.decode("utf-8", errors="replace")], max_words)


async def ingest(filename: str, data: bytes) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    pool = get_pool()
    async with pool.connection() as conn:
        row = await (await conn.execute("select id from documents where sha256 = %s", (sha,))).fetchone()
    if row:
        raise DuplicateDocument(row["id"])

    parser, chunks = parse_file(filename, data)
    if not chunks:
        raise ValueError("No text extracted from document")
    vectors = await llm.embed([c.embed_text() for c in chunks])

    async with pool.connection() as conn, conn.transaction():
        doc = await (
            await conn.execute(
                "insert into documents (filename, sha256, parser) values (%s, %s, %s) returning id", (filename, sha, parser)
            )
        ).fetchone()
        async with conn.cursor() as cur:
            await cur.executemany(
                """insert into chunks (document_id, para_ref, part, source_type, page, heading, content, embedding)
                   values (%s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (doc["id"], c.para_ref, c.part, c.source_type, c.page, c.heading, c.content, np.asarray(v, dtype=np.float32))
                    for c, v in zip(chunks, vectors)
                ],
            )
    # Keep the original upload so it can be viewed later (skipped when storage is not configured)
    rec = await storage.put(storage.object_path("rag", str(doc["id"]), filename), data, storage.content_type(filename))
    if rec:
        async with pool.connection() as conn:
            await conn.execute("update documents set file = %s where id = %s", (Jsonb(rec), doc["id"]))
    counts: dict[str, int] = {}
    for c in chunks:
        counts[c.source_type] = counts.get(c.source_type, 0) + 1
    return {"document_id": str(doc["id"]), "filename": filename, "parser": parser, "chunks": len(chunks), "by_source_type": counts}
