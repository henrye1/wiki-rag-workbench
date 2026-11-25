from functools import lru_cache
from urllib.parse import quote

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


FALLBACK_MODEL = "gemini-2.5-flash"  # used where a model setting is given but left empty
MODEL_JOBS = {  # job -> what it does; each job's model is its own setting (<JOB>_MODEL), shown on the admin screen
    "parser": "reads uploaded files", "writer": "notes, routing, planning, writing and fixing pages",
    "answer": "Ask and the wiki answers", "lint": "lint health check",
    "suggest": "issuer, edition and part suggestions on the upload form",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str
    gemini_api_key: str
    parser_model: str = "gemini-4-hydrogen"
    writer_model: str = "gemini-4-carbon"
    answer_model: str = "gemini-4-carbon"
    lint_model: str = "gemini-4-carbon"
    suggest_model: str = "gemini-4-carbon"
    parser_thinking_budget: int = 2048  # the most thinking tokens one parser call may use (0: the model's own setting)
    gemini_embed_model: str = "gemini-embedding-001"
    embed_dim: int = 768  # must match vector(768) in migrations
    embed_batch: int = 100
    temperature: float = 0.1
    # A job's spending cap in US dollars (0: none): the job stops, failed, once its model calls have cost this much.
    # Worked out from MODEL_PRICES: "<model>=<$ per million input tokens>/<$ per million output tokens>", comma
    # separated; thinking tokens are billed as output. With a cap set, a call to a model with no price is refused.
    job_spend_cap_usd: float = 0
    fix_rounds_per_page: int = 2  # fix rounds a page may have in one job, over all the checks it goes through
    model_prices: str = ""
    llm_timeout_s: int = 600  # the longest one model call may take; a call over it is tried again (without a limit a stalled connection waits forever)
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"  # local Supabase
    # Original uploads in Supabase Storage (off unless the secret key is set; the URL defaults to DATABASE_URL's project)
    supabase_url: str = ""
    supabase_secret_key: str = ""
    storage_bucket: str = "sources"
    db_pool_max: int = 10  # keep low on hosted Postgres (connection limits)

    section_words: int = 3000  # source split size for note extraction
    chunk_max_words: int = 500  # page chunk size for search / IFRS parser
    page_source_words: int = 12000  # a source with no paragraphs to route: the most relevant paragraphs given to a page writer
    page_part_words: int = 4000  # source words per writing call; longer pages are written in parts
    page_background_words: int = 2000  # other sections' paragraphs given to a section page as context only
    route_batch: int = 120  # paragraphs per call when assigning paragraphs to schema sections
    route_batch_last: int = 5  # the last routing round: what the earlier rounds left unplaced, a few paragraphs per call
    llm_concurrency: int = 8  # parallel LLM calls inside one job (each call is independent: the same prompts at any setting)
    job_workers: int = 2  # jobs running at once
    browse_max_rounds: int = 6  # choosing pages to answer from: safety nets only; the model stops when it has enough
    browse_max_pages: int = 30
    browse_max_words: int = 150000  # words of page text read for one question
    shortlist_size: int = 15  # pages the search lists for the model to choose from when answering
    lint_batch_pages: int = 12
    max_upload_mb: int = 50

    @field_validator(*(f"{j}_model" for j in MODEL_JOBS), mode="before")
    @classmethod
    def _model_or_fallback(cls, v):
        return v.strip() if isinstance(v, str) and v.strip() else FALLBACK_MODEL

    def model_for(self, job: str) -> str:
        return getattr(self, f"{job}_model")

    def prices(self) -> dict[str, tuple[float, float]]:
        """model -> ($ per million input tokens, $ per million output tokens), from MODEL_PRICES."""
        out = {}
        for item in (x.strip() for x in self.model_prices.split(",") if x.strip()):
            name, _, rates = item.partition("=")
            inp, _, outp = rates.partition("/")
            out[name.strip()] = (float(inp), float(outp))
        return out

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
