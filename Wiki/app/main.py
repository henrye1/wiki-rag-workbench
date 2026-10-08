import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse

from . import db, jobs
from .auth import require_api_key
from .config import get_settings
from .routers import ops, pages, sources, view, wikis

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings()  # fail fast on missing env
    await db.open_pool()
    await jobs.recover()
    yield
    await db.close_pool()


app = FastAPI(title="LLM Wiki API", version="0.1.0", lifespan=lifespan)
auth = [Depends(require_api_key)]
for r in (wikis.router, sources.router, pages.router, ops.router):
    app.include_router(r, dependencies=auth)
app.include_router(view.router)  # public, read-only


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/view")


@app.get("/health")
async def health():
    async with db.get_pool().connection() as conn:
        await conn.execute("select 1")
    return {"status": "ok"}
