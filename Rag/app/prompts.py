QUERY_SYSTEM = """You answer questions using ONLY the passages provided in <context>.
Rules:
- Every statement must be supported by a passage. Do not use general knowledge.
- Each passage starts with its citation key in square brackets, e.g. [5.5.3], [B5.5.17], [Appendix A: credit loss].
- Cite inline by copying that key exactly, including the brackets, e.g. [5.5.3]. Cite several as [5.5.3][B5.5.17]. Never invent or alter keys, never cite page numbers.
- When the Standard allows or requires something only "if", "provided that", "unless" or "only when", state every condition in full.
- If the passages do not answer the question, say so plainly rather than guessing.
- Be concise."""


def query_prompt(question: str, context: str) -> str:
    return f"<context>\n{context}\n</context>\n\nQuestion: {question}"


BULK_SYSTEM = """You write IFRS requirement blocks using ONLY the passages provided in <context>.
The passages are the binding text of the Standard. Follow the run rules and the topic instructions exactly.
Do not use general knowledge. If a question cannot be answered from the passages, list it as not addressed.
Return JSON matching the schema. Do not put IFRS paragraph numbers in the prose; put them in the source list."""

BULK_SCHEMA = {
    "type": "object",
    "properties": {
        "prose_paragraphs": {
            "type": "array",
            "description": "Requirement text, one string per prose paragraph, no IFRS paragraph numbers.",
            "items": {"type": "string"},
        },
        "source_list": {
            "type": "array",
            "description": "One row per prose paragraph, same order.",
            "items": {
                "type": "object",
                "properties": {
                    "para": {"type": "integer", "description": "1-based prose paragraph number"},
                    "covers": {"type": "string", "description": "What it covers, a few words"},
                    "ifrs_paragraphs": {"type": "array", "items": {"type": "string"}},
                    "passage_ids": {"type": "array", "items": {"type": "string"}, "description": "Passage ids, e.g. C123"},
                },
                "required": ["para", "covers", "ifrs_paragraphs", "passage_ids"],
            },
        },
        "not_addressed": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"question": {"type": "string", "description": "e.g. Q3"}, "note": {"type": "string"}},
                "required": ["question", "note"],
            },
        },
        "standard_version": {"type": "string", "description": "Version of the Standard used, if stated in the passages"},
    },
    "required": ["prose_paragraphs", "source_list", "not_addressed"],
}


def bulk_prompt(rules: str, topic_block: str, context: str) -> str:
    return f"<run_rules>\n{rules}\n</run_rules>\n\n<topic>\n{topic_block}\n</topic>\n\n<context>\n{context}\n</context>"


REVISE_INSTRUCTIONS = """Review the draft against EVERY run rule and the SELF-CHECK list, then return the corrected block as JSON. In particular:
- Fix every detected issue.
- Remove any sentence not supported by a passage, and anything covered by the topic's "Leave out" line.
- No IFRS paragraph numbers in the prose; where the Standard names something only by number, use the name it gives it.
- Keep every "if", "provided that", "unless" and "only when" condition in full.
- Aim for roughly the word guide; cut repetition and supporting detail first, never required points or conditions.
- Every question is answered in the prose or listed under not addressed, after searching the passages.
- Source list: exactly one row per prose paragraph, citing only passage ids present in the context."""


def revise_prompt(rules: str, topic_block: str, context: str, draft_json: str, issues: list[str]) -> str:
    found = "\n".join(f"- {i}" for i in issues) or "- (none detected automatically)"
    return (
        f"{bulk_prompt(rules, topic_block, context)}\n\n<draft>\n{draft_json}\n</draft>\n\n"
        f"<detected_issues>\n{found}\n</detected_issues>\n\n{REVISE_INSTRUCTIONS}"
    )
