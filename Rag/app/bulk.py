"""Parse an IFRS requirement query-set file and run each topic through retrieval + generation."""
import asyncio
import json
import re
from dataclasses import dataclass, field

from . import llm, prompts, retrieval
from .config import get_settings

TOPIC_RE = re.compile(r"^TOPIC (\d+) of (\d+):\s*(.+)$", re.M)
# Chat-only instructions (one-topic-per-reply flow) that do not apply to an API run
DROP_RULE_RE = re.compile(r"^(HOW THIS RUN WORKS:|END OF EACH REPLY:|Rule 12 in bulk mode:).*$", re.M)
# IFRS paragraph refs such as 5.5.3, 4.1.2A, B5.5.17 (two+ dot-separated numbers)
PARA_NUM_RE = re.compile(r"\b(?:B|BC|IE|IG)?\d+\.\d+(?:\.\d+)*[A-Z]?\b")
WORD_TOLERANCE = 0.25


@dataclass
class Topic:
    number: int
    title: str
    block: str
    row_label: str = ""
    word_guide: int | None = None
    leave_out: str = ""
    search_terms: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)


def _field(block: str, name: str) -> str:
    m = re.search(rf"^{name}:\s*(.*)$", block, re.M)
    return m.group(1).strip() if m else ""


def parse_query_set(text: str) -> tuple[str, list[Topic]]:
    text = text.replace("\r\n", "\n")
    matches = list(TOPIC_RE.finditer(text))
    if not matches:
        raise ValueError("No 'TOPIC n of N:' blocks found")
    rules = DROP_RULE_RE.sub("", text[: matches[0].start()])
    rules = re.sub(r"=+\s*$", "", rules).strip()
    topics = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = re.sub(r"\n=+\s*\nEND OF TOPICS.*", "", text[m.start() : end], flags=re.S).strip()
        wg = re.search(r"about (\d+) words", _field(block, "Word guide"))
        topics.append(
            Topic(
                number=int(m.group(1)),
                title=m.group(3).strip(),
                block=block,
                row_label=_field(block, "Row label"),
                word_guide=int(wg.group(1)) if wg else None,
                leave_out=_field(block, "Leave out"),
                search_terms=[t.strip() for t in _field(block, "Search terms").split(",") if t.strip()],
                questions=re.findall(r"^Q\d+\..*$", block, re.M),
            )
        )
    return rules, topics


async def _retrieve(topic: Topic, collection_id) -> list[dict]:
    s = get_settings()
    queries = [f"{topic.title}. {', '.join(topic.search_terms)}"] + topic.questions
    embeddings = await llm.embed(queries, task="RETRIEVAL_QUERY")
    results = await asyncio.gather(
        *(retrieval.search(q, s.bulk_k_per_query, embedding=e, collection_id=collection_id) for q, e in zip(queries, embeddings))
    )
    # Round-robin merge so every question contributes its best hits before the cap
    seen: dict[int, dict] = {}
    for rank in range(s.bulk_k_per_query):
        for rows in results:
            if rank < len(rows) and rows[rank]["id"] not in seen and len(seen) < s.bulk_max_chunks:
                seen[rows[rank]["id"]] = rows[rank]
    return list(seen.values())


def _render(topic: Topic, out: dict, word_count: int) -> str:
    lines = [f"### {topic.title}", f"**{topic.row_label}**", ""]
    lines += [p + "\n" for p in out.get("prose_paragraphs", [])]
    lines += ["**Source list**", "", "| Para | What it covers | IFRS paragraphs used | Passage / claim IDs |", "|---|---|---|---|"]
    for r in out.get("source_list", []):
        lines.append(f"| {r['para']} | {r['covers']} | {', '.join(r['ifrs_paragraphs'])} | {', '.join(r['passage_ids'])} |")
    lines += ["", "**Not addressed in the Standard**"]
    na = out.get("not_addressed", [])
    lines += [f"- {n['question']}: {n['note']}" for n in na] if na else ["- None"]
    lines += ["", f"**Word count:** {word_count}"]
    return "\n".join(lines)


def check(topic: Topic, out: dict, by_id: dict) -> list[str]:
    """Mechanical rule checks; returned as issues and fed to the revision pass."""
    issues = []
    prose = out.get("prose_paragraphs", [])
    refs = sorted({m for p in prose for m in PARA_NUM_RE.findall(p)})
    if refs:
        issues.append(f"IFRS paragraph numbers appear in the prose (rule 7): {', '.join(refs)}")
    wc = sum(len(p.split()) for p in prose)
    if topic.word_guide and wc > topic.word_guide * (1 + WORD_TOLERANCE):
        issues.append(f"Word count {wc} is well over the word guide of about {topic.word_guide}; tighten without dropping required points or conditions")
    if len(out.get("source_list", [])) != len(prose):
        issues.append("Source list must have exactly one row per prose paragraph")
    unknown = sorted({pid for r in out.get("source_list", []) for pid in r.get("passage_ids", []) if pid not in by_id})
    if unknown:
        issues.append(f"Unknown passage ids cited: {', '.join(unknown)}")
    return issues


async def run_topic(rules: str, topic: Topic, collection_id, revise: bool = True) -> dict:
    rows = await _retrieve(topic, collection_id)
    by_id = {retrieval.chunk_id(r): r for r in rows}
    context = retrieval.format_context(rows, with_ids=True)
    raw = await llm.generate(prompts.BULK_SYSTEM, prompts.bulk_prompt(rules, topic.block, context), schema=prompts.BULK_SCHEMA)
    out = json.loads(raw)
    draft_issues = check(topic, out, by_id)
    revised = False
    if revise:
        raw = await llm.generate(
            prompts.BULK_SYSTEM,
            prompts.revise_prompt(rules, topic.block, context, raw, draft_issues),
            schema=prompts.BULK_SCHEMA,
        )
        out, revised = json.loads(raw), True
    issues = check(topic, out, by_id)
    word_count = sum(len(p.split()) for p in out.get("prose_paragraphs", []))
    cited = {pid for r in out.get("source_list", []) for pid in r.get("passage_ids", [])}
    return {
        "revised": revised,
        "draft_issues": draft_issues,
        "issues": issues,
        "topic_no": topic.number,
        "title": topic.title,
        "row_label": topic.row_label,
        "word_guide": topic.word_guide,
        "word_count": word_count,
        "prose_paragraphs": out.get("prose_paragraphs", []),
        "source_list": out.get("source_list", []),
        "not_addressed": out.get("not_addressed", []),
        "standard_version": out.get("standard_version"),
        "answer_markdown": _render(topic, out, word_count),
        "citations": [retrieval.citation(by_id[c]) for c in cited if c in by_id],
        "unknown_passage_ids": sorted(c for c in cited if c not in by_id),
        "retrieved": len(rows),
    }


async def run(text: str, collection_id, only: list[int] | None = None, revise: bool = True) -> dict:
    rules, topics = parse_query_set(text)
    if only:
        topics = [t for t in topics if t.number in only]
    sem = asyncio.Semaphore(get_settings().bulk_concurrency)

    async def one(t: Topic):
        async with sem:
            try:
                return await run_topic(rules, t, collection_id, revise)
            except Exception as e:  # keep other topics going
                return {"topic_no": t.number, "title": t.title, "error": f"{type(e).__name__}: {e}"}

    results = await asyncio.gather(*(one(t) for t in topics))
    return {"topics_total": len(topics), "topics": sorted(results, key=lambda r: r["topic_no"])}
