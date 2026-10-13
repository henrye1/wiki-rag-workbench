import pathlib
from functools import lru_cache
from urllib.parse import quote

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT.parent / "Docs"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # Judge. If unset here, the SDK falls back to the ANTHROPIC_API_KEY env var / `ant auth login` profile.
    anthropic_api_key: str | None = None
    judge_model: str = "claude-opus-5-5"
    judge_effort: str = "high"

    rag_url: str = "http://127.0.0.1:8000"
    rag_api_key: str
    wiki_url: str = "http://127.0.0.1:8001"
    wiki_api_key: str
    # CLI only: what a new run compares (UI runs choose them; a resumed run uses what it stored)
    rag_collection: str = ""
    wiki_slug: str = ""
    sources: str = "all"  # "standard" (Part A only) or "all" (Parts A, B and C); always the same for both systems

    # Results and uploaded inputs are stored in bench.runs
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"  # local Supabase

    runs: int = 3
    concurrency: int = 4  # parallel topics (each topic = 2 system calls + 1 judge call)
    seed: int = 42

    # CLI only: inputs for a new run started from the command line (UI runs upload them instead)
    query_set: pathlib.Path = DOCS / "IFRS9_Requirement_Query_Set_BULK_5.txt"
    # Human-written assessment with the reference answers (kept local, see Docs/ in .gitignore)
    reference_docx: pathlib.Path = DOCS / "reference_assessment.docx"

    @field_validator("query_set", "reference_docx")
    @classmethod
    def _relative_to_benchmark(cls, v: pathlib.Path) -> pathlib.Path:
        return v if v.is_absolute() else (ROOT / v).resolve()

    @field_validator("rag_url", "wiki_url")
    @classmethod
    def _scheme(cls, v: str) -> str:
        # Render private services expose host:port without a scheme
        v = v.rstrip("/")
        return v if "://" in v else f"http://{v}"

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
