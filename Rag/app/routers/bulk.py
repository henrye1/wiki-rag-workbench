from fastapi import APIRouter, HTTPException, Query, UploadFile

from .. import bulk

router = APIRouter(tags=["bulk"])


@router.post("/bulk")
async def bulk_run(
    file: UploadFile,
    topics: list[int] | None = Query(None, description="Only run these topic numbers, e.g. ?topics=1&topics=3"),
    revise: bool = Query(True, description="Run a self-check revision pass on each draft"),
):
    """Run a query-set file (TOPIC n of N blocks). Returns one JSON result per topic."""
    text = (await file.read()).decode("utf-8", errors="replace")
    try:
        return await bulk.run(text, topics, revise)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/bulk/parse")
async def bulk_parse(file: UploadFile):
    """Dry run: show how the query-set file is parsed, without calling the LLM."""
    text = (await file.read()).decode("utf-8", errors="replace")
    try:
        rules, topics = bulk.parse_query_set(text)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"rules_chars": len(rules), "topics": [t.__dict__ | {"block": None} for t in topics]}
