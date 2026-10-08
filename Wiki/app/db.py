from pgvector.psycopg import register_vector_async
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import get_settings

pool: AsyncConnectionPool | None = None


async def _configure(conn):
    await register_vector_async(conn)
    conn.row_factory = dict_row


async def open_pool():
    global pool
    pool = AsyncConnectionPool(get_settings().database_url, min_size=1, max_size=10, configure=_configure, open=False)
    await pool.open()


async def close_pool():
    if pool:
        await pool.close()


def get_pool() -> AsyncConnectionPool:
    assert pool is not None, "DB pool not open"
    return pool
