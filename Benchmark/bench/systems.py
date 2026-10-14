"""Clients for the two systems under test. Both receive the identical question text."""
import asyncio
import time
from urllib.parse import quote

import httpx

from .config import get_settings

SYSTEMS = ("rag", "wiki")


async def _post(client: httpx.AsyncClient, url: str, key: str, body: dict, attempts: int = 3) -> dict:
    for i in range(attempts):
        try:
            r = await client.post(url, json=body, headers={"X-API-Key": key}, timeout=300)
            if r.status_code >= 500 and i < attempts - 1:
                await asyncio.sleep(5 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.TransportError, httpx.TimeoutException):
            if i == attempts - 1:
                raise
            await asyncio.sleep(5 * (i + 1))
    raise RuntimeError("unreachable")


async def ask(client: httpx.AsyncClient, system: str, question: str) -> dict:
    s = get_settings()
    t0 = time.perf_counter()
    if system == "rag":
        data = await _post(client, f"{s.rag_url}/collections/{quote(s.rag_collection, safe='')}/query", s.rag_api_key,
                           {"question": question, "sources": s.sources})
        sources = [c.get("para_ref") or c.get("chunk_id") for c in data.get("citations", [])]
    else:
        data = await _post(client, f"{s.wiki_url}/wikis/{s.wiki_slug}/query", s.wiki_api_key,
                           {"question": question, "save": False, "sources": s.sources})
        sources = [p["slug"] for p in data.get("pages", []) if p.get("cited")]
    return {"answer": data["answer"], "sources": sources, "latency_s": round(time.perf_counter() - t0, 2)}


async def describe(client: httpx.AsyncClient) -> dict:
    """Snapshot of the systems under test, recorded in results for reproducibility."""
    s = get_settings()
    out = {}
    try:
        r = await client.get(f"{s.rag_url}/collections/{quote(s.rag_collection, safe='')}/documents", headers={"X-API-Key": s.rag_api_key})
        r.raise_for_status()
        out["rag"] = {"url": s.rag_url, "collection": s.rag_collection,
                      "documents": [{"filename": d["filename"], "chunks": d["chunks"]} for d in r.json()]}
    except Exception as e:
        out["rag"] = {"url": s.rag_url, "error": str(e)}
    try:
        w = (await client.get(f"{s.wiki_url}/wikis", headers={"X-API-Key": s.wiki_api_key})).json()
        out["wiki"] = {"url": s.wiki_url, "wiki": next((x for x in w if x["slug"] == s.wiki_slug), None)}
    except Exception as e:
        out["wiki"] = {"url": s.wiki_url, "error": str(e)}
    return out
