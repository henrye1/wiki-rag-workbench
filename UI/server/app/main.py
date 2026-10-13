import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse

from . import auth, bench, bulk, proxy
from .config import get_settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings()
    yield
    await proxy.close()


app = FastAPI(title="Workbench BFF", version="0.1.0", lifespan=lifespan)
app.add_middleware(auth.AuthMiddleware)
app.include_router(auth.router)


@app.get("/api/status")
async def status():
    """Health + headline counts for each system."""
    s = get_settings()

    async def check(service: str, path: str):
        base, key = proxy.target(service)
        try:
            r = await proxy.client().get(f"{base}{path}", headers={"X-API-Key": key}, timeout=5)
            return {"ok": r.status_code == 200, "data": r.json() if r.status_code == 200 else None, "url": base}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}", "url": base}

    rag_health, rag_docs, rag_cols, wiki_health, wikis = await asyncio.gather(
        check("rag", "/health"), check("rag", "/documents"), check("rag", "/collections"), check("wiki", "/health"), check("wiki", "/wikis")
    )
    try:
        runs = await bench.list_runs()
    except Exception:
        runs = []
    return {
        "rag": {"ok": rag_health["ok"], "url": rag_health["url"], "documents": rag_docs.get("data") or [],
                "collections": rag_cols.get("data") or []},
        "wiki": {"ok": wiki_health["ok"], "url": wiki_health["url"], "wikis": wikis.get("data") or []},
        "benchmark": {"ok": await bench.db_ok() and s.bench_python_path().exists(), "runs": len(runs), "latest": runs[0] if runs else None},
    }


@app.get("/healthz", include_in_schema=False)
async def healthz():
    """Liveness for the host (Render health check); open, no login."""
    return {"status": "ok"}


# Order matters: specific /api routers before the generic /api/{service}/... proxy
app.include_router(bulk.router)
app.include_router(bench.router)
app.include_router(proxy.router)


@app.get("/view/{path:path}", include_in_schema=False)
@app.get("/view", include_in_schema=False)
async def wiki_viewer(request: Request, path: str = ""):
    """Proxy the Wiki API's public HTML viewer so it works through the tunnel too."""
    base, _ = proxy.target("wiki")
    r = await proxy.client().get(f"{base}/view/{path}".rstrip("/"), params=request.query_params)
    return Response(r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    """Serve the built Angular app (UI/web/dist); unknown paths fall back to index.html for client-side routing."""
    dist = get_settings().web_dist
    if path.startswith(("api/", "view")):
        raise HTTPException(404)
    file = (dist / path).resolve()
    if path and file.is_file() and dist.resolve() in file.parents:
        return FileResponse(file)
    index = dist / "index.html"
    if not index.exists():
        raise HTTPException(404, "UI not built. Run `npm run build` in UI/web, or use `npm start` (dev server on :4200).")
    return FileResponse(index)
