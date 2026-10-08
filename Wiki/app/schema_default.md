# Wiki schema

This document tells the wiki maintainer (the LLM) how this wiki is structured. Edit it to fit the domain.

## Purpose
A persistent, interlinked knowledge base compiled from the sources added to it. Pages are written and maintained by the LLM; humans curate sources and ask questions.

## Page types
- **overview** — the single top-level page (`overview`) describing what the wiki covers and its main threads.
- **source** — one per ingested source (`source-<name>`): what it is, key takeaways, which pages it informed.
- **entity** — a specific thing: organisation, person, product, standard, document, instrument.
- **concept** — an idea, term, rule, method or definition.
- **topic** — a broader theme that ties several entities/concepts together.
- **comparison** — a side-by-side analysis of two or more things.
- **synthesis** — an analysis or answer filed back from a query.

## Slugs and links
- Slugs are lowercase kebab-case, unique, stable (e.g. `expected-credit-losses`). Never rename an existing slug.
- Link to other pages with `[[slug]]` or `[[slug|display text]]`. Link the first mention of every entity/concept that has (or should have) a page.
- Cite sources by linking their source page, e.g. `[[source-ifrs-9]]`, right after the claim they support.

## Page content
- Start with a one-paragraph definition/summary, then sections with `##` headings.
- Only state what the sources support. Attribute claims to sources.
- Keep pages focused; split when a page covers several distinct things.
- End with a `## Related` list of links where useful.

## Contradictions and updates
- When a new source contradicts an existing claim, keep both and flag it:
  `> [!warning] Contradiction: <source A> says X; <source B> says Y.`
- When a newer source supersedes a claim, update the text and note what changed and why.

## Style
- Plain, precise language. No filler. Prefer short paragraphs and lists.
