"""Prompts and JSON schemas for wiki operations. The wiki's own schema doc is always included."""

MAINTAINER_SYSTEM = """You are the maintainer of a persistent, interlinked markdown wiki.
You follow the wiki's schema document exactly. You only write what the provided material supports.
You never invent sources, facts or page slugs that you were not given, unless asked to propose new pages."""


def with_schema(schema_md: str, body: str) -> str:
    return f"<wiki_schema>\n{schema_md}\n</wiki_schema>\n\n{body}"


# ---------- ingest: notes ----------

NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2-4 sentence summary of this section"},
        "claims": {
            "type": "array",
            "description": "Statements the source itself ASSERTS as fact (rules, definitions, numbers). Keep location labels like [5.5.3] or [page 4] if present. Never turn a question, request or hypothesis into a claim.",
            "items": {"type": "string"},
        },
        "open_questions": {
            "type": "array",
            "description": "Questions, requests, hypotheses or instructions the source poses without answering them",
            "items": {"type": "string"},
        },
        "entities": {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}}, "required": ["name", "description"]},
        },
        "concepts": {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}}, "required": ["name", "description"]},
        },
    },
    "required": ["summary", "claims", "open_questions", "entities", "concepts"],
}


def notes_prompt(source_title: str, idx: int, total: int, section: str) -> str:
    return (
        f"Source: {source_title} (section {idx} of {total}).\n"
        "Extract notes for building wiki pages: a short summary; the claims the source itself asserts (complete, precise, "
        "with every condition); the questions/requests it poses without answering (as open questions, not claims); "
        "and the entities and concepts that deserve or relate to wiki pages. "
        "If the source is mainly a questionnaire, checklist or instructions, most content belongs in open_questions. "
        "Follow the wiki schema for what to capture and how to label it.\n\n"
        f"<section>\n{section}\n</section>"
    )


# ---------- ingest: plan ----------

ONE_TOP_PAGE = (
    "- `overview` is the wiki's only top-level page. Never create or link a second top-level or index page "
    "(for example one named after the standard, such as `ifrs-9`), even where the schema describes one; link to [[overview]] instead."
)

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "source_summary": {"type": "string", "description": "One-line summary of the source for the index"},
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create", "update"]},
                    "slug": {"type": "string", "description": "Existing slug for update; new kebab-case slug for create"},
                    "title": {"type": "string"},
                    "type": {"type": "string", "enum": ["overview", "topic", "concept", "entity", "comparison"]},
                    "focus": {"type": "string", "description": "What this page should cover / what to add or change, from this source"},
                },
                "required": ["action", "slug", "title", "type", "focus"],
            },
        },
    },
    "required": ["source_summary", "pages"],
}


def plan_prompt(source_title: str, source_slug: str, notes: str, index: str, candidates: str, max_pages: int) -> str:
    return (
        f"A new source has been added: \"{source_title}\" (its source page will be [[{source_slug}]], written separately).\n"
        f"Decide which wiki pages to create or update so the wiki integrates this source. At most {max_pages} pages.\n"
        "- Prefer updating existing pages over creating near-duplicates.\n"
        "- Create pages for important entities/concepts/topics that the source covers substantively.\n"
        "- Always include the `overview` page (create it if missing, otherwise update it).\n"
        f"{ONE_TOP_PAGE}\n"
        "- Do not include the source page itself.\n"
        "- Do not create a page whose content would come only from open questions; those belong on the source page.\n\n"
        f"<current_index>\nslug | type | title | summary\n{index}\n</current_index>\n\n"
        f"<related_existing_pages>\n{candidates}\n</related_existing_pages>\n\n"
        f"<source_notes>\n{notes}\n</source_notes>"
    )


# ---------- page writing ----------

PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string", "description": "One line for the index"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "content_md": {"type": "string", "description": "Full page markdown (no front matter, no top-level # title)"},
        "change_note": {"type": "string", "description": "What changed and why, one line"},
    },
    "required": ["title", "summary", "tags", "content_md", "change_note"],
}


def write_page_prompt(
    *, slug: str, title: str, ptype: str, focus: str, existing_md: str | None, material: str,
    linkable: str, source_slug: str | None, source_paragraphs: str | None = None,
    part: tuple[int, int] | None = None, headings_so_far: str = "",
) -> str:
    cite = (
        f"The source page is [[{source_slug}]]; cite it exactly as the wiki schema requires. "
        "Only state as fact what the source paragraphs or the Claims in the material support; material listed under Open "
        "questions may be recorded as open questions the source raises, never as facts.\n"
        if source_slug else ""
    )
    paragraphs = (
        "<source_paragraphs>\nThe source's own text for this page, each paragraph labelled with its [paragraph number], "
        "in document order. Write from these first; use the material for context.\n\n"
        f"{source_paragraphs}\n</source_paragraphs>\n\n"
        if source_paragraphs else ""
    )
    if part:
        n, total = part
        current = (
            f"This page is long, so it is written in {total} parts. This is part {n} of {total}: write only the content "
            "drawn from the source paragraphs given here. "
            + ("Start the page. " if n == 1 else
               f"Continue the page: do not repeat the introduction or a heading already used.\n<headings_so_far>\n{headings_so_far or '(none)'}\n</headings_so_far>\n")
            + "Do not write a 'Not yet covered' list; it is added after all parts are written.\n"
        )
        if existing_md:
            current += (
                f"<current_page version=\"existing\">\n{existing_md}\n</current_page>\n"
                "Keep the current page's correct content that relates to this part's source paragraphs, with its citations; "
                "flag contradictions with the schema's contradiction callout rather than silently replacing claims.\n"
            )
    elif existing_md:
        current = (
            f"<current_page version=\"existing\">\n{existing_md}\n</current_page>\n"
            "Rewrite the full page integrating the new material. Keep existing correct content and its citations; "
            "flag contradictions with the schema's contradiction callout rather than silently replacing claims.\n"
        )
    else:
        current = "This is a new page.\n"
    return (
        f"Write the wiki page `{slug}` (type: {ptype}, title: \"{title}\").\n"
        f"Focus: {focus}\n{cite}"
        "Link other pages with [[slug]] using ONLY slugs listed in <linkable_pages>.\n"
        f"{ONE_TOP_PAGE}\n\n"
        f"{current}\n"
        f"<linkable_pages>\n{linkable}\n</linkable_pages>\n\n"
        f"{paragraphs}"
        f"<material>\n{material}\n</material>"
    )


# ---------- query ----------

SELECT_SCHEMA = {
    "type": "object",
    "properties": {"slugs": {"type": "array", "items": {"type": "string"}}},
    "required": ["slugs"],
}


def select_prompt(question: str, index: str, max_pages: int) -> str:
    return (
        f"Pick up to {max_pages} wiki pages most useful for answering the question. Return their slugs.\n\n"
        f"<index>\nslug | type | title | summary\n{index}\n</index>\n\nQuestion: {question}"
    )


QUERY_SYSTEM = """You answer questions using ONLY the wiki pages provided.
- Cite pages inline with [[slug]] after the statements they support.
- If pages disagree, say so and cite both.
- If the pages do not answer the question, say what is missing; do not use outside knowledge.
- Use the clearest form: prose, a list, or a markdown table."""


def query_prompt(question: str, pages_md: str) -> str:
    return f"<wiki_pages>\n{pages_md}\n</wiki_pages>\n\nQuestion: {question}"


def save_answer_prompt(question: str, answer: str, linkable: str) -> str:
    return (
        "Turn this question and answer into a synthesis page for the wiki. Keep every citation link. "
        "Link only slugs in <linkable_pages>. Choose a concise descriptive title.\n\n"
        f"<linkable_pages>\n{linkable}\n</linkable_pages>\n\nQuestion: {question}\n\n<answer>\n{answer}\n</answer>"
    )


# ---------- lint ----------

LINT_SCHEMA = {
    "type": "object",
    "properties": {
        "contradictions": {
            "type": "array",
            "items": {"type": "object", "properties": {"pages": {"type": "array", "items": {"type": "string"}}, "description": {"type": "string"}}, "required": ["pages", "description"]},
        },
        "stale_claims": {
            "type": "array",
            "items": {"type": "object", "properties": {"slug": {"type": "string"}, "description": {"type": "string"}}, "required": ["slug", "description"]},
        },
        "missing_pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string"}, "title": {"type": "string"},
                    "type": {"type": "string", "enum": ["topic", "concept", "entity", "comparison"]},
                    "reason": {"type": "string"}, "mentioned_in": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["slug", "title", "type", "reason", "mentioned_in"],
            },
        },
        "missing_links": {
            "type": "array",
            "items": {"type": "object", "properties": {"from_slug": {"type": "string"}, "to_slug": {"type": "string"}, "reason": {"type": "string"}}, "required": ["from_slug", "to_slug", "reason"]},
        },
        "questions": {"type": "array", "items": {"type": "string"}, "description": "Good questions to investigate next"},
        "sources_to_find": {"type": "array", "items": {"type": "string"}, "description": "Sources that would fill gaps"},
    },
    "required": ["contradictions", "stale_claims", "missing_pages", "missing_links", "questions", "sources_to_find"],
}


def lint_prompt(pages_md: str, index: str) -> str:
    return (
        "Health-check these wiki pages. Report: contradictions between pages; stale claims superseded by other pages; "
        "important concepts/entities mentioned but lacking their own page (not already in the index); missing cross-references "
        "between existing pages (both slugs must exist in the index); good questions to investigate; sources that would fill gaps. "
        "Only report real, specific issues.\n\n"
        f"<index>\nslug | type | title | summary\n{index}\n</index>\n\n<pages>\n{pages_md}\n</pages>"
    )


def add_links_prompt(slug: str, content_md: str, targets: str) -> str:
    return (
        f"Edit the wiki page `{slug}` minimally to add links to the pages below where they fit naturally "
        "(link an existing mention, or add a short sentence or a `## Related` entry). Do not change anything else.\n\n"
        f"<links_to_add>\n{targets}\n</links_to_add>\n\n<current_page>\n{content_md}\n</current_page>"
    )
