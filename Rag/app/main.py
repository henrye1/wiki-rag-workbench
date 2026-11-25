import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader

from . import db
from .config import get_settings
from .routers import bulk, collections, documents, query

logging.basicConfig(level=logging.INFO)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Security(api_key_header)):
    if not key or not secrets.compare_digest(key, get_settings().api_key):
        raise HTTPException(401, "Invalid or missing API key")


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()  # fail fast on missing env
    logging.getLogger("app.models").info("RAG_ANSWER_MODEL (the RAG side's answers): %s", s.rag_answer_model)
    await db.open_pool()
    yield
    await db.close_pool()


app = FastAPI(title="RAG API", version="0.1.0", lifespan=lifespan)
auth = [Depends(require_api_key)]
app.include_router(collections.router, dependencies=auth)
app.include_router(documents.router, dependencies=auth)
app.include_router(query.router, dependencies=auth)
app.include_router(bulk.router, dependencies=auth)


@app.get("/models", dependencies=auth)
async def models():
    """The RAG side's model job, its setting and the model it uses now."""
    return {"rag_answer": {"does": "the RAG side's answers (Ask, bulk and the benchmark)", "setting": "RAG_ANSWER_MODEL",
                           "model": get_settings().rag_answer_model}}


@app.get("/health")
async def health():
    async with db.get_pool().connection() as conn:
        await conn.execute("select 1")
    return {"status": "ok"}
