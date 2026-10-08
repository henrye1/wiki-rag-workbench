import secrets

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from .config import get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Security(api_key_header)):
    if not key or not secrets.compare_digest(key, get_settings().api_key):
        raise HTTPException(401, "Invalid or missing API key")
