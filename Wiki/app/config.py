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
    embed_dim: int = 768  # must match vector(768) in migrations
    embed_batch: int = 100
    temperature: float = 0.2
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"  # local Supabase
    db_pool_max: int = 10  # keep low on hosted Postgres (connection limits)

    section_words: int = 3000  # source split size for note extraction
    chunk_max_words: int = 500  # page chunk size for search / IFRS parser
    max_pages_per_ingest: int = 17  # including the source page
    page_source_words: int = 12000  # schema without fixed sections: source paragraphs given to each page writer
    page_part_words: int = 4000  # source words per writing call; longer pages are written in parts
    page_background_words: int = 2000  # other sections' paragraphs given to a section page as context only
    route_batch: int = 120  # paragraphs per call when assigning paragraphs to schema sections
    llm_concurrency: int = 4  # parallel LLM calls inside one job
    job_workers: int = 2  # jobs running at once
    query_top_k: int = 8
    query_max_pages: int = 8
    lint_batch_pages: int = 12
    max_upload_mb: int = 50

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
