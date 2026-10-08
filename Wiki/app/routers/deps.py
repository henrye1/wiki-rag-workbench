from typing import Literal

from fastapi import HTTPException

from ..wiki import store

Mode = Literal["auto", "review"]


async def wiki_dep(w: str) -> dict:
    try:
        return await store.get_wiki(w)
    except store.NotFound as e:
        raise HTTPException(404, str(e))
