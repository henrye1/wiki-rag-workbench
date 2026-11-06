# Architecture

A guide for whoever has to fix or change this code. It says what each part does, where each job is done, and the
rules the code keeps. METHODOLOGY.md holds the full detail (every setting, prompt and metric); this file is the map.

## What this is

A workbench that answers questions about an accounting standard in two ways and compares them:

- **Wiki**: an LLM reads the source documents once and writes a wiki of pages, each statement citing the paragraph it
  rests on. Questions are answered by reading the wiki's pages.
- **RAG**: the same documents cut into passages; each question searches the passages and answers from the top hits.
- **Benchmark**: asks both the same questions, has a judge model grade them against a human reference, and reports
  coverage, similarity, contradictions, faithfulness, citation accuracy, length, time and cost.

## The parts

| Part | Folder | Runs as | Port (local) | What it does |
|---|---|---|---|---|
| Wiki API | `Wiki/` | FastAPI | 8001 | Builds wikis from uploads, checks pages, answers questions |
| RAG API | `Rag/` | FastAPI | 8000 | Stores passages, searches them, answers questions |
| Workbench | `UI/server` (FastAPI) + `UI/web` (Angular) | one service | 8080 | The screens; proxies the two APIs; starts benchmark runs |
| Benchmark | `Benchmark/` | a command (`python -m bench.run --run-id …`) | — | Started by the workbench; one process per run |

All four share **one Postgres database** (Supabase): schema `wiki` (wikis, pages, sources, jobs, changesets),
`bench` (runs, rubrics), `ask` (chats) and `public` (RAG collections, documents, chunks). Original uploads are kept
in Supabase Storage. The deployed copy on Render (`render.yaml`, `DEPLOY.md`) uses the **same database** as a local
run: starting a wiki service anywhere fails the jobs running elsewhere, so check `wiki.jobs` and `bench.runs` first.

Each service deploys on its own, so a few small files are copied between them on purpose (`storage.py`, `text.py`,
`migrate.py`, the database-URL cleaner in `config.py`). The RAG's PDF reader (`Rag/app/ingest/pdf_ifrs.py`) is an
older copy of the wiki's; change the wiki's first.

## The rule the wiki keeps: the schema is in charge

Each wiki stores its own **schema**, a Markdown document (`Wiki/schemas/ifrs9-schema-3.17.md`; the client wiki uses
`client-schema-1.17.md`). It says what the wiki's sections are, how pages are written, how answers are laid out, and,
in its **Checks** section, every word and list the engine needs: paragraph kinds, openers, citation forms, force words,
headings and so on.

- **The code does mechanics only.** No standard names, document names, section names, paragraph labels or English
  marker words are written in the code; they are read from the schema's Checks lists (`Wiki/app/wiki/checks.py`
  `load()` turns them into a `Checks` object). If a fix needs a new rule, the rule goes into the schema first, as
  wording the owner approves, and the code reads it.
- **A missing list switches its check off**, and says so in the report (`Checks.missing`, `answer_missing`). The
  client schema lacks many lists; that is how its wiki runs with fewer checks.
- **Every wiki needs a Checks section and a fixed list of sections.** Creating a wiki or replacing its schema refuses
  one without (`Wiki/app/routers/wikis.py`, `schema_problem`). A new wiki gets schema 3.17.
- **One exception, to be moved:** the PDF readers still hold document words (the IE / IG / BC / DO paragraph
  prefixes, the publisher's font names, `KIND_LABELS` in `Wiki/app/sources/extract.py`). They are due to move into a
  reader settings file.

## How an upload becomes pages (Wiki)

Entry: `POST /wikis/{w}/sources` → a background job (`Wiki/app/jobs.py`) → `Wiki/app/ops/ingest.py` `run()`.

1. **Read** the file into labelled passages: `Wiki/app/sources/extract.py` picks the reader (`pdf_ifrs.py` for the
   publisher's PDFs, `docx_reader.py` for Word, plain text otherwise).
2. **Notes** per part of the source (`prompts.notes_prompt`).
3. **Route** every labelled paragraph to one of the schema's sections, in rounds until each is placed.
4. **Plan** the pages: every section page and the overview, plus subtopic pages where a section is split.
5. **Write** each page from its own paragraphs (`prompts.write_page_prompt`), in parts for long pages.
6. **Check and fix**: each page is checked against the schema's lists (`ops/pagecheck.py` → `wiki/checks.py`
   `section_failures`) and sent back at most twice, paragraph by paragraph (`ops/fixpass.py`); a paragraph still failing
   is quoted in full.
7. **Compose** the pages the engine builds itself: concept and entity pages (`ops/concepts.py`), indexes of split
   sections.
8. **Commit** as a changeset (`wiki/store.py` `commit`): applied, or held for review when checks still fail.

`ops/recheck.py` runs steps 6–8 again on an existing wiki without re-reading the sources. `ops/lint.py` runs the
schema's Maintain checks that need no rewrite.

## How a question is answered (Wiki)

Entry: `POST /wikis/{w}/query` (or `/query/stream`) → `Wiki/app/ops/query.py` `answer()`.

1. **Choose pages**: a search of every page's text gives a shortlist (`wiki/search.py`); the model reads the page list
   and shortlist, picks pages, reads them and follows links, in rounds (`_browse`). This is the only method.
2. **Write** the answer. Where the schema has an Answer layout (3.17 does), `query._checked` and `ops/answering.py`
   apply it: the instruction quotes the schema's own answer rules word for word (`checks.rules_using`); each point
   said to be "not addressed" is searched for, term by term, before the answer is final; the answer is checked
   (citations, openers, force words, layout, brief kinds) and sent back once; its Clause references are built by the
   code from the citations that end its sentences. A schema without an Answer layout (the client's) gets a plain
   answer from the pages.
3. **Citations**: a paragraph is cited only by the group of citations that ends a sentence; a link inside a sentence
   is a pointer (`checks.closing_links`).

## RAG

Upload: `Rag/app/routers/documents.py` → `ingest/pipeline.py` (reader, chunks, embeddings). Question:
`Rag/app/routers/query.py` → `retrieval.py` (`hybrid_search` in SQL: full text + vector, merged) → `prompts.py`.
Two ways to search: `whole` (one search, `TOP_K` passages) and `per_question` (one search per numbered question).
`include_editorial` adds the editorial notes and introduction; the benchmark and the Ask screen both send it.

## Benchmark

`Benchmark/bench/run.py` reads its run row from `bench.runs` (set up by the workbench form), then for each topic:
asks the three systems (`systems.py`: `rag`, `rag_q`, `wiki`), builds or reuses the approved rubric (`rubric.py`),
has the judge grade each wiki–RAG pair in both orders (`judge.py`, Anthropic API, Message Batches), and stores the
results. Then the answer checks (`checks.py`), and in Full mode faithfulness and context recall (`context.py`) and
standard-only similarity (`std_similarity.py`). Gaps and their intervals: `gaps.py`. Cost and time: `metrics.py`.
`Benchmark/README.md` explains the settings and commands.

## Where to fix things

| Symptom | Look in |
|---|---|
| A word or label the checks look for is wrong | The schema's Checks section, not the code |
| A paragraph is read wrongly from a PDF | `Wiki/app/sources/pdf_ifrs.py` (then the RAG copy) |
| A paragraph lands in the wrong section | `ops/ingest.py`, routing (step 3) |
| A page fails a check it should pass, or passes one it should fail | `wiki/checks.py` (`section_failures`, `closing_links`, `sentences`) |
| Fix rounds keep or throw away the wrong rewrite | `ops/fixpass.py` (`_fix_blocks`) |
| An answer reads the wrong pages | `ops/query.py` `_browse`, `wiki/search.py`, `prompts.browse_prompt` |
| An answer's layout, openers or citations are wrong | `ops/answering.py` and the schema's Answer workflow |
| A RAG answer misses passages | `Rag/app/retrieval.py`, `Rag/app/routers/query.py` |
| A benchmark score looks wrong | `Benchmark/bench/checks.py`, `context.py`, `judge.py`; METHODOLOGY.md §8 |
| A screen shows the wrong thing | `UI/web/src/app/pages/…`; its data from `UI/server/app/…` |

## Keeping it fixable

- **Plain names, one place per job.** If two places do the same thing, make one call the other.
- **A short "why" comment** where the reason is not obvious from the code.
- **No document words in code** (see above). Tests read their words from the schema too.
- **Schema wording is approved before code that depends on it.**
- **Migrations are history**: add a new numbered file, never edit or delete an old one.
- **Never commit `.env` files.**

## Tests

| Folder | Command | Needs |
|---|---|---|
| `Wiki/` | `.venv/bin/python -m unittest discover tests` | the database, for `test_real_wiki_answers.py` (reads ifrs9-wiki3) |
| `Benchmark/` | `.venv/bin/python -m unittest discover tests` | nothing |
| `UI/web/` | `npx ng build` | node_modules |

## Running locally

Start the RAG (`Rag/run.py`, 8000), the Wiki (`Wiki/run.py`, 8001; set `DB_POOL_MAX=3` against the hosted database)
and the workbench (`UI/server`, 8080). Each reads its own `.env` (see each folder's `.env.example`). See `README.md`.

## Known open items

- The Market risk page on ifrs9-wiki3 keeps one flag (IFRS 7 36 and B23 cited in one sentence).
- Some answers still end with faults the one fix round does not clear: bare "Qn." lines, an uncited "does not
  describe" sentence, "must" written where the paragraph says "shall".
- The PDF readers' document words are to move into a reader settings file.
- Example page titles name only the label (a wording change, not yet approved).
- `wiki.wikis.answer_method` is now always `search_browse`; the column can be dropped once every deployed service runs
  this code.
