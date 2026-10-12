"""Store the original file for a source ingested before file storage existed.

  python -m app.attach_file <wiki-slug> <source-slug> <path/to/file>

The file is re-extracted and must produce the same text the source was ingested from (same SHA-256),
so a different file cannot be attached by mistake.
"""
import asyncio
import hashlib
import pathlib
import selectors
import sys

from . import storage
from .config import get_settings
from .db import close_pool, get_pool, open_pool
from .routers.sources import attach_file
from .sources import extract


async def main(wiki_slug: str, source_slug: str, path: str):
    if not storage.enabled():
        sys.exit("File storage is not configured: set SUPABASE_SECRET_KEY")
    f = pathlib.Path(path)
    data = f.read_bytes()
    ex = extract.from_upload(f.name, data, get_settings().section_words)
    await open_pool()
    try:
        async with get_pool().connection() as conn:
            src = await (
                await conn.execute(
                    """select s.id, s.sha256, w.id as wiki_id from wiki.sources s join wiki.wikis w on w.id = s.wiki_id
                       where w.slug = %s and s.slug = %s""", (wiki_slug, source_slug),
                )
            ).fetchone()
        if not src:
            sys.exit(f"No source '{source_slug}' in wiki '{wiki_slug}'")
        if hashlib.sha256(ex.text.encode("utf-8")).hexdigest() != src["sha256"]:
            sys.exit("This file does not produce the text the source was ingested from: not attached")
        rec = await attach_file(src["id"], storage.object_path("wiki", str(src["wiki_id"]), source_slug, f.name), data, f.name)
        print(f"attached {f.name} ({len(data):,} bytes) -> {rec['bucket']}/{rec['path']}" if rec else "upload failed (see log)")
    finally:
        await close_pool()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    if sys.platform == "win32":  # psycopg async needs a selector loop on Windows (as in run.py)
        asyncio.run(main(*sys.argv[1:]), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(main(*sys.argv[1:]))
