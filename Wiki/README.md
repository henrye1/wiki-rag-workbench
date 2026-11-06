# LLM Wiki API

An implementation of the LLM Wiki pattern described in `llm-wiki.md`. When you add a source, the LLM folds it into a persistent wiki of interlinked markdown pages. It doesn't re-derive answers from the raw documents every time. The service is a FastAPI app using Gemini, with all state in Postgres (the `wiki` schema in the same local Supabase DB as `Rag/`). The app keeps no state of its own, so it's ready to deploy later.

## Setup
```powershell
cd Wiki
npx supabase start                      # from Rag/ — shared local DB (127.0.0.1:54322)
python -m venv .venv; .venv\Scripts\pip install -r requirements.txt
copy .env.example .env                  # set API_KEY, GEMINI_API_KEY
.venv\Scripts\python -m app.migrate     # creates/updates the wiki schema (any Postgres + pgvector)
.venv\Scripts\python run.py             # http://127.0.0.1:8001 (use run.py, not uvicorn: Windows event loop)
```
- Swagger: http://127.0.0.1:8001/docs
- Viewer: http://127.0.0.1:8001/view (public, read-only)
- Postman: import `postman/LLM_Wiki.postman_collection.json` and set the `apiKey` variable.
- Every API route needs the `X-API-Key` header except `/view` and `/health`.

## Concepts
- **Wiki**: an independent knowledge base. You can have several, each with its own **schema** (the conventions doc every LLM call follows; edit it with `PUT /wikis/{w}/schema`). A new wiki uses `schemas/ifrs9-schema-3.17.md` unless you give one. A schema must have a Checks section and fixed sections (`### 01. <name>`); creating a wiki or saving a schema without them is refused (422). Older schema versions are kept in `archive/schemas/` at the repo root.
- **Source**: raw, immutable input (PDF, DOCX, MD/TXT, URL or pasted text). IFRS-layout PDFs reuse the Rag paragraph parser (Standards, and their Parts B and C by IE / IG / BC… / DO numbering); a PDF whose layout is not recognised is kept page by page and the upload returns a warning.
- **Page**: an LLM-maintained markdown page with a type (overview, topic, concept, entity, comparison, synthesis or source). Links use `[[slug]]` or `[[slug|label]]`. Every change is stored as a version.
- **Changeset**: the proposed page edits from an ingest, a saved query or a lint fix.
- **Saved answer**: a synthesis page filed with Save. It is never one of the pages chosen for a question; up to two saved answers relevant to the question are read in addition, as earlier answers to check against those pages (never cited). Uploads never use synthesis pages as material or rewrite them. When an applied change rewrites what a page says about a paragraph a saved answer cites, the saved answer is flagged **needs checking** (shown on the page, the pages list and the Jobs screen; cleared with *Mark as checked*). A synthesis saved with citation problems (*Save anyway*) is also marked **needs checking** and is not read by Ask or the benchmark until it is saved again with no problems (*Mark as checked* does not clear that).
  - `mode=auto` applies it straight away; `mode=review` leaves it pending.
  - At apply time, an op is skipped as a **conflict** if its page changed after the op was written.
- **Job**: ingest and LLM lint run in the background. Poll `GET /jobs/{id}`. Jobs on the same wiki run one at a time.
- `index.md` and `log.md` are generated from the database, so they're always current.

## Endpoints
| | |
|---|---|
| `POST /wikis`, `GET /wikis`, `GET/DELETE /wikis/{w}` | manage wikis |
| `POST /wikis/{w}/copy` `{slug, name, description?}` | copy a wiki under a new slug: settings, schema, sources, pages with every version, links, flags and search index (no AI calls; the copy's sources share the original's stored files; log, jobs and changesets start empty) |
| `POST /wikis/{w}/summaries` `{dry_run?}` | make every page's summary again by the schema's summary rules from the page text as it stands; no AI calls, no text changes; changed summaries are saved as new page versions |
| `GET/PUT /wikis/{w}/schema` | conventions doc (PUT refuses a schema with no Checks section or no fixed sections) |
| `POST /wikis/{w}/sources?mode=` | upload file → `{job_id}` |
| `POST /wikis/{w}/sources/url?mode=`, `/sources/text?mode=` | ingest a URL / pasted text |
| `GET /wikis/{w}/sources`, `GET/DELETE /wikis/{w}/sources/{slug}` | raw sources |
| `POST /wikis/{w}/query` `{question, save?, mode?, sources?, use_saved?}` | cited answer; `save` files it as a synthesis page; `sources`: `all` (default) or `standard` (only statements cited to a Standard, Part A); `use_saved` (default true): also read relevant saved answers |
| `POST /wikis/{w}/query/stream` | SSE events: `token`, `pages`, `done` |
| `POST /wikis/{w}/synthesis/draft` `{chat_id, chat_title, answers}` | one consolidated summary of an Ask chat's wiki answers, with its citation problems; nothing is saved |
| `POST /wikis/{w}/synthesis/check` `{content_md, answers}` | check an edited draft again: citation check, citations not in the wiki answers, missing pages |
| `POST /wikis/{w}/synthesis` | save the draft as a synthesis page (`<framework>-synthesis-<chat id>`, a saved answer); the same chat updates the same page |
| `POST /wikis/{w}/lint` `{llm?, fix?, mode?}` | structural checks run immediately; with `llm` or `fix` it becomes a job |
| `GET /jobs/{id}`, `GET /wikis/{w}/jobs` | job status, progress, result |
| `GET /wikis/{w}/pages`, `GET/PUT/DELETE .../pages/{slug}` | read pages or edit by hand (`base_version` → 409 if stale) |
| `GET .../pages/{slug}/versions[/{v}]`, `POST .../revert/{v}` | page history |
| `GET /wikis/{w}/changesets[?status=pending]`, `GET .../{id}` (with diffs) | review proposed changes |
| `POST .../changesets/{id}/apply[?force=true]`, `/discard` | apply or discard; discarding an ingest frees its source for re-ingest |
| `GET /wikis/{w}/index.md`, `/log.md`, `/export.zip` | export (zip is an Obsidian vault) |

## How the operations work
**Ingest**
1. The source is split into sections of about 3,000 words.
2. Notes are extracted from each section, with the schema: a summary, the claims the source makes, and its entities and concepts; sections blocked by the model are split and retried.
3. Every source paragraph is assigned to exactly one of the schema's fixed sections (`### 01. <name>`): labelled issuer examples to the worked-examples section, the rest by the LLM (with a retry and fallbacks, so none is left out). The job result lists the assignment and any paragraphs the LLM did not assign itself.
4. A plan is made: which pages to create or update. It's based on the index and a hybrid search for the entities found: one page per schema section plus the overview, besides the source page (subtopic pages of split sections come on top). Every schema section gets a page; `overview` is the only top-level page.
5. The source page and the planned pages are written. A section page writes up only its own paragraphs (other sections' paragraphs are unnumbered context), long pages are written in parts, own paragraphs a page leaves out get one more writing pass, and any still uncited are listed in the job result (`missed_paragraphs`), not on the page. Links to pages that do not exist become plain text.
6. The changeset is applied or left pending, depending on the mode.

**Query**
1. A search of every page's text gives a shortlist (up to 15 pages, with scores and the passages that matched), shown beside the page list (every page's title and summary).
2. The LLM chooses pages from both, reads them and follows their links, in rounds, until it has enough (at most 6 rounds, 30 pages and 150,000 words).
3. The LLM reads the full pages and answers with `[[slug]]` citations.

**Lint**
- Structural checks: broken links, orphan pages, missing metadata, thin pages, unsourced pages, possible duplicates.
- With `llm`: contradictions, stale claims, missing pages, missing links, questions to investigate, sources to find.
- With `fix`: proposes that each link to a page that does not exist be written as plain text (every page comes from the schema's fixed sections, so lint makes no page); nothing is changed.

## Layout
```
run.py                launcher (Windows-safe event loop), port 8001
migrations/           SQL migrations (python -m app.migrate)
app/main.py           app, auth, lifespan (pool + job recovery)
app/jobs.py           background jobs (DB-persisted, per-wiki serialised)
app/sources/          extraction: pdf/ifrs, docx, text, url
app/wiki/store.py     pages, versions, links, chunks, changesets, index/log
app/wiki/search.py    hybrid search
app/ops/              ingest, query, lint
app/prompts.py        prompts + JSON schemas
app/routers/          API + viewer
app/templates/        viewer HTML
schemas/             wiki schemas: ifrs9-schema-3.17.md (the default for a new wiki), client-schema-1.17.md
```

## Limits / next steps
- Jobs run in-process on a single instance. A restart marks running jobs as failed; scaling out needs an external queue.
- Conflicted ops are skipped, not merged. Re-ingest, or add an LLM "rebase" step.
- Deployment (Dockerfile, hosted Supabase) has been deferred.
