# IFRS Workbench Guide

The IFRS Workbench compares two ways of answering IFRS 9 questions with an LLM, retrieval over the Standard (RAG) and an LLM-maintained wiki, and scores both against human-written answers. This guide explains how each part works and how to run and use it.

## What it is

Four parts work together; each runs as its own service and can be used on its own.

| Part | Folder | Port | What it does |
| --- | --- | --- | --- |
| RAG API | `Rag/` | 8000 | Indexes documents into searchable chunks and answers questions by retrieving the most relevant paragraphs at query time. Built for IFRS standards: chunks follow paragraph numbers (5.5.3, B5.5.17) and answers cite them. |
| LLM Wiki API | `Wiki/` | 8001 | Has the LLM read each source once and compile it into a persistent, interlinked wiki of markdown pages. Questions are answered from the wiki pages, which keep improving as sources are added and lint fixes run. |
| Benchmark | `Benchmark/` | CLI | Sends the 26 topics of the IFRS 9 requirement query set to both systems and has Claude grade each answer blind against a human-written assessment. |
| Workbench UI | `UI/` | 8080 | A browser app over all three: ask both systems side by side, manage documents and the wiki, run bulk requirement blocks and benchmarks, and explore the results. |

The question they answer together: does a pre-compiled wiki beat plain retrieval for regulatory Q&A? On the first full benchmark (26 topics, 3 runs) RAG scored 3.8/10 and the Wiki 2.7/10 for similarity to the human answers; RAG won 54 of 78 runs. The Wiki then held only 16 pages from one ingest, so the comparison is worth repeating as it grows.

Both systems answer with the same Google Gemini model (`gemini-2.5-flash`) and embeddings (`gemini-embedding-001`, 768 dimensions). Claude (`claude-opus-5-5`) is used only as the benchmark judge. All data lives in one local Supabase Postgres database with pgvector.

## At a glance

```mermaid
flowchart TB
    you["You, in a browser<br/>http://127.0.0.1:8080"]
    tester["A tester, via Cloudflare<br/>quick-tunnel link + password"]
    bff["UI server (BFF), port 8080<br/>serves the Angular app; holds the API keys and the login<br/>proxies RAG and Wiki; runs bulk jobs and benchmarks"]
    rag["RAG API, port 8000<br/>chunks by paragraph number<br/>hybrid search, cites [5.5.3]"]
    wiki["Wiki API, port 8001<br/>LLM-written, linked pages<br/>answers cite wiki pages"]
    bench["Benchmark (CLI)<br/>asks RAG and Wiki the same topics<br/>Claude grades blind"]
    gemini["Google Gemini<br/>answers and embeddings"]
    claude["Claude (Anthropic)<br/>benchmark judge only"]
    db[("Supabase Postgres + pgvector, in Docker<br/>RAG: documents and chunks with embeddings<br/>wiki schema: pages, versions, links, jobs, changesets")]

    you --> bff
    tester --> bff
    bff --> rag
    bff --> wiki
    bff --> bench
    rag --> gemini
    wiki --> gemini
    bench --> claude
    rag --> db
    wiki --> db
```

The browser only ever talks to the UI server, which adds the API keys and forwards requests. RAG and the Wiki share one Supabase database (separate schemas) and the same Gemini models; Claude is used only to judge benchmark answers.

## Quick start

Start five things in order (database, RAG, Wiki, UI server, then open the browser); each Python service runs in its own PowerShell window.

**Prerequisites**

- Windows 10/11 (commands below are PowerShell; macOS/Linux work with the usual path changes)
- Python 3.12, Node.js 22+ (for the UI and the Supabase CLI via `npx`)
- Docker Desktop, running (local Supabase runs in Docker)
- A Google Gemini API key ([aistudio.google.com/apikey](https://aistudio.google.com/apikey))
- An Anthropic API key, only for the Benchmark judge
- The source documents in `Docs/` (not in git, see [Repository, data and limits](#repository-data-and-limits)): the IFRS 9 PDF, the requirement query set and the human-written reference assessment

**First-time setup**

1. Database: `cd Rag` then `npx supabase start`. It pulls images on first run, applies the RAG migration and prints the database URL (`postgresql://postgres:postgres@127.0.0.1:54322/postgres`).
2. RAG: in `Rag/`, run `python -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt`, copy `.env.example` to `.env` and set `API_KEY` and `GEMINI_API_KEY`.
3. Wiki: in `Wiki/`, create the venv and install the same way, copy `.env.example` to `.env`, then run `.venv\Scripts\python -m app.migrate` once to create the `wiki` schema.
4. Benchmark: in `Benchmark/`, create the venv, copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`, the two API keys and `REFERENCE_DOCX`.
5. UI: in `UI/server/` create the venv and `.env` (RAG and Wiki API keys); in `UI/web/` run `npm install` then `npm run build`.

**Every time**

1. Docker Desktop running, then `npx supabase start` in `Rag/` (a no-op if already up).
2. In `Rag/`: `.venv\Scripts\python run.py` (port 8000).
3. In `Wiki/`: `.venv\Scripts\python run.py` (port 8001).
4. In `UI/server/`: `.venv\Scripts\python run.py` (port 8080).
5. Open <http://127.0.0.1:8080>.

Always start the Python services with `run.py`, not `uvicorn` directly: on Windows the async database driver needs a selector event loop that `run.py` sets up.

**First data**

1. In the UI, open **RAG documents**, create a collection (for example slug `ifrs9`) and ingest the IFRS 9 PDF into it (about a minute; 927 chunks).
2. Open **Wiki**, create a wiki (for example slug `ifrs9`), go to **Sources & ingest**, upload the same PDF in *Apply automatically* mode and follow the job (a few minutes; about 16 pages).
3. Try **Ask** with a question such as "When must lifetime expected credit losses be recognised?".

## Configuration

Each service reads its own `.env` file (never committed; copy `.env.example`). Only the keys marked required have no default.

| Service | Setting | Default | Purpose |
| --- | --- | --- | --- |
| RAG | `API_KEY` (required) | none | Clients send it as the `X-API-Key` header |
| RAG | `GEMINI_API_KEY` (required) | none | Google Gemini key for embeddings and answers |
| RAG | `DATABASE_URL` | local Supabase `:54322` | Postgres with pgvector |
| RAG | `GEMINI_CHAT_MODEL` / `GEMINI_EMBED_MODEL` | `gemini-2.5-flash` / `gemini-embedding-001` | Models; change in one place |
| RAG | `TOP_K`, `CHUNK_MAX_WORDS`, `TEMPERATURE` | 8, 500, 0.1 | Passages per answer, chunk size, sampling |
| RAG | `BULK_CONCURRENCY`, `BULK_K_PER_QUERY`, `BULK_MAX_CHUNKS` | 3, 6, 30 | Bulk run parallelism and retrieval budget |
| Wiki | `API_KEY`, `GEMINI_API_KEY` (required) | none | As for RAG |
| Wiki | `DATABASE_URL` | local Supabase `:54322` | Same database, `wiki` schema |
| RAG, Wiki | `SUPABASE_SECRET_KEY`, `SUPABASE_URL`, `STORAGE_BUCKET` | empty, from `DATABASE_URL`, `sources` | Optional: keep each uploaded file in a private Supabase Storage bucket, opened from the UI with **View original** (signed links valid for one hour). Files ingested earlier can be attached with `python -m app.attach_file` in `Rag/` or `Wiki/` |
| Wiki | `MAX_PAGES_PER_INGEST` | 17 | Cap on pages one ingest creates or updates, including the source page (15 sections + overview + source) |
| Wiki | `LLM_CONCURRENCY`, `JOB_WORKERS` | 4, 2 | Parallel LLM calls per job; jobs running at once |
| Wiki | `TEMPERATURE` | 0.2 (set to 0.1 here to match RAG) | Sampling |
| Benchmark | `ANTHROPIC_API_KEY` | none | Claude judge |
| Benchmark | `JUDGE_MODEL`, `JUDGE_EFFORT` | `claude-opus-5-5`, `high` | Judge model and reasoning effort |
| Benchmark | `RAG_URL` / `RAG_API_KEY`, `WIKI_URL` / `WIKI_API_KEY` | `:8000`, `:8001` | Systems under test |
| Benchmark | `RAG_COLLECTION`, `WIKI_SLUG` | none | CLI runs only: the RAG collection and the wiki to compare (UI runs choose them; a resumed run uses what it stored) |
| Benchmark | `REFERENCE_DOCX` | `../Docs/reference_assessment.docx` | Human-written assessment with the reference answers |
| Benchmark | `RUNS`, `CONCURRENCY`, `SEED` | 3, 4, 42 | Repeats per topic, parallel topics, A/B shuffle seed |
| UI server | `RAG_API_KEY`, `WIKI_API_KEY` (required) | none | Keys the server adds when it calls RAG and Wiki |
| UI server | `UI_PASSWORD`, `SESSION_SECRET` | empty | Shared-password login; empty = no login (local use) |
| UI server | `BENCH_DIR`, `DEFAULT_QUERY_SET` | `../../Benchmark`, `../../Docs/...txt` | Where the Benchmark and default query set live |

Paths in `Benchmark/.env` are resolved relative to the `Benchmark/` folder.

## RAG API

The RAG API answers each question from scratch: it finds the paragraphs of the Standard most relevant to the question and asks Gemini to answer from those alone, citing paragraph numbers.

### How ingestion works

1. **Upload** a PDF, TXT or MD file. Duplicates are rejected by file hash (409).
2. **Parse.** IFRS-layout PDFs are detected automatically and parsed by layout, not by plain text:
   - Paragraph numbers in the left margin (1.1, 5.5.3, B5.5.17) start new chunks, so every chunk is one paragraph of the Standard.
   - Appendix A defined terms become chunks keyed `Appendix A: <term>`.
   - Editorial material ([Refer], [Note], [Link] boxes, IFRIC agenda decisions, E-footnotes) is separated from the binding text and stored as `note` chunks.
   - Each chunk is tagged with a source type: `standard`, `appendix_a`, `appendix_b` (Application Guidance), `note`, `intro`, `appendix_c` or `back_matter`.
   - Paragraphs longer than 500 words are split at sentence boundaries.
   - Other PDFs and text files are split into overlapping ~400-word windows (`general`).
3. **Embed** each chunk with Gemini (768-dimension vectors) and store it in Postgres with a full-text index.

The IFRS 9 PDF yields 927 chunks: 256 Standard, 338 Application Guidance, 30 defined terms and 298 editorial notes.

### How answering works

1. **Hybrid search.** The question is embedded and matched two ways: vector similarity and keyword full-text search. The two rankings are merged with reciprocal rank fusion. Editorial notes, introduction pages and Appendix C are excluded unless you ask for them (`include_editorial` or `source_types`).
2. **Answer.** The top 8 passages go to Gemini, each labelled with its citation key (for example `[5.5.3]`). The prompt requires every statement to be supported by a passage, every if/unless condition to be kept, and citations to copy the key exactly.
3. **Citations.** The response lists the passages the answer actually cited, with paragraph, page, source type and a snippet.

### Bulk requirement runs

`POST /collections/{c}/bulk` takes a query-set file made of `TOPIC n of N:` blocks (title, row label, word guide, leave-out line, search terms, questions) plus run rules. For each topic it:

1. Retrieves passages for the search terms and every question, merged round-robin up to 30 passages.
2. Drafts the requirement block as structured JSON: prose paragraphs, source list, not-addressed list.
3. Checks the draft mechanically: paragraph numbers in the prose, word count more than 25% over the guide, source list mismatched to paragraphs, unknown passage ids.
4. Runs a self-check revision pass that fixes the detected issues and re-checks (skip with `revise=false`).

Each topic returns the rendered markdown block, the issues before and after revision, the citations and the word count.

### Endpoints

All require the `X-API-Key` header except `/health`. Interactive docs: <http://127.0.0.1:8000/docs>.

| Method | Path | Purpose |
| --- | --- | --- |
| GET / POST | `/collections` | List collections (with document and chunk counts) / create one `{slug, name, description?}` |
| PATCH / DELETE | `/collections/{c}` | Rename `{name?, slug?, description?}` / delete a collection with its documents, chunks and stored files |
| POST | `/collections/{c}/documents` | Upload a document into a collection (multipart `file`); the same file can be in several collections, once per collection |
| GET | `/collections/{c}/documents` | List a collection's documents with chunk counts (`GET /documents` lists all collections) |
| DELETE | `/documents/{id}` | Remove a document and its chunks |
| GET | `/chunks?para_ref=5.5.3&collection=c` | Look up a paragraph by its reference (used by citation viewers); `collection` optional |
| POST | `/collections/{c}/query` | `{question, top_k?, source_types?, include_editorial?}` returns `{answer, citations}`, searching only that collection |
| POST | `/collections/{c}/query/stream` | Same, streamed as server-sent events: `token`, `citations`, `done` |
| POST | `/collections/{c}/bulk?topics=1&revise=true` | Run a query-set file (multipart `file`) on one collection |
| POST | `/bulk/parse` | Dry run: show how a query-set file parses, no LLM calls |
| GET | `/health` | Database check |

A Postman collection is in `Rag/postman/`.

## LLM Wiki

The Wiki does the reading once: when a source is added, the LLM turns it into wiki pages and keeps those pages current, so questions are answered from a compiled, cross-linked knowledge base instead of raw chunks. It implements the LLM Wiki pattern described in `Wiki/llm-wiki.md`, for any domain.

### Concepts

| Concept | What it is |
| --- | --- |
| Wiki | An independent knowledge base with its own slug (for example `ifrs9`). You can run several. |
| Schema | The wiki's conventions document, sent with every LLM call: page types, `[[slug]]` link syntax, how to cite sources, how to flag contradictions. A generic default is used until you edit it. |
| Source | A raw, immutable input: PDF, DOCX, MD/TXT, URL or pasted text. Each source also gets a source page (`source-<name>`). |
| Page | An LLM-written markdown page with a type: overview, topic, concept, entity, comparison, synthesis or source. Every change creates a new version. |
| Links | `[[slug]]` or `[[slug\|label]]`. Links to pages that do not exist yet are allowed and reported by lint as broken links. |
| Changeset | A set of proposed page edits from an ingest, a saved answer or a lint fix. In *auto* mode it is applied at once; in *review* mode it waits for you to apply or discard it. |
| Conflict | When a changeset is applied, any edit to a page that changed after the edit was written is skipped instead of overwriting the newer content. |
| Job | Ingest and LLM lint run in the background; each has a status, a progress stage and a result. Jobs on the same wiki run one at a time. |
| Index and log | `index.md` (every page with a one-line summary, by type) and `log.md` (dated record of ingests, queries, lint runs and edits), generated from the database. |

### Ingest

1. **Extract.** The source becomes text split into sections of about 3,000 words. IFRS PDFs reuse the RAG paragraph parser and keep only binding text.
2. **Notes.** Each section is summarised, following the schema, into claims the source asserts, open questions it only poses, and entities and concepts. Questions are never turned into claims, so a questionnaire produces open questions, not facts. A section the model refuses to process (Gemini blocks verbatim reproduction of copyrighted text) is split in half and retried.
3. **Route.** If the schema defines fixed sections (`### 01. <name>` briefs), every source paragraph goes to exactly one section. Paragraphs carrying an issuer example label ("Example 1", "Instrument A", "Scenario 2") go to the worked-examples section, and nothing else does. The LLM assigns the rest, following the briefs' hand-off rules and seeing each paragraph's heading and the source's numbered outline, so a topic such as hedge accounting (chapter 6 and B6) stays together. Paragraphs it misses get a second round; any still missing go where most of their paragraph group went, else to the closest section brief. The job result lists which paragraphs went where (`routing`) and any the LLM did not assign itself (`unassigned`).
4. **Plan.** The LLM sees the schema, the current index and the existing pages most related to the new material, and picks the pages to create or update. Every schema section gets a page and `overview` is the only top-level page; the source page counts toward the limit of 17.
5. **Write.** The source page and each planned page are written in parallel. A section page writes up only its own paragraphs, cited by paragraph number; a few related paragraphs from other sections come without numbers, as context only. Long pages are written in parts of about 4,000 source words, each part seeing the earlier ones, and repeated blocks are dropped. Every own paragraph must be written up; any the page still does not cite get one more writing pass, and the page ends with a "Not yet covered" list of its own paragraphs it still does not cite. A section with no paragraphs gets a one-line empty page (an existing page is left as it is). Links to pages that do not exist become plain text. Updated pages keep their existing correct content; contradictions are flagged with a `> [!warning] Contradiction` callout naming both sources.
6. **Commit.** The edits become a changeset: applied now (*auto*) or left pending (*review*). Applying stores versions, rebuilds links and search chunks, and records which sources each page draws on.

The IFRS 9 PDF (26 sections) produces 17 pages.

### Query

1. Hybrid search over page chunks finds related pages; the LLM also picks pages from the index.
2. Up to about 8 full pages are read, with the schema, and the answer cites them as `[[slug]]`.
3. With `save: true`, the answer is filed back as a synthesis page, so good answers become part of the wiki.

### Lint

- **Structural** (instant, no LLM): broken links, orphan pages with no inbound links, missing summary or tags, thin pages, pages that cite no source, possible duplicate titles.
- **LLM health-check** (job): contradictions between pages, stale claims, missing concept pages, missing cross-links, questions worth investigating and sources that would fill gaps.
- **Fix** (job): writes pages for broken links and missing concepts from what the wiki already says, adds missing links and links orphan pages, up to 15 pages per run, as a changeset.

### Endpoints

All require `X-API-Key` except `/health` and the HTML viewer. Interactive docs: <http://127.0.0.1:8001/docs>.

| Method | Path | Purpose |
| --- | --- | --- |
| POST / GET | `/wikis` | Create (`slug`, `name`, `description`, optional `schema_md`) / list wikis |
| GET / DELETE | `/wikis/{w}` | Read / delete a wiki and everything in it |
| GET / PUT | `/wikis/{w}/schema` | Read / replace the conventions document |
| POST | `/wikis/{w}/sources?mode=auto\|review` | Upload a file; returns a `job_id` |
| POST | `/wikis/{w}/sources/url`, `/sources/text` | Ingest a web page or pasted text |
| GET / DELETE | `/wikis/{w}/sources[/{slug}]` | List, read or delete raw sources |
| POST | `/wikis/{w}/query` | `{question, save?, mode?}` returns the answer and the pages read |
| POST | `/wikis/{w}/query/stream` | Streamed answer: `token`, `pages`, `done` events |
| POST | `/wikis/{w}/lint` | `{llm?, fix?, mode?}`; structural is instant, with `llm` or `fix` returns a `job_id` |
| GET | `/jobs/{id}`, `/wikis/{w}/jobs` | Job status, progress and result |
| GET / PUT / DELETE | `/wikis/{w}/pages[/{slug}]` | List, read, hand-edit (`base_version` gives 409 if stale) or delete pages |
| GET / POST | `/pages/{slug}/versions[/{v}]`, `/revert/{v}` | Page history and revert |
| GET / POST | `/wikis/{w}/changesets[/{id}]`, `/apply`, `/discard` | Review diffs; apply (optionally `force`) or discard |
| GET | `/wikis/{w}/graph` | Nodes and links for the graph view |
| GET | `/wikis/{w}/index.md`, `/log.md`, `/export.zip` | Index, log and an Obsidian-compatible vault |
| GET | `/view/{w}[/{slug}]` | Read-only HTML viewer |

A Postman collection is in `Wiki/postman/`.

## Benchmark

The Benchmark measures how close each system's answers are to a human expert's, topic by topic, with Claude as a blind judge.

### Method

1. **Inputs.** Each of the 26 topics in the query set is sent as its title plus its questions (Q1 to Qn), identically, to RAG `/collections/{c}/query` and Wiki `/wikis/{w}/query`, for the RAG collection and wiki chosen for the run.
2. **Reference.** Each topic's reference answer is the first row of its table in the human-written assessment (tables 1 to 26 map to topics 1 to 26; `python -m bench.data` checks the mapping by title).
3. **Rubric.** Claude breaks each reference into atomic key points, once per topic, and tags each as `standard` (from the IFRS 9 or IFRS 7 text) or `beyond_standard` (industry practice, ITG or Basel guidance, examples). Neither system has the beyond-standard material, so scores are reported both ways.
4. **Blind grading.** The two answers are labelled A and B in a seeded random order each run. Claude grades every key point for each answer as full, partial or missing, scores overall similarity 0 to 10, lists contradictions with the reference, and picks a winner.
5. **Scores.** Coverage = (full + 0.5 x partial) / key points; standard-only coverage uses only `standard` points. Each topic is run 3 times and averaged; the summary averages the topics.

### Running it

From `Benchmark/` with RAG and Wiki running:

- `.venv\Scripts\python -m bench.run --topics 2 --runs 1` for a quick check (about a minute)
- `.venv\Scripts\python -m bench.run` for the full run (26 topics x 3 runs: about 100 Claude calls and 156 Gemini calls, roughly 10 minutes)
- `--topics 1,4,10-12` selects topics; `--run-id <id>` resumes a run that stopped
- Or start runs from the UI's Benchmark screen: upload the reference .docx and the query set (later runs reuse the last uploaded files), watch progress, resume interrupted runs
- First time: `.venv\Scripts\python -m bench.migrate` creates the `bench.runs` table; `python -m bench.import_results results\<folder>` imports runs saved by older versions

Results are stored in the database (`bench.runs`, one row per run, together with the uploaded inputs and the run log): the configuration (models, document and page counts, git commit), each topic's key points, every answer with its grades and the judge's notes, and per-topic and overall averages.

### Latest full run (2026-10-08)

| System | Similarity (0-10) | Coverage, all points | Coverage, Standard-only points | Runs won (of 78) | Average answer time |
| --- | --- | --- | --- | --- | --- |
| RAG | 3.8 | 30% | 61% | 54 | 9 s |
| Wiki (16 pages) | 2.7 | 20% | 48% | 17 | 17 s |

7 runs were ties. RAG led most on the effective interest rate (6.0 vs 1.0), collective assessment (6.7 vs 1.0) and modified assets not derecognised (6.0 vs 2.0), where the Wiki had no dedicated page and said its pages did not cover the point. The Wiki won on post write-off recoveries, LGD term structure, EAD segmentation and forward-looking PD.

### Reading the scores

- Absolute scores are low partly because the human answers include practice and supervisory guidance that is not in the Standard (topic 26, validation, has no Standard points at all). Standard-only coverage is the fairer measure of retrieval quality.
- The human answers also contain points that a topic's "Leave out" line excludes, which lowers both systems equally.
- The Wiki's score depends on how many pages it has. Growing it with lint and fix, then re-running, tests whether a compiled wiki closes the gap.

## Workbench UI

The Workbench is the easiest way to use everything: open <http://127.0.0.1:8080> and pick a screen from the left menu. It is an Angular app served by a small Python server (the BFF) that holds the API keys, so the browser never sees them.

### Screens

| Screen | What you can do |
| --- | --- |
| Home | See whether RAG, Wiki and the Benchmark are up, with document, page and latest score counts |
| Ask (side by side) | Ask one question to RAG and the Wiki at once and watch both answers stream in. Tick either system off to ask only one. |
| RAG documents | Create, rename and delete collections; upload documents into the chosen collection by drag and drop, see chunk counts by source type, delete documents |
| Bulk requirements | Run requirement blocks for chosen topics through the RAG bulk pipeline and copy each finished block as markdown |
| Wiki | Create or select a wiki, then work in its tabs (below) |
| Benchmark | Start runs, watch progress, explore results, drill into topics and compare runs |

**Wiki tabs**

| Tab | What you can do |
| --- | --- |
| Pages | Filter pages by type or text; open a page to read it, see what links to it and which sources it uses, compare any version with the current one and revert |
| Sources & ingest | Add a file, URL or pasted text, choosing *Review changes first* or *Apply automatically*; delete raw sources |
| Jobs | Follow ingest and lint jobs live; open a finished job to reach its changeset or pages |
| Changesets | Review proposed edits as diffs (new pages are shown rendered), then apply or discard; stale edits are flagged |
| Lint | Run the instant structural check, the LLM health-check, or the check plus fixes |
| Graph | See pages as a link map: colour = page type, size = inbound links, red ring = orphan; tick to show pages linked but not yet written; click a page to open it |
| Schema & export | Edit the wiki's conventions; download the Obsidian vault, index.md or log.md |

### Common tasks

**Compare the two systems on a question**

1. Open **Ask**, type the question, keep both boxes ticked, press **Ask** (or Ctrl+Enter).
2. Click a blue citation chip such as `5.5.19` in the RAG answer to open that paragraph of the Standard in the side panel.
3. Click a page link in the Wiki answer to preview that page in the side panel; **Open page** goes to it.
4. If the Wiki answer is good, **Save answer as wiki page** files it as a synthesis page.

**Add a source to the wiki and check the changes first**

1. **Wiki** > your wiki > **Sources & ingest**, choose *Review changes first*, add the file.
2. Follow the job in **Jobs**; when it succeeds, open it and click **review N change(s)**.
3. Expand each change to read the diff, then **Apply** or **Discard**. Discarding an ingest also removes its source so it can be re-ingested.

**Grow the wiki**

1. **Lint** > choose *Apply fixes* > **LLM check + fix**.
2. When the job finishes, check **Graph**: new pages appear and broken links shrink. Each run writes up to 15 pages.

**Run and read a benchmark**

1. **Benchmark** > enter topics (empty = all 26) and runs > **Start**; the progress bar counts judged answers.
2. Open the run: summary cards, a by-section chart, and a topic table you can sort by the gap between the systems.
3. Click a topic for the grid of key points by grade (hover a cell for the judge's note), both answers side by side per run, the winner and the judge's reasoning.
4. Tick two runs on the Benchmark list and **Compare selected** to see per-topic changes.

### Development mode

For UI changes with hot reload, run `npm start` in `UI/web/` and open <http://localhost:4200>; it forwards `/api` and `/view` to the server on port 8080. After changes, `npm run build` updates what port 8080 serves.

## Sharing with a tester

A Cloudflare quick tunnel gives someone outside your network a temporary HTTPS link to your running Workbench, protected by a shared password. No Cloudflare account is needed.

1. Set a password: in `UI/server/.env`, set `UI_PASSWORD` (and a long random `SESSION_SECRET`), then restart the UI server. With a password set, the app shows a sign-in screen and every `/api` and `/view` request needs a login. Wrong guesses are slowed down; a session lasts 7 days.
2. Keep everything running on your machine: Docker and Supabase, RAG, Wiki and the UI server, with the UI built (`npm run build`).
3. Start the tunnel in PowerShell: `& "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --no-autoupdate --url http://127.0.0.1:8080`. It prints a `https://<random-words>.trycloudflare.com` link.
4. Send the tester the link and the password separately.
5. To stop sharing, close the tunnel (Ctrl+C). The link changes every time the tunnel starts.

Things to know:

- Anyone with the password has full access, including deleting documents and wikis and running benchmarks, which spend your Gemini and Claude credits. There is no automatic backup of the local database.
- Cloudflare ends any single request after about 100 seconds. Streamed answers and background jobs are unaffected; uploading a very large document to RAG could time out.
- Quick tunnels are for testing. For a stable address, use a named tunnel on your own domain with Cloudflare Access email login.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Docker Desktop is unable to start` | WSL2 not ready after install | Restart Windows; if it persists run `wsl --update` and check virtualization is enabled in the BIOS |
| A service starts but `/health` hangs, log shows `ProactorEventLoop` | Started with `uvicorn` directly on Windows | Start it with `python run.py` |
| `/health` returns 500 or connection refused | Supabase is not running | `npx supabase start` in `Rag/` |
| Home shows RAG or Wiki down | That service is not running or its key in `UI/server/.env` is wrong | Start it; copy its `API_KEY` into the UI server's `.env` and restart the UI server |
| Every page in the UI shows the sign-in screen | `UI_PASSWORD` is set | Sign in, or clear `UI_PASSWORD` for local use |
| "UI not built" on port 8080 | No production build yet | `npm run build` in `UI/web/` |
| Ingest to RAG returns 409 | That exact file was already ingested | Delete the document first if you want to re-ingest it |
| Wiki ingest returns 409 for a source | Same text already ingested into that wiki | Delete the source (or discard its changeset), then re-ingest |
| Wiki job shows "failed sections" with RECITATION | Gemini refused to reproduce copyrighted text verbatim | Usually resolved by the automatic split-and-retry; the rest of the ingest still succeeds |
| Changeset apply reports conflicts | Those pages changed after the changeset was written | Re-ingest the source, or apply with force only if you accept overwriting |
| Wiki answers "the pages do not cover this" | The wiki has no page on that topic yet | Run lint with fix, ingest more sources, or check the Graph for missing pages |
| Benchmark fails at start: topic does not match heading | Wrong or missing `REFERENCE_DOCX` | Point `REFERENCE_DOCX` in `Benchmark/.env` at the assessment; check with `python -m bench.data` |
| Benchmark judge errors with authentication | No Anthropic key | Set `ANTHROPIC_API_KEY` in `Benchmark/.env` |
| Gemini 429 errors | Rate limit | Calls retry with backoff automatically; lower `BULK_CONCURRENCY`, `LLM_CONCURRENCY` or `CONCURRENCY` |

## Deploying to Render

See [DEPLOY.md](DEPLOY.md): a Render Blueprint (`render.yaml`) runs the Workbench publicly and RAG and Wiki as private services, on a Supabase Cloud database.

## Repository, data and limits

The code is at [github.com/henrye1/wiki-rag-workbench](https://github.com/henrye1/wiki-rag-workbench). Source documents are deliberately not in it.

| Folder | Contents |
| --- | --- |
| `Rag/` | RAG API: `app/ingest` (IFRS PDF parser, chunking), `app/retrieval.py`, `app/bulk.py`, `supabase/migrations`, Postman collection |
| `Wiki/` | Wiki API: `app/ops` (ingest, query, lint), `app/wiki/store.py` (pages, versions, changesets), `migrations`, HTML viewer templates, `llm-wiki.md` (the pattern it implements) |
| `Benchmark/` | `bench/` (data loading, system clients, Claude judge, runner); results are stored in `bench.runs` |
| `UI/web/` | Angular app: `pages/` (one file per screen), `shared/` (markdown rendering, citation panel, diff viewer) |
| `UI/server/` | BFF: proxy, login, bulk runner, benchmark runner |
| `Docs/` | Local only, ignored by git: the IFRS 9 PDF, the query set and the reference assessment |

**Data handling**

- `Docs/` is in `.gitignore`: the IFRS Foundation text is copyrighted and the assessment is client material. Anyone cloning the repo supplies their own documents.
- Every `.env` file is ignored. API keys and the UI password live only on the machine running the services.
- All indexed content, wiki pages and versions live in the local Supabase database. Stopping Supabase keeps the data; `npx supabase db reset` wipes it.

**Known limits**

- Built and tested for local use on one machine; deployment (containers, hosted database, proper user accounts) is not set up yet.
- Wiki jobs and UI bulk runs live in the running process: a restart marks running Wiki jobs as failed and forgets UI bulk results.
- Conflicting changeset edits are skipped, not merged.
- The Wiki currently holds 16 pages from one ingest; 131 linked pages are still unwritten (visible in the Graph).
- IFRS 7 is referenced by the query set but not ingested, so disclosure questions (topic 26) are only partly answerable.
