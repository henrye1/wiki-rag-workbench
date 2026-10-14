"""Original uploaded files, kept in a private Supabase Storage bucket and viewed through short-lived signed URLs.

Off unless SUPABASE_SECRET_KEY is set (SUPABASE_URL defaults to the project in DATABASE_URL). The secret key stays
server-side: the browser only ever receives a signed URL for one file.
"""
import logging
import re
from functools import lru_cache
from urllib.parse import quote, unquote

import httpx

from .config import get_settings

log = logging.getLogger(__name__)
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def base_url() -> str:
    s = get_settings()
    if s.supabase_url:
        return s.supabase_url.rstrip("/")
    # Supabase pooler URLs carry the project ref in the user name: postgres.<ref>@...pooler.supabase.com
    m = re.search(r"://postgres\.([a-z0-9]+)[:@]", s.database_url)
    return f"https://{m.group(1)}.supabase.co" if m else ""


def enabled() -> bool:
    return bool(get_settings().supabase_secret_key and base_url())


def content_type(name: str) -> str:
    ext = re.search(r"\.[A-Za-z0-9]+$", name)
    return CONTENT_TYPES.get(ext.group(0).lower(), "application/octet-stream") if ext else "application/octet-stream"


def object_path(*parts: str) -> str:
    """A safe object key: folders as given, file name stripped of characters Storage rejects."""
    *folders, name = parts
    name = re.sub(r"[^\w.\- ()]", "_", name).strip() or "file"
    return "/".join([*folders, name])


def _headers() -> dict:
    key = get_settings().supabase_secret_key
    # Legacy service_role keys are JWTs and go in Authorization too; new sb_secret_ keys go in apikey only
    return {"apikey": key, **({"Authorization": f"Bearer {key}"} if key.startswith("eyJ") else {})}


@lru_cache
def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=f"{base_url()}/storage/v1", headers=_headers(), timeout=120)


_bucket_ready = False


async def _ensure_bucket():
    global _bucket_ready
    if _bucket_ready:
        return
    bucket = get_settings().storage_bucket
    r = await _client().get(f"/bucket/{bucket}")
    if r.status_code != 200:
        r = await _client().post("/bucket", json={"id": bucket, "name": bucket, "public": False})
        if r.status_code not in (200, 201, 409) and "already exists" not in r.text.lower():
            r.raise_for_status()
    _bucket_ready = True


async def put(path: str, data: bytes, ctype: str) -> dict | None:
    """Upload (overwriting) and return the record to store with the source, or None when storage is off or fails."""
    if not enabled():
        return None
    try:
        await _ensure_bucket()
        bucket = get_settings().storage_bucket
        r = await _client().post(f"/object/{bucket}/{quote(path)}", content=data,
                                 headers={"content-type": ctype, "x-upsert": "true"})
        r.raise_for_status()
        return {"bucket": bucket, "path": path, "content_type": ctype, "size": len(data)}
    except httpx.HTTPError as e:  # keeping the original is a convenience: never fail an ingest over it
        log.warning("storage: upload of %s failed: %s", path, e)
        return None


async def signed_url(file: dict, expires_s: int = 3600) -> str:
    r = await _client().post(f"/object/sign/{file['bucket']}/{quote(file['path'])}", json={"expiresIn": expires_s})
    r.raise_for_status()
    # Storage returns the object path unencoded (spaces, brackets in file names): encode it, keep the token as is
    path, _, token = unquote(r.json()["signedURL"]).partition("?")
    return f"{base_url()}/storage/v1{quote(path)}?{token}"


async def remove(file: dict | None):
    if not (file and enabled()):
        return
    try:
        r = await _client().request("DELETE", f"/object/{file['bucket']}", json={"prefixes": [file["path"]]})
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("storage: delete of %s failed: %s", file.get("path"), e)
