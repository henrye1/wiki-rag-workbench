"""Store the original file for a document ingested before file storage existed.

  python -m app.attach_file <path/to/file>

The document is found by the file's SHA-256 (the same fingerprint used to refuse duplicate ingests),
so only the exact file that was ingested can be attached.
"""
import asyncio
import hashlib
import pathlib
import selectors
import sys

from psycopg.types.json import Jsonb

from . import storage
from .db import close_pool, get_pool, open_pool


async def main(path: str):
    if not storage.enabled():
        sys.exit("File storage is not configured: set SUPABASE_SECRET_KEY")
    f = pathlib.Path(path)
    data = f.read_bytes()
    await open_pool()
    try:
        async with get_pool().connection() as conn:
            doc = await (
                await conn.execute("select id, filename from documents where sha256 = %s", (hashlib.sha256(data).hexdigest(),))
            ).fetchone()
        if not doc:
            sys.exit("No ingested document matches this file: not attached")
        rec = await storage.put(storage.object_path("rag", str(doc["id"]), doc["filename"]), data, storage.content_type(doc["filename"]))
        if not rec:
            sys.exit("upload failed (see log)")
        async with get_pool().connection() as conn:
            await conn.execute("update documents set file = %s where id = %s", (Jsonb(rec), doc["id"]))
        print(f"attached {doc['filename']} ({len(data):,} bytes) -> {rec['bucket']}/{rec['path']}")
    finally:
        await close_pool()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    if sys.platform == "win32":  # psycopg async needs a selector loop on Windows (as in run.py)
        asyncio.run(main(sys.argv[1]), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(main(sys.argv[1]))
