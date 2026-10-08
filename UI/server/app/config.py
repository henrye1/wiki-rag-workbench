import pathlib
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = pathlib.Path(__file__).resolve().parent.parent
PROJECT = SERVER_DIR.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=SERVER_DIR / ".env", extra="ignore")

    rag_url: str = "http://127.0.0.1:8000"
    rag_api_key: str
    wiki_url: str = "http://127.0.0.1:8001"
    wiki_api_key: str

    bench_dir: pathlib.Path = PROJECT / "Benchmark"
    bench_python: pathlib.Path | None = None  # default: <bench_dir>/.venv/Scripts/python(.exe)
    default_query_set: pathlib.Path = PROJECT / "Docs" / "IFRS9_Requirement_Query_Set_BULK_5.txt"
    # Shared-password login; leave empty for local use without login
    ui_password: str = ""
    session_secret: str = ""
    web_dist: pathlib.Path = SERVER_DIR.parent / "web" / "dist" / "web" / "browser"

    def bench_python_path(self) -> pathlib.Path:
        if self.bench_python:
            return self.bench_python
        win = self.bench_dir / ".venv" / "Scripts" / "python.exe"
        return win if win.exists() else self.bench_dir / ".venv" / "bin" / "python"


@lru_cache
def get_settings() -> Settings:
    return Settings()
