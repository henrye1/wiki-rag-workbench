from functools import lru_cache
from urllib.parse import quote

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str
    gemini_api_key: str
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "gemini-embedding-001"
    embed_dim: int = 768  # must match vector(768) in migration
    embed_batch: int = 100
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"  # local Supabase
    # Original uploads in Supabase Storage (off unless the secret key is set; the URL defaults to DATABASE_URL's project)
    supabase_url: str = ""
    supabase_secret_key: str = ""
    storage_bucket: str = "sources"
    db_pool_max: int = 10  # keep low on hosted Postgres (connection limits)
    top_k: int = 8
    chunk_max_words: int = 500
    temperature: float = 0.1
    bulk_concurrency: int = 3
    bulk_k_per_query: int = 6
    bulk_max_chunks: int = 30

    @field_validator("database_url")
    @classmethod
    def _clean_database_url(cls, v: str) -> str:
        # Tolerate copy/paste slips in hosting dashboards: quotes, whitespace, a pasted "DATABASE_URL=" prefix,
        # and empty query parts ("...postgres?&sslmode=require", trailing "?") that psycopg rejects
        v = v.strip().strip("\"'").strip()
        if v.upper().startswith("DATABASE_URL="):
            v = v.split("=", 1)[1].strip()
        v = v.lstrip("=").strip()
        creds, at, rest = v.rpartition("@")  # only touch the query after the host: a password may contain "?"
        base, _, query = rest.partition("?")
        params = [p for p in query.split("&") if p and not p.startswith("=")]
        scheme, sep, userinfo = creds.partition("://")
        if at and sep and ":" in userinfo:
            # The password is taken literally (as typed into Supabase's URI template) and percent-encoded here,
            # so %, ?, #, / and @ in it work. Do not percent-encode it yourself.
            user, _, pw = userinfo.partition(":")
            creds = f"{scheme}://{user}:{quote(pw, safe='')}"
        return creds + at + base + ("?" + "&".join(params) if params else "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
