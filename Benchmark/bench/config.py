import pathlib
from functools import lru_cache

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
    wiki_slug: str = "ifrs9"

    runs: int = 3
    concurrency: int = 4  # parallel topics (each topic = 2 system calls + 1 judge call)
    seed: int = 42

    query_set: pathlib.Path = DOCS / "IFRS9_Requirement_Query_Set_BULK_5.txt"
    # Human-written assessment with the reference answers (kept local, see Docs/ in .gitignore)
    reference_docx: pathlib.Path = DOCS / "reference_assessment.docx"

    @field_validator("query_set", "reference_docx")
    @classmethod
    def _relative_to_benchmark(cls, v: pathlib.Path) -> pathlib.Path:
        return v if v.is_absolute() else (ROOT / v).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
