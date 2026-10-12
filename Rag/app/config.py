from functools import lru_cache

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
    db_pool_max: int = 10  # keep low on hosted Postgres (connection limits)
    top_k: int = 8
    chunk_max_words: int = 500
    temperature: float = 0.1
    bulk_concurrency: int = 3
    bulk_k_per_query: int = 6
    bulk_max_chunks: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
