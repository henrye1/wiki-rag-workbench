from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile

from .. import bulk
from .collections import collection_dep

router = APIRouter(tags=["bulk"])


@router.post("/collections/{c}/bulk")
async def bulk_run(
    file: UploadFile,
    col: dict = Depends(collection_dep),
    topics: list[int] | None = Query(None, description="Only run these topic numbers, e.g. ?topics=1&topics=3"),
    revise: bool = Query(True, description="Run a self-check revision pass on each draft"),
):
    """Run a query-set file (TOPIC n of N blocks). Returns one JSON result per topic."""
    text = (await file.read()).decode("utf-8", errors="replace")
    try:
        return await bulk.run(text, col["id"], topics, revise)
    except ValueError as e:
        raise HTTPException(422, str(e))
