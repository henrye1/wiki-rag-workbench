"""Clients for the systems under test. All receive the identical question text.

The wiki is compared with two RAG columns, each graded against the wiki in its own blind pair:
- rag: the RAG's /query as it is, one search for the whole topic (its top_k passages);
- rag_q: the same route and answer prompt, but one search for the topic's first line and one per numbered question
  (retrieval=per_question: the bulk run's search, its bulk_k_per_query passages each, up to bulk_max_chunks).
SYSTEMS and LABEL are the one list of systems and their names; the UI server mirrors them (UI/server/app/bench.py)."""
import asyncio
import time
from urllib.parse import quote

import httpx

from .config import get_settings

SYSTEMS = ("rag", "wiki", "rag_q")
RAGS = ("rag", "rag_q")  # each is graded against the wiki in its own pair
LABEL = {"rag": "RAG (per topic)", "rag_q": "RAG (per question)", "wiki": "Wiki"}
RETRIEVAL = {"rag": "whole", "rag_q": "per_question"}


def compared(data: dict) -> tuple[str, ...]:
    """The systems a run compares, as it recorded them when it started."""
    return tuple(data["config"]["systems_compared"])


def pairs(data: dict) -> tuple[str, ...]:
    """The RAG systems of a run, each paired with the wiki for grading."""
    return tuple(r for r in RAGS if r in compared(data))


def answers_of(run: dict) -> dict:
    """A repetition's answers by system: a graded repetition keeps them under "systems" (with its scores), one not graded
    yet (or whose grading failed) under "answers"."""
    return run.get("systems") or run.get("answers") or {}


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
    if system in RAGS:
        data = await _post(client, f"{s.rag_url}/collections/{quote(s.rag_collection, safe='')}/query", s.rag_api_key,
                           {"question": question, "sources": s.sources, "retrieval": RETRIEVAL[system],
                            "include_editorial": s.rag_include_editorial})
        sources = [c.get("para_ref") or c.get("chunk_id") for c in data.get("citations", [])]
        extra = {}
    else:
        data = await _post(client, f"{s.wiki_url}/wikis/{s.wiki_slug}/query", s.wiki_api_key,
                           {"question": question, "save": False, "sources": s.sources, "use_saved": s.use_saved})
        sources = [p["slug"] for p in data.get("pages", []) if p.get("cited")]
        extra = {"saved_answers_read": [p["slug"] for p in data.get("pages", []) if p.get("saved")]}  # read with the pages
    # what the answer was based on (RAG: the passages; wiki: page versions and a hash of the text given), the AI calls
    # behind it, with their tokens, and (wiki, choosing in rounds) each round's choices and reasons
    recorded = {k: data[k] for k in ("read", "usage", "rounds") if k in data}
    return {"answer": data["answer"], "sources": sources, **extra, **recorded, "latency_s": round(time.perf_counter() - t0, 2)}


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
        r = await client.get(f"{s.wiki_url}/wikis/{s.wiki_slug}", headers={"X-API-Key": s.wiki_api_key})
        r.raise_for_status()
        w = r.json()  # its state when the run started: pages, sources and latest applied change
        out["wiki"] = {"url": s.wiki_url, "wiki": {k: w.get(k) for k in ("id", "name", "slug", "pages", "sources", "created_at",
                                                                         "last_change_id", "last_change_at")}}
    except Exception as e:
        out["wiki"] = {"url": s.wiki_url, "error": str(e)}
    return out
