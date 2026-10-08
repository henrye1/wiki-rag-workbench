"""Pass-through proxy to the RAG and Wiki APIs. The browser never sees the API keys."""
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from .config import get_settings

router = APIRouter()
_client: httpx.AsyncClient | None = None
# Response headers worth passing back to the browser
PASS_HEADERS = ("content-type", "content-disposition", "cache-control")


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10))
    return _client


async def close():
    if _client:
        await _client.aclose()


def target(service: str) -> tuple[str, str]:
    s = get_settings()
    if service == "rag":
        return s.rag_url, s.rag_api_key
    if service == "wiki":
        return s.wiki_url, s.wiki_api_key
    raise HTTPException(404, "Unknown service")


@router.api_route("/api/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
async def proxy(service: str, path: str, request: Request):
    base, key = target(service)
    headers = {"X-API-Key": key}
    if ct := request.headers.get("content-type"):
        headers["content-type"] = ct
    if accept := request.headers.get("accept"):
        headers["accept"] = accept
    req = client().build_request(
        request.method, f"{base}/{path}", params=request.query_params, content=await request.body(), headers=headers
    )
    try:
        resp = await client().send(req, stream=True)
    except httpx.ConnectError:
        raise HTTPException(502, f"{service} API is not reachable at {base}")
    # Streamed back unchanged: works for JSON, SSE (query/stream) and file downloads (export.zip)
    return StreamingResponse(
        resp.aiter_raw(),
        status_code=resp.status_code,
        headers={k: v for k, v in resp.headers.items() if k.lower() in PASS_HEADERS},
        background=BackgroundTask(resp.aclose),
    )
