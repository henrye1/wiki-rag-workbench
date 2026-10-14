"""Prompts and JSON schemas for wiki operations. The wiki's own schema doc is always included."""
import re


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
        "- If the schema defines a fixed list of sections, include one page for every section.\n"
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

# An extra pass adds to a written page: same shape, but its text is only the new part (a "full page" description makes
# the model rewrite the whole page instead)
FILL_SCHEMA = {
    **PAGE_SCHEMA,
    "properties": {
        **PAGE_SCHEMA["properties"],
        "content_md": {"type": "string", "description": "ONLY the new text for the requested paragraphs, to be appended to the page"},
    },
}


def write_page_prompt(
    *, slug: str, title: str, ptype: str, focus: str, existing_md: str | None, material: str,
    linkable: str, source_slug: str | None, source_paragraphs: str | None = None,
    background_paragraphs: str | None = None, auto_gaps: bool = False,
    part: tuple[int, int] | None = None, earlier_parts: str = "", fill: bool = False,
) -> str:
    cite = (
        f"The source page is [[{source_slug}]]; cite it exactly as the wiki schema requires. "
        "Only state as fact what the source paragraphs or the Claims in the material support; material listed under Open "
        "questions may be recorded as open questions the source raises, never as facts.\n"
        if source_slug else ""
    )
    if background_paragraphs and source_paragraphs:
        scope = ("Write only about the paragraphs in <source_paragraphs>: they are this page's own section. "
                 "<background_paragraphs> belong to other sections and are context only: never write them up or list them; "
                 "link to the page that covers them instead.\n")
    elif background_paragraphs:
        scope = ("<background_paragraphs> belong to the section pages and are context only: never write them up; "
                 "link to the section page that covers them instead.\n")
    else:
        scope = ""
    gaps = (
        "Every paragraph in <source_paragraphs> is assigned to this page and to no other: write up each one, even where "
        "it seems to sit at the edge of this section; a paragraph left out is missing from the wiki. "
        "Do not write a 'Not yet covered' list; it is added automatically.\n"
        if auto_gaps else ""
    )
    paragraphs = (
        "<source_paragraphs>\nThe source's own text for this page, each paragraph labelled with its [paragraph number], "
        "in document order. Write from these first; use the material for context.\n\n"
        f"{source_paragraphs}\n</source_paragraphs>\n\n"
        if source_paragraphs else ""
    )
    background = (
        "<background_paragraphs>\nContext only, from other sections, unlabelled: they cannot be cited, so nothing from them "
        f"may be written on this page.\n\n{background_paragraphs}\n"
        "</background_paragraphs>\n\n"
        if background_paragraphs else ""
    )
    if fill:
        refs = ", ".join(dict.fromkeys(re.findall(r"^\[([^\]]+)\]", source_paragraphs or "", re.M)))
        current = (
            "This page is already written, but it does not yet cover the paragraphs in <source_paragraphs>. Write only "
            "those paragraphs, to be added to the end of the page: no introduction, no summary, and nothing about any "
            "other paragraph. Use one of the page's headings below or a new one.\n"
            f"Write ONLY about paragraph(s) {refs}: a few sentences each, and every sentence must cite one of them. "
            "Do not rewrite the page or write about any other paragraph.\n"
            f"<page_headings>\n{earlier_parts or '(none)'}\n</page_headings>\n"
        )
    elif part:
        n, total = part
        current = (
            f"This page is long, so it is written in {total} parts. This is part {n} of {total}: write only the content "
            "drawn from the source paragraphs given here. "
            + ("Start the page.\n" if n == 1 else
               "Continue the page: no introduction, and do not restate, summarise or re-head anything already in "
               f"<earlier_parts>.\n<earlier_parts>\n{earlier_parts}\n</earlier_parts>\n")
            + ("" if auto_gaps else "Do not write a 'Not yet covered' list; it is added after all parts are written.\n")
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
        f"Focus: {focus}\n{cite}{scope}{gaps}"
        "Link other pages with [[slug]] using ONLY slugs listed in <linkable_pages>.\n"
        f"{ONE_TOP_PAGE}\n\n"
        f"{current}\n"
        f"<linkable_pages>\n{linkable}\n</linkable_pages>\n\n"
        f"{paragraphs}{background}"
        f"<material>\n{material}\n</material>"
    )


# ---------- ingest: route paragraphs to sections ----------

ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "section": {"type": "integer", "description": "Section number"}},
                "required": ["id", "section"],
            },
        },
    },
    "required": ["assignments"],
}


# ---------- ingest: "also record here" sections (additive) ----------

ALSO_SCHEMA = {
    "type": "object",
    "properties": {"ids": {"type": "array", "items": {"type": "integer"}, "description": "Ids of the paragraphs to also record"}},
    "required": ["ids"],
}


def also_prompt(brief: str, lines: str) -> str:
    return (
        "The section below is an \"also record here\" section: a paragraph stays on its own section's page and is ALSO "
        "recorded here. From the paragraphs below, return the ids of those that contain a presumption, an election, a "
        "policy choice, a judgement or an estimate that the Standard leaves to the entity, as the section brief describes. "
        "Leave out paragraphs that contain none.\n\n"
        f"<section_brief>\n{brief}\n</section_brief>\n\n<paragraphs>\nid | text\n{lines}\n</paragraphs>"
    )


def also_record_prompt(*, slug: str, title: str, items: str, linkable: str, source_slug: str) -> str:
    return (
        f"Add short entries to the wiki page `{slug}` (\"{title}\"). Each paragraph in <paragraphs> is written up in full on "
        "its main page (named after it) and is ALSO recorded here, without repeating it.\n"
        "For each paragraph write exactly ONE line, as a markdown bullet: what the entity decides, presumes, elects or "
        "estimates, in a few words, then a link to its main page, then the paragraph's citation, e.g.\n"
        f"- Policy choice: measure the loss allowance at lifetime expected credit losses: see [[main-page-slug]] [[{source_slug}|5.5.15]]\n"
        "Cite each paragraph exactly as the wiki schema requires, with its paragraph number. Nothing else: no heading, no "
        "introduction, no full restatement.\n\n"
        f"<linkable_pages>\n{linkable}\n</linkable_pages>\n\n<paragraphs>\n{items}\n</paragraphs>"
    )


def route_prompt(briefs: str, lines: str, outline: str = "", note: str = "") -> str:
    return (
        "Assign each source paragraph to the ONE section whose brief says it belongs there (follow the briefs' hand-off "
        "rules). That section's page is the only one that writes it up. Return every id exactly once, with its section number. "
        "Keep a topic together: paragraphs under the same heading, and application guidance (B paragraphs) with the "
        "chapter its number points to (B6.x goes with chapter 6), go to the same section unless a brief hands one off.\n"
        f"{note}\n"
        + (f"<source_outline>\nNumbered headings of the source:\n{outline}\n</source_outline>\n\n" if outline else "")
        + f"<section_briefs>\n{briefs}\n</section_briefs>\n\n<paragraphs>\nid | heading | text (first words)\n{lines}\n</paragraphs>"
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
