import pathlib
import sys
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = pathlib.Path(__file__).resolve().parent.parent
PROJECT = SERVER_DIR.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=SERVER_DIR / ".env", extra="ignore")

    rag_url: str = "http://127.0.0.1:8000"
    rag_api_key: str
    wiki_url: str = "http://127.0.0.1:8001"
    wiki_api_key: str
    # Benchmark runs live in bench.runs
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"  # local Supabase

    bench_dir: pathlib.Path = PROJECT / "Benchmark"
    bench_python: pathlib.Path | None = None  # default: <bench_dir>/.venv python, else this interpreter (container)
    default_query_set: pathlib.Path = PROJECT / "Docs" / "IFRS9_Requirement_Query_Set_BULK_5.txt"  # optional
    # Shared-password login; leave empty for local use without login
    ui_password: str = ""
    session_secret: str = ""
    web_dist: pathlib.Path = SERVER_DIR.parent / "web" / "dist" / "web" / "browser"

    @field_validator("rag_url", "wiki_url")
    @classmethod
    def _scheme(cls, v: str) -> str:
        # Render private services expose host:port without a scheme
        v = v.rstrip("/")
        return v if "://" in v else f"http://{v}"

    def bench_python_path(self) -> pathlib.Path:
        if self.bench_python:
            return self.bench_python
        for venv in (self.bench_dir / ".venv" / "Scripts" / "python.exe", self.bench_dir / ".venv" / "bin" / "python"):
            if venv.exists():
                return venv
        return pathlib.Path(sys.executable)


@lru_cache
def get_settings() -> Settings:
    return Settings()
