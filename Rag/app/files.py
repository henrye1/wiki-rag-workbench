"""Removing a deleted document's stored file. Why: two collections can hold the same original (the same stored file
path), so a file is removed only when no document still points to it; otherwise deleting one collection would break
"View original" in the other."""
from . import storage
from .db import get_pool


async def remove_unless_held(files: list[dict | None]) -> None:
    """Remove each stored file that no remaining document points to (call after the documents are deleted)."""
    async with get_pool().connection() as conn:
        for f in files:
            if not f:
                continue
            held = await (await conn.execute(
                "select 1 from documents where file->>'bucket' = %s and file->>'path' = %s limit 1",
                (f.get("bucket"), f.get("path")))).fetchone()
            if not held:
                await storage.remove(f)
