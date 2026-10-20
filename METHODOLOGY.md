# Methodology: IFRS Workbench (RAG vs LLM-wiki benchmark)

This document describes the application **exactly as the code is at the commit below**: not as designed, not as planned. Every factual claim cites the file (and where useful the function, constant or line) it comes from. Statements that could not be confirmed from the code are marked **[UNVERIFIED]** with the reason. Where the design intends something the code does not do, §11 says so.

## 0. Pinned state

| | |
|---|---|
| Commit (`git rev-parse HEAD`) | `f5a776be31906d20d2e64e8280f9e291a1c74441` |
| Commit date (`git log -1 --format=%ci`) | 2026-10-20 14:55:54 +0200 |
| Branch | `main` (local; the GitHub default branch may be behind this commit) |
| Working tree (`git status --short`) | **dirty only by untracked files**: ?? .DS_Store; ?? Benchmark_Overview.html; ?? METHODOLOGY.md. `METHODOLOGY.md` itself is added in the commit after this one. No tracked file is modified, so the code described is exactly the commit. |
| Tracked files | 186 (`git ls-files`) |

Confidentiality: the benchmark's human reference document is a client memo. Its file name is never written here; the code itself shows it only as a neutral label such as "Reference memo 1" (§8.5, §9.2). The `Docs/` folder holding source documents is git-ignored (`.gitignore`) and is not part of the codebase described.

## Step 1: Reconnaissance

### Directory tree (tracked files only)

Excludes `node_modules`, `.venv`, `__pycache__`, `.git`, build output and everything in `.gitignore` (only `Docs/` at the root; per-service `.gitignore` files exclude `.env`, `results/`, `dist/`, `.angular/` etc.).

```
├── Benchmark/
│   ├── bench/
│   │   ├── __init__.py
│   │   ├── checks.py
│   │   ├── config.py
│   │   ├── context.py
│   │   ├── data.py
│   │   ├── gaps.py
│   │   ├── import_results.py
│   │   ├── judge.py
│   │   ├── library.py
│   │   ├── metrics.py
│   │   ├── migrate.py
│   │   ├── prices.json
│   │   ├── rubric.py
│   │   ├── run.py
│   │   ├── suggest.py
│   │   └── systems.py
│   ├── migrations/
│   │   ├── 0001_init.sql
│   │   ├── 0002_rag_collection.sql
│   │   ├── 0003_sources.sql
│   │   ├── 0004_rubrics.sql
│   │   ├── 0005_use_saved.sql
│   │   ├── 0006_ask_chats.sql
│   │   ├── 0007_run_mode.sql
│   │   ├── 0008_rubric_review.sql
│   │   ├── 0009_facts.sql
│   │   ├── 0010_rubric_v3.sql
│   │   └── 0011_reference_labels.sql
│   ├── .env.example
│   ├── .gitignore
│   ├── README.md
│   └── requirements.txt
├── Rag/
│   ├── app/
│   │   ├── ingest/
│   │   │   ├── __init__.py
│   │   │   ├── models.py
│   │   │   ├── pdf_ifrs.py
│   │   │   ├── pipeline.py
│   │   │   └── text.py
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── bulk.py
│   │   │   ├── collections.py
│   │   │   ├── documents.py
│   │   │   └── query.py
│   │   ├── __init__.py
│   │   ├── attach_file.py
│   │   ├── bulk.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── llm.py
│   │   ├── main.py
│   │   ├── migrate.py
│   │   ├── prompts.py
│   │   ├── retrieval.py
│   │   └── storage.py
│   ├── postman/
│   │   └── RAG_API.postman_collection.json
│   ├── supabase/
│   │   ├── migrations/
│   │   │   ├── 20261007000000_init.sql
│   │   │   ├── 20261012000000_document_file.sql
│   │   │   └── 20261013000000_collections.sql
│   │   ├── .gitignore
│   │   └── config.toml
│   ├── .env.example
│   ├── .gitignore
│   ├── Dockerfile
│   ├── README.md
│   ├── requirements.txt
│   └── run.py
├── UI/
│   ├── server/
│   │   ├── app/
│   │   │   ├── __init__.py
│   │   │   ├── ask.py
│   │   │   ├── auth.py
│   │   │   ├── bench.py
│   │   │   ├── bulk.py
│   │   │   ├── config.py
│   │   │   ├── main.py
│   │   │   ├── proxy.py
│   │   │   └── rubric_export.py
│   │   ├── .env.example
│   │   ├── .gitignore
│   │   ├── requirements.txt
│   │   └── run.py
│   ├── web/
│   │   ├── .vscode/
│   │   │   ├── extensions.json
│   │   │   ├── launch.json
│   │   │   └── tasks.json
│   │   ├── public/
│   │   │   └── favicon.ico
│   │   ├── src/
│   │   │   ├── app/
│   │   │   │   ├── core/
│   │   │   │   │   ├── api.ts
│   │   │   │   │   ├── auth.ts
│   │   │   │   │   ├── collections.ts
│   │   │   │   │   └── sse.ts
│   │   │   │   ├── pages/
│   │   │   │   │   ├── benchmark/
│   │   │   │   │   │   ├── compare.ts
│   │   │   │   │   │   ├── rubric.ts
│   │   │   │   │   │   ├── run.ts
│   │   │   │   │   │   ├── runs.ts
│   │   │   │   │   │   └── topic.ts
│   │   │   │   │   ├── wiki/
│   │   │   │   │   │   ├── changeset.ts
│   │   │   │   │   │   ├── changesets.ts
│   │   │   │   │   │   ├── graph.ts
│   │   │   │   │   │   ├── jobs.ts
│   │   │   │   │   │   ├── lint.ts
│   │   │   │   │   │   ├── page.ts
│   │   │   │   │   │   ├── pages.ts
│   │   │   │   │   │   ├── settings.ts
│   │   │   │   │   │   ├── sources.ts
│   │   │   │   │   │   ├── wiki-layout.ts
│   │   │   │   │   │   └── wiki-select.ts
│   │   │   │   │   ├── ask.ts
│   │   │   │   │   ├── bulk.ts
│   │   │   │   │   ├── documents.ts
│   │   │   │   │   └── home.ts
│   │   │   │   ├── shared/
│   │   │   │   │   ├── citation-service.ts
│   │   │   │   │   ├── citations.ts
│   │   │   │   │   ├── diff.ts
│   │   │   │   │   ├── file-drop.ts
│   │   │   │   │   ├── login.ts
│   │   │   │   │   ├── markdown.ts
│   │   │   │   │   └── poll.ts
│   │   │   │   ├── app.config.ts
│   │   │   │   ├── app.routes.ts
│   │   │   │   └── app.ts
│   │   │   ├── index.html
│   │   │   ├── main.ts
│   │   │   └── styles.scss
│   │   ├── .editorconfig
│   │   ├── .gitignore
│   │   ├── .prettierrc
│   │   ├── angular.json
│   │   ├── package-lock.json
│   │   ├── package.json
│   │   ├── proxy.conf.json
│   │   ├── README.md
│   │   ├── tsconfig.app.json
│   │   ├── tsconfig.json
│   │   └── tsconfig.spec.json
│   ├── Dockerfile
│   └── README.md
├── Wiki/
│   ├── app/
│   │   ├── ops/
│   │   │   ├── __init__.py
│   │   │   ├── ingest.py
│   │   │   ├── lint.py
│   │   │   ├── query.py
│   │   │   └── synthesis.py
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── deps.py
│   │   │   ├── ops.py
│   │   │   ├── pages.py
│   │   │   ├── sources.py
│   │   │   ├── view.py
│   │   │   └── wikis.py
│   │   ├── sources/
│   │   │   ├── __init__.py
│   │   │   ├── extract.py
│   │   │   ├── models.py
│   │   │   ├── pdf_ifrs.py
│   │   │   └── text.py
│   │   ├── templates/
│   │   │   ├── base.html
│   │   │   ├── doc.html
│   │   │   ├── home.html
│   │   │   ├── index.html
│   │   │   ├── missing.html
│   │   │   └── page.html
│   │   ├── wiki/
│   │   │   ├── __init__.py
│   │   │   ├── citecheck.py
│   │   │   ├── saved.py
│   │   │   ├── search.py
│   │   │   └── store.py
│   │   ├── __init__.py
│   │   ├── attach_file.py
│   │   ├── auth.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── jobs.py
│   │   ├── llm.py
│   │   ├── main.py
│   │   ├── migrate.py
│   │   ├── prompts.py
│   │   ├── schema_default.md
│   │   └── storage.py
│   ├── migrations/
│   │   ├── 0001_init.sql
│   │   └── 0002_page_flags.sql
│   ├── postman/
│   │   └── LLM_Wiki.postman_collection.json
│   ├── .env.example
│   ├── .gitignore
│   ├── Dockerfile
│   ├── llm-wiki.md
│   ├── README.md
│   ├── requirements.txt
│   └── run.py
├── .dockerignore
├── .gitignore
├── DEPLOY.md
├── README.md
└── render.yaml
```

### Services and apps

Exactly four deployable components exist; no others were found (`render.yaml` deploys three containers because the Benchmark runs inside the UI image).

| Component | Folder | What it is | Entry point | Local port | Container port |
|---|---|---|---|---|---|
| RAG API | `Rag/` | FastAPI: IFRS PDF ingestion, hybrid retrieval, Gemini answers (the control system) | `Rag/run.py` → `app.main:app` | 8000 (`Rag/run.py`) | `${PORT:-10000}` (`Rag/Dockerfile`) |
| Wiki API | `Wiki/` | FastAPI: LLM-maintained wiki built from the same sources (the system under test) | `Wiki/run.py` → `app.main:app` | 8001 (`Wiki/run.py`) | `${PORT:-10000}` (`Wiki/Dockerfile`) |
| Benchmark | `Benchmark/` | Python package `bench`: runs both systems on a query set and grades them with Claude against a human reference | `python -m bench.run` etc. (§8.1); spawned as a subprocess by the UI server | n/a (CLI) | runs inside the UI container (`UI/Dockerfile`: `BENCH_DIR=/app/Benchmark`) |
| UI (Workbench) | `UI/server/` + `UI/web/` | FastAPI BFF (auth, proxy, benchmark/Ask/bulk endpoints, serves the SPA) + Angular single-page app | `UI/server/run.py` → `app.main:app`; `UI/web` built with the Angular CLI | 8080 (`UI/server/run.py`); Angular dev server 4200 (`UI/web/package.json` `start`, `proxy.conf.json`) | `${PORT:-10000}` (`UI/Dockerfile`) |

Shared infrastructure: one Postgres 17 database with pgvector (local Supabase, `Rag/supabase/config.toml` `[db] major_version = 17`, port 54322; hosted Supabase in deployment, `DEPLOY.md`), and Supabase Storage for original uploads (optional). External model APIs: Google Gemini (answers, embeddings, Ask rewrite) and Anthropic Claude (judge).

### Coverage checklist

Every tracked file, grouped by folder. The audit at the end (§Coverage audit) ticks each one off.

- **(root)**: `.dockerignore`, `.gitignore`, `DEPLOY.md`, `README.md`, `render.yaml`
- **Benchmark/**: `.env.example`, `.gitignore`, `README.md`, `requirements.txt`
- **Benchmark/bench/**: `__init__.py`, `checks.py`, `config.py`, `context.py`, `data.py`, `gaps.py`, `import_results.py`, `judge.py`, `library.py`, `metrics.py`, `migrate.py`, `prices.json`, `rubric.py`, `run.py`, `suggest.py`, `systems.py`
- **Benchmark/migrations/**: `0001_init.sql`, `0002_rag_collection.sql`, `0003_sources.sql`, `0004_rubrics.sql`, `0005_use_saved.sql`, `0006_ask_chats.sql`, `0007_run_mode.sql`, `0008_rubric_review.sql`, `0009_facts.sql`, `0010_rubric_v3.sql`, `0011_reference_labels.sql`
- **Rag/**: `.env.example`, `.gitignore`, `Dockerfile`, `README.md`, `requirements.txt`, `run.py`
- **Rag/app/**: `__init__.py`, `attach_file.py`, `bulk.py`, `config.py`, `db.py`, `llm.py`, `main.py`, `migrate.py`, `prompts.py`, `retrieval.py`, `storage.py`
- **Rag/app/ingest/**: `__init__.py`, `models.py`, `pdf_ifrs.py`, `pipeline.py`, `text.py`
- **Rag/app/routers/**: `__init__.py`, `bulk.py`, `collections.py`, `documents.py`, `query.py`
- **Rag/postman/**: `RAG_API.postman_collection.json`
- **Rag/supabase/**: `.gitignore`, `config.toml`
- **Rag/supabase/migrations/**: `20261007000000_init.sql`, `20261012000000_document_file.sql`, `20261013000000_collections.sql`
- **UI/**: `Dockerfile`, `README.md`
- **UI/server/**: `.env.example`, `.gitignore`, `requirements.txt`, `run.py`
- **UI/server/app/**: `__init__.py`, `ask.py`, `auth.py`, `bench.py`, `bulk.py`, `config.py`, `main.py`, `proxy.py`, `rubric_export.py`
- **UI/web/**: `.editorconfig`, `.gitignore`, `.prettierrc`, `README.md`, `angular.json`, `package-lock.json`, `package.json`, `proxy.conf.json`, `tsconfig.app.json`, `tsconfig.json`, `tsconfig.spec.json`
- **UI/web/.vscode/**: `extensions.json`, `launch.json`, `tasks.json`
- **UI/web/public/**: `favicon.ico`
- **UI/web/src/**: `index.html`, `main.ts`, `styles.scss`
- **UI/web/src/app/**: `app.config.ts`, `app.routes.ts`, `app.ts`
- **UI/web/src/app/core/**: `api.ts`, `auth.ts`, `collections.ts`, `sse.ts`
- **UI/web/src/app/pages/**: `ask.ts`, `bulk.ts`, `documents.ts`, `home.ts`
- **UI/web/src/app/pages/benchmark/**: `compare.ts`, `rubric.ts`, `run.ts`, `runs.ts`, `topic.ts`
- **UI/web/src/app/pages/wiki/**: `changeset.ts`, `changesets.ts`, `graph.ts`, `jobs.ts`, `lint.ts`, `page.ts`, `pages.ts`, `settings.ts`, `sources.ts`, `wiki-layout.ts`, `wiki-select.ts`
- **UI/web/src/app/shared/**: `citation-service.ts`, `citations.ts`, `diff.ts`, `file-drop.ts`, `login.ts`, `markdown.ts`, `poll.ts`
- **Wiki/**: `.env.example`, `.gitignore`, `Dockerfile`, `README.md`, `llm-wiki.md`, `requirements.txt`, `run.py`
- **Wiki/app/**: `__init__.py`, `attach_file.py`, `auth.py`, `config.py`, `db.py`, `jobs.py`, `llm.py`, `main.py`, `migrate.py`, `prompts.py`, `schema_default.md`, `storage.py`
- **Wiki/app/ops/**: `__init__.py`, `ingest.py`, `lint.py`, `query.py`, `synthesis.py`
- **Wiki/app/routers/**: `__init__.py`, `deps.py`, `ops.py`, `pages.py`, `sources.py`, `view.py`, `wikis.py`
- **Wiki/app/sources/**: `__init__.py`, `extract.py`, `models.py`, `pdf_ifrs.py`, `text.py`
- **Wiki/app/templates/**: `base.html`, `doc.html`, `home.html`, `index.html`, `missing.html`, `page.html`
- **Wiki/app/wiki/**: `__init__.py`, `citecheck.py`, `saved.py`, `search.py`, `store.py`
- **Wiki/migrations/**: `0001_init.sql`, `0002_page_flags.sql`
- **Wiki/postman/**: `LLM_Wiki.postman_collection.json`

## 1. System overview

### 1.1 What the application is

The repository is a research workbench that compares two ways of answering questions about IFRS Standards (IFRS 9 and IFRS 7 in practice) from the same source PDFs:

- **RAG API (`Rag/`)**, the control: it splits each PDF into IFRS paragraphs (`Rag/app/ingest/pdf_ifrs.py`), embeds them (`Rag/app/llm.py:embed`), and answers a question from the top hybrid-search passages (`Rag/app/retrieval.py:search`, `Rag/app/routers/query.py`).
- **Wiki API (`Wiki/`)**, the system under test: an LLM reads each source and writes and maintains a persistent, interlinked markdown wiki (`Wiki/app/ops/ingest.py`). Questions are answered from whole wiki pages that the model picks (`Wiki/app/ops/query.py`). This implements the "LLM wiki" idea in `Wiki/llm-wiki.md` (§6.0).
- **Benchmark (`Benchmark/`)**: asks both systems the same questions from a query set, then has Claude grade both answers blind against a human-written reference memo. It produces similarity, key-point coverage, wins and further answer-level tests with confidence intervals (§8).
- **UI (`UI/`)**, the "Workbench": an Angular app plus a FastAPI backend-for-frontend. It lets a user manage RAG collections and wikis, ask both systems side by side, run bulk requirement blocks, run and inspect benchmarks, and review the grading rubric (§9).

### 1.2 How the parts talk

All service-to-service traffic is HTTP/JSON. Streaming answers use Server-Sent Events (`sse-starlette`; event names in §5.4 and §6.5).

- **Browser to UI server.** The browser talks only to the UI server: same origin, `/api/...`, protected by an HMAC session cookie when `UI_PASSWORD` is set (`UI/server/app/auth.py`).
- **UI server to RAG and Wiki.** The UI server proxies `/api/rag/...` and `/api/wiki/...` to the RAG and Wiki APIs, adding the shared `X-API-Key` (`UI/server/app/proxy.py`). It also proxies `/view/...` to the Wiki's public HTML viewer without a key (`UI/server/app/main.py:wiki_viewer`).
- **API keys.** RAG and Wiki each require `X-API-Key` on every route except `/health` (and, for the Wiki, the `/view` routes) (`Rag/app/main.py:require_api_key`, `Wiki/app/auth.py`).
- **Benchmark process.** The UI server starts benchmark work as a child process: `python -m bench.run --run-id …`, and also `bench.rubric`, `bench.suggest` and `bench.checks` (`UI/server/app/bench.py:_spawn`).
  - The benchmark process calls the RAG and Wiki APIs directly, with `RAG_URL`/`WIKI_URL` passed in its environment (`Benchmark/bench/systems.py`).
  - It calls the Anthropic API, or the local `claude` CLI, for judging (`Benchmark/bench/judge.py`).
  - It writes progress and results into `bench.runs` in the shared database (`Benchmark/bench/run.py:Store`).
  - The UI reads results back from the database (`UI/server/app/bench.py`).
- **Ask chats.** These are stored by the UI server in schema `ask` (`UI/server/app/ask.py`, `Benchmark/migrations/0006_ask_chats.sql`). Follow-up questions are rewritten by a direct Gemini REST call from the UI server (`ask.py:_gemini_json`).
- **Gemini.** RAG and Wiki call Google Gemini through the `google-genai` SDK for generation and embeddings (`Rag/app/llm.py`, `Wiki/app/llm.py`).
- **Shared database.** All four components share one Postgres database: schemas `public` (RAG), `wiki`, `bench` and `ask`. Optional original files go to Supabase Storage (`Rag/app/storage.py`, `Wiki/app/storage.py`).

```mermaid
flowchart LR
  B[Browser<br/>Angular SPA] -- "HTTPS, /api/*, cookie wb_session" --> UI[UI server - FastAPI BFF<br/>:8080 local / :10000 container]
  UI -- "/api/rag/* + X-API-Key" --> RAG[RAG API<br/>:8000 local]
  UI -- "/api/wiki/* + X-API-Key<br/>/view/* without key" --> WIKI[Wiki API<br/>:8001 local]
  UI -- "spawn python -m bench.*" --> BENCH[Benchmark process]
  BENCH -- "POST /collections/c/query" --> RAG
  BENCH -- "POST /wikis/w/query, /read-text" --> WIKI
  BENCH -- "POST /search/paragraphs" --> RAG
  BENCH -- "Messages / Batches API or claude -p" --> CLAUDE[(Anthropic Claude)]
  RAG -- "generate, embed" --> GEM[(Google Gemini)]
  WIKI -- "generate, embed" --> GEM
  UI -- "Ask rewrite (REST v1beta)" --> GEM
  RAG --- DB[(Postgres 17 + pgvector<br/>public, wiki, bench, ask)]
  WIKI --- DB
  BENCH --- DB
  UI --- DB
  RAG -. originals .-> ST[(Supabase Storage<br/>bucket sources)]
  WIKI -. originals .-> ST
```

### 1.3 End-to-end flows

1. **Building the corpora** (§5.2, §6.4). An upload goes through the UI proxy:
   - To RAG, `POST /collections/{c}/documents`. The document is parsed, chunked and embedded synchronously.
   - To the Wiki, `POST /wikis/{w}/sources`. The text is extracted, a background ingest job is queued, and the LLM writes or updates pages, either applied immediately (`mode=auto`) or held as a changeset for review (`mode=review`).
2. **Asking** (§9.3 Ask page). The Ask page sends the same question to `POST /api/rag/collections/{c}/query/stream` and `POST /api/wiki/wikis/{w}/query/stream` and renders both streams side by side with clickable citations. Follow-ups are first rewritten into a standalone question (`/api/ask/chats/{id}/rewrite`).
3. **Benchmarking** (§8):
   1. `POST /api/bench/runs` stores the inputs (query set `.txt`, reference `.docx`) in `bench.runs` and spawns `bench.run`.
   2. For every topic × repetition, both systems get the identical question (`systems.ask`).
   3. Claude grades each pair twice, in both A/B orders, against the topic's key points.
   4. Answer checks, and in Full mode faithfulness/context recall, run.
   5. `aggregate()` writes the summary and bootstrap confidence intervals.
   6. The run page reads it back.

### 1.4 Where each part runs

| Part | Local (README) | Deployed (`render.yaml`) | Protocol |
|---|---|---|---|
| UI server + SPA + Benchmark | `127.0.0.1:8080` (`UI/server/run.py`); Angular dev server `:4200` proxies `/api` to 8080 (`UI/web/proxy.conf.json`) | Render `web` service `workbench`, Docker `UI/Dockerfile`, public | HTTP(S) |
| RAG API | `127.0.0.1:8000` (`Rag/run.py`) | Render private service `rag` (`type: pserv`) | HTTP, internal `hostport` |
| Wiki API | `127.0.0.1:8001` (`Wiki/run.py`) | Render private service `wiki` (`type: pserv`) | HTTP, internal `hostport` |
| Postgres | local Supabase `127.0.0.1:54322` (`Rag/supabase/config.toml`, `*/.env.example`) | Supabase Cloud, session pooler 5432 (`DEPLOY.md`) | Postgres wire |
| Storage | local Supabase API `:54321` | Supabase Storage (optional, `SUPABASE_SECRET_KEY`) | HTTPS REST |

## 2. Technology stack and versions

### 2.1 Summary

| Item | Version | Source |
|---|---|---|
| Python (all three images) | 3.12 (`python:3.12-slim`) | `Rag/Dockerfile:2`, `Wiki/Dockerfile:2`, `UI/Dockerfile:9` |
| Python (local) | not pinned anywhere in the code (no `.python-version`, `pyproject` or `runtime.txt`) | [UNVERIFIED] local virtual environments are outside the repository |
| Node (UI build) | 24 (`node:24-slim`) | `UI/Dockerfile:2` |
| Angular, Angular Material, TypeScript | see §2.6 | `UI/web/package.json`, `UI/web/package-lock.json` |
| Postgres | 17 (local Supabase) | `Rag/supabase/config.toml` `[db] major_version = 17` |
| pgvector extension | **not pinned**: `create extension if not exists vector with schema extensions` takes whatever the database provides | `Rag/supabase/migrations/20261007000000_init.sql:2`, `Wiki/migrations/0001_init.sql:2` |
| pgvector Python adapter | 0.5.0 | `Rag/requirements.txt`, `Wiki/requirements.txt` |
| Vector dimension | 768 | `vector(768)` in both migrations; `embed_dim = 768` in `Rag/app/config.py`, `Wiki/app/config.py` |
| Generation model (RAG, Wiki, Ask rewrite) | `gemini-2.5-flash` (default) | `Rag/app/config.py:gemini_chat_model`, `Wiki/app/config.py:gemini_chat_model`, `UI/server/app/config.py:gemini_model` |
| Embedding model | `gemini-embedding-001` (default) | `Rag/app/config.py`, `Wiki/app/config.py` |
| Judge model | `claude-opus-5-5` (default), effort `high` | `Benchmark/bench/config.py:judge_model`, `judge_effort` |
| Answer-check and context model | `claude-sonnet-5-5` (default) | `Benchmark/bench/config.py:checks_model`, `context_model` |

### 2.2 RAG API dependencies (`Rag/requirements.txt`, exact pins)

`fastapi==0.142.2`, `google-genai==2.28.0`, `pgvector==0.5.0`, `psycopg[binary,pool]==3.3.6`, `psycopg-pool==3.3.3`, `pydantic-settings==2.15.0`, `pymupdf==1.28.2`, `python-multipart==0.0.32`, `sse-starlette==3.5.0`, `uvicorn[standard]==0.54.0`, `numpy==2.5.3`.

`httpx` is imported (`Rag/app/storage.py`, `Rag/app/routers/documents.py`) but is not pinned. It arrives transitively [UNVERIFIED which package brings it].

### 2.3 Wiki API dependencies (`Wiki/requirements.txt`, exact pins)

`fastapi==0.142.4`, `google-genai==2.29.0`, `httpx==0.28.1`, `Jinja2==3.1.6`, `markdown-it-py==4.2.0`, `mdit-py-plugins==0.6.1` (pinned but not imported anywhere; verified with `git grep`), `numpy==2.5.3`, `pgvector==0.5.0`, `psycopg[binary,pool]==3.3.6`, `psycopg-pool==3.3.3`, `pydantic-settings==2.15.0`, `pymupdf==1.28.2`, `python-docx==1.2.0`, `python-multipart==0.0.32`, `PyYAML==6.0.3`, `trafilatura==2.3.1`, `uvicorn[standard]==0.54.0`, `sse-starlette==3.5.0`.

The RAG and Wiki pin different FastAPI (0.142.2 vs 0.142.4) and google-genai (2.28.0 vs 2.29.0) versions.

### 2.4 Benchmark dependencies (`Benchmark/requirements.txt`, exact pins)

`anthropic==1.12.1`, `httpx==0.28.1`, `pydantic-settings==2.15.0`, `python-docx==1.2.0`, `psycopg[binary]==3.3.6`.

The optional `claude-code` judge backend needs the Claude Code CLI (`claude`) on the PATH (`Benchmark/bench/config.py:claude_bin`). It is not a Python dependency and is not installed by any Dockerfile.

### 2.5 UI server dependencies (`UI/server/requirements.txt`, exact pins)

`fastapi==0.142.4`, `httpx==0.28.1`, `pydantic-settings==2.15.0`, `python-multipart==0.0.32`, `uvicorn[standard]==0.54.0`, `psycopg[binary]==3.3.6`, `python-docx==1.2.0`.

The UI image also installs `Benchmark/requirements.txt` (`UI/Dockerfile`), because benchmark runs are spawned from that image.

### 2.6 Angular web app: versions from `UI/web/package.json` and `package-lock.json`

| Package | Range | Installed |
|---|---|---|
| @angular/core, common, compiler, forms, platform-browser, router, compiler-cli | ^22.2.0 | 22.2.1 |
| @angular/material, @angular/cdk | ^22.2.2 | 22.2.2 |
| @angular/build, @angular/cli | ^22.2.2 | 22.2.2 |
| typescript | ~6.0.2 | 6.0.3 |
| rxjs | ~7.8.0 | 7.8.2 |
| tslib | ^2.3.0 | 2.8.1 |
| marked | ^18.1.0 | 18.1.0 |
| dompurify | ^3.4.16 | 3.4.16 |
| cytoscape | ^3.34.3 | 3.34.3 |
| prettier | ^3.8.1 | (dev) |

- `packageManager: npm@11.19.0`. No `engines` field in package.json. @angular/core requires node `^22.22.3 || ^24.15.0 || >=26.0.0` (lockfile, core entry). The Docker build uses `node:24-slim`.
- **Zoneless.** zone.js is not a dependency; it appears only as an optional peer of @angular/core in the lockfile. `app.config.ts` has no `provideZoneChangeDetection`, so the app runs zoneless, the Angular default in recent versions. State is held in signals throughout.
- Bootstrap is `bootstrapApplication(App, appConfig)` (`src/main.ts`). Components are standalone.
- Providers (`app.config.ts`):
  - `provideBrowserGlobalErrorListeners()`
  - `provideHttpClient(withFetch(), withInterceptors([authInterceptor]))`
  - `provideRouter(routes, withComponentInputBinding(), withRouterConfig({paramsInheritanceStrategy:'always'}), withNavigationErrorHandler(...))`. The error handler reloads `location.assign(e.url)` on "dynamically imported module|Loading chunk|Importing a module script failed", so a stale tab loads the new build.
- Build (`angular.json`):
  - builder `@angular/build:application`, browser `src/main.ts`, scss, assets from `public/`
  - production budgets: initial warning 1.5MB / error 3MB; anyComponentStyle 4kB / 8kB; outputHashing all
  - development: no optimisation, source maps
  - serve uses `proxyConfig: proxy.conf.json`
- `proxy.conf.json`: `/api` and `/view` → `http://127.0.0.1:8080` (secure false, changeOrigin).
- `tsconfig.json`: ES2022, module preserve, strictInjectionParameters, strictInputAccessModifiers. `tsconfig.spec.json` references `vitest/globals`, but vitest is not in devDependencies and there are no `*.spec.ts` files. So no tests exist.
- `.vscode`: extension `angular.ng-template`. Launch configs "ng serve" (localhost:4200) and "ng test" (9876/debug.html). Tasks for npm start and test.
- `index.html`: title "IFRS Workbench". Loads Roboto and Material Symbols Outlined from Google Fonts. Body class `mat-typography`.
- `styles.scss`: `mat.theme` with azure primary, blue tertiary, Roboto, density -1, color-scheme light dark. Shared classes: page, card, cards, pill (ok/warn/bad), simple table, .md (markdown, cite chips, missing wiki links), .diff.

### 2.7 RAG runtime, Postgres and local Supabase details

**`Rag/requirements.txt`** (exact pins):
- `fastapi==0.142.2`
- `google-genai==2.28.0`
- `pgvector==0.5.0`
- `psycopg[binary,pool]==3.3.6`
- `psycopg-pool==3.3.3`
- `pydantic-settings==2.15.0`
- `pymupdf==1.28.2`
- `python-multipart==0.0.32`
- `sse-starlette==3.5.0`
- `uvicorn[standard]==0.54.0`
- `numpy==2.5.3`

`httpx` is imported in `app/storage.py` and `app/routers/documents.py` but is **not pinned**. It arrives only transitively, presumably through google-genai [UNVERIFIED].

**Python:** 3.12 (`Rag/Dockerfile:2`).

**Postgres and extensions:**
- `Rag/supabase/config.toml` `[db] major_version = 17`.
- Ports:
  - db `54322`
  - shadow db `54320`
  - API `54321`
  - studio `54323`
  - inbucket/smtp `54324`
  - pooler `54329`; the pooler is disabled, with `pool_mode="transaction"`.
- `[api] extra_search_path = ["public","extensions"]`, `max_rows = 1000`.
- `[storage] file_size_limit = "50MiB"`. No buckets are declared in config.toml; the app creates its own.
- `[db.seed] sql_paths = ["./seed.sql"]`, but **`supabase/seed.sql` does not exist**. `supabase/snippets/` is empty.
- pgvector is installed by the migration: `create extension if not exists vector with schema extensions;`.

### 2.8 Wiki runtime

**`requirements.txt`, exact pins**

| Package | Version |
|---|---|
| fastapi | 0.142.4 |
| google-genai | 2.29.0 |
| httpx | 0.28.1 |
| Jinja2 | 3.1.6 |
| markdown-it-py | 4.2.0 |
| mdit-py-plugins | 0.6.1 |
| numpy | 2.5.3 |
| pgvector | 0.5.0 |
| psycopg[binary,pool] | 3.3.6 |
| psycopg-pool | 3.3.3 |
| pydantic-settings | 2.15.0 |
| pymupdf | 1.28.2 |
| python-docx | 1.2.0 |
| python-multipart | 0.0.32 |
| PyYAML | 6.0.3 |
| trafilatura | 2.3.1 |
| uvicorn[standard] | 0.54.0 |
| sse-starlette | 3.5.0 |

- `mdit-py-plugins` is pinned but no import of it appears in these files (verified with `git grep`: only `markdown_it` is imported, in `Wiki/app/routers/view.py`; `mdit-py-plugins` is unused).

**Runtime**
- Python: base image `python:3.12-slim`, with `PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1` (`Dockerfile:2-3`).
- Install: `pip install --no-cache-dir -r requirements.txt`, then `COPY Wiki/ .` (`Dockerfile:5-7`).

## 3. Configuration

Every setting below is read by pydantic-settings from the named `.env` file or the environment (field names upper-cased). Secret values are never shown; `.env.example` placeholders are masked.

### 3.1 RAG API (`Rag/app/config.py`, `Rag/.env.example`)

`SettingsConfigDict(env_file=".env", extra="ignore")`. Env var names are the upper-case field names (pydantic-settings is case-insensitive). `get_settings()` is `@lru_cache`.

| Field (line) | Type | Default | Controls |
|---|---|---|---|
| `api_key` (11) | str | **required** | value checked against the `X-API-Key` header |
| `gemini_api_key` (12) | str | **required** | `genai.Client(api_key=...)` |
| `gemini_chat_model` (13) | str | `"gemini-2.5-flash"` | generation and streaming model |
| `gemini_embed_model` (14) | str | `"gemini-embedding-001"` | embedding model |
| `embed_dim` (15) | int | `768` | `output_dimensionality`; must match `vector(768)` |
| `embed_batch` (16) | int | `100` | texts per embed call |
| `database_url` (17) | str | `postgresql://postgres:postgres@127.0.0.1:54322/postgres` (local Supabase default) | DB connection |
| `supabase_url` (19) | str | `""` | Storage base URL; falls back to the project ref in DATABASE_URL |
| `supabase_secret_key` (20) | str | `""` | turns original-file storage on |
| `storage_bucket` (21) | str | `"sources"` | Storage bucket name |
| `db_pool_max` (22) | int | `10` | pool `max_size` |
| `top_k` (23) | int | `8` | default passages per query |
| `chunk_max_words` (24) | int | `500` | max words per chunk (IFRS parser and generic chunker) |
| `temperature` (25) | float | `0.1` | generation temperature |
| `bulk_concurrency` (26) | int | `3` | topics run in parallel (semaphore) |
| `bulk_k_per_query` (27) | int | `6` | hybrid_search match_count per bulk query |
| `bulk_max_chunks` (28) | int | `30` | cap on merged passages per topic |

**`_clean_database_url` validator** (lines 30-48):
- Strips whitespace and quotes, a pasted `DATABASE_URL=` prefix and a leading `=`.
- Drops empty query params, and params that start with `=`, after the host.
- Percent-encodes the password literally, using `quote(pw, safe='')`. Users must **not** pre-encode it.

**`Rag/.env.example`**:
- `API_KEY=change-me` (placeholder)
- `GEMINI_API_KEY=your-gemini-key` (placeholder)
- `DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres` (local default creds)
- Commented out: `SUPABASE_SECRET_KEY=` (empty), `SUPABASE_URL=https://<project-ref>.supabase.co`, `STORAGE_BUCKET=sources`
- `GEMINI_CHAT_MODEL=gemini-2.5-flash`
- `GEMINI_EMBED_MODEL=gemini-embedding-001`
- `TOP_K=8`
- `CHUNK_MAX_WORDS=500`
- `TEMPERATURE=0.1`
- `BULK_CONCURRENCY=3`
- `BULK_K_PER_QUERY=6`
- `BULK_MAX_CHUNKS=30`

`EMBED_DIM`, `EMBED_BATCH` and `DB_POOL_MAX` are settable but absent from .env.example.

### 3.2 Wiki API (`Wiki/app/config.py`, `Wiki/.env.example`)

`Settings(BaseSettings)` uses `env_file=".env"` (relative to the working directory) and `extra="ignore"` (`app/config.py:9`). Env names are the upper-case field names (pydantic-settings, case-insensitive). The object is cached by `@lru_cache get_settings()` (`:60-62`).

| Setting | Type | Default | Effect (where used) |
|---|---|---|---|
| api_key | str | required | Shared `X-API-Key` (`auth.py:12`) |
| gemini_api_key | str | required | `genai.Client(api_key=...)` (`llm.py:20`) |
| gemini_chat_model | str | `gemini-2.5-flash` | All generate and stream calls (`llm.py:89,109`) |
| gemini_embed_model | str | `gemini-embedding-001` | Embeddings (`llm.py:71`) |
| embed_dim | int | 768 | `output_dimensionality`. Comment: "must match vector(768) in migrations" (`config.py:15`, `llm.py:70`) |
| embed_batch | int | 100 | Texts per embed call (`llm.py:68`) |
| temperature | float | 0.1 | Every generation config (`llm.py:83`) |
| database_url | str | `postgresql://postgres:postgres@127.0.0.1:54322/postgres` | Pool and migrations. Comment: "local Supabase" |
| supabase_url | str | `""` | Storage base URL. If empty, the project ref is taken from DATABASE_URL (`storage.py:25-31`) |
| supabase_secret_key | str | `""` | Storage is off unless set (`storage.py:34-35`) |
| storage_bucket | str | `sources` | Private bucket name |
| db_pool_max | int | 10 | Pool max size. Comment: "keep low on hosted Postgres" |
| section_words | int | 3000 | Source split size for note extraction (`_pack`, used by the `routers/sources.py` uploads and `attach_file.py`) |
| chunk_max_words | int | 500 | Page chunk size for search (`store._chunks`). The comment also says "IFRS parser", but `extract.from_pdf` calls `pdf_ifrs.parse_document(doc)` without it, so the parser uses its hard-coded default `max_words=500` (`extract.py:75`, `pdf_ifrs.py:117`) |
| max_pages_per_ingest | int | 17 | "including the source page". Used in ops/ingest and lint |
| page_source_words | int | 12000 | Source paragraphs given to each page writer when the schema has no fixed sections (ops/ingest) |
| page_part_words | int | 4000 | Source words per writing call; longer pages are written in parts (ops/ingest) |
| page_background_words | int | 2000 | Context-only paragraphs from other sections (ops/ingest) |
| route_batch | int | 120 | Paragraphs per call when assigning paragraphs to schema sections. ops/ingest retries with 40 (`ops/ingest.py:360`) |
| llm_concurrency | int | 4 | Default cap in `llm.gather_limited` (`llm.py:129`) |
| job_workers | int | 2 | Global job semaphore (`jobs.py:34`) |
| query_top_k | int | 8 | Search hits for a query (`ops/query.py:21`) |
| query_max_pages | int | 8 | Pages the LLM may pick (`ops/query.py:27,33`) |
| lint_batch_pages | int | 12 | Pages per LLM lint call (`ops/lint.py:72`) |
| max_upload_mb | int | 50 | Upload size cap, 413 above it (`routers/sources.py:51-52`) |

`database_url` validator `_clean_database_url` (`config.py:39-57`):
- Strips whitespace and quotes, and a pasted `DATABASE_URL=` prefix and a leading `=`.
- Drops empty query parts and a trailing `?`. It only touches the part after the last `@`.
- Percent-encodes the password with `quote(pw, safe='')`. The password is meant to be typed literally; do not pre-encode it.

**`.env.example`** (`.env.example:1-19`):
- Required: `API_KEY=<masked>`, `GEMINI_API_KEY=<masked>`.
- `DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres` (local Supabase default credentials). Comment: "Same local Supabase DB as Rag (tables live in the "wiki" schema)".
- Commented optional lines: `# SUPABASE_SECRET_KEY=`, `# SUPABASE_URL=https://<project-ref>.supabase.co`, `# STORAGE_BUCKET=sources`.
- Optional, set: `GEMINI_CHAT_MODEL=gemini-2.5-flash`, `GEMINI_EMBED_MODEL=gemini-embedding-001`, `MAX_PAGES_PER_INGEST=17`, `LLM_CONCURRENCY=4`, `JOB_WORKERS=2`.

The local `.env` (not committed per `.gitignore` [UNVERIFIED]) has these keys only: API_KEY, GEMINI_API_KEY, DATABASE_URL, GEMINI_CHAT_MODEL, GEMINI_EMBED_MODEL, MAX_PAGES_PER_INGEST, LLM_CONCURRENCY, JOB_WORKERS, TEMPERATURE, SUPABASE_SECRET_KEY. Values not shown; `TEMPERATURE` is 0.1 there, the same as the default.

### 3.3 Benchmark (`Benchmark/bench/config.py`, `Benchmark/.env.example`)

**requirements.txt (exact pins):** `anthropic==1.12.1`, `httpx==0.28.1`, `pydantic-settings==2.15.0`, `python-docx==1.2.0`, `psycopg[binary]==3.3.6`.

**config.py `Settings`.** It reads `Benchmark/.env` with `extra="ignore"`; `ROOT=Benchmark/`, `DOCS=ROOT.parent/"Docs"`.

| name | type | default | effect |
|---|---|---|---|
| anthropic_api_key | str\|None | None | If unset, the SDK uses the env var or an `ant auth login` profile (`judge.client`) |
| judge_model | str | "claude-opus-5-5" | key points, grading, facts, suggestions |
| judge_effort | str | "high" | `output_config.effort` / `--effort` for **all** Claude calls, checks and context included (`judge._params` L69-70, `_cli_call` L40) |
| judge_backend | str | "api" | "api" or "claude-code" |
| claude_code_oauth_token | str | "" | required for claude-code |
| claude_bin | str | "claude" | CLI binary |
| judge_timeout_s | int | 900 | timeout of the claude-code subprocess |
| rag_url | str | "http://127.0.0.1:8000" | trailing "/" stripped; "http://" added if no scheme |
| rag_api_key | str | required | X-API-Key header |
| wiki_url | str | "http://127.0.0.1:8001" | same validator as rag_url |
| wiki_api_key | str | required | X-API-Key header |
| rag_collection | str | "" | CLI only |
| wiki_slug | str | "" | CLI only |
| sources | str | "all" | "standard" (Part A) or "all" (A, B, C); the same for both systems |
| use_saved | bool | True | the wiki also reads saved answers |
| mode | str | "quick" | quick or full |
| use_batch | bool | True | Message Batches for grading, checks and context |
| batch_poll_s | int | 30 | batch poll interval |
| batch_timeout_s | int | 6*3600 | after this the batch is cancelled and the rest is graded normally |
| context_model | str | "claude-sonnet-5-5" | faithfulness and context recall |
| checks_model | str | "claude-sonnet-5-5" | completeness, exact match, citations |
| database_url | str | local Supabase on port 54322 | cleaned by a validator: strips quotes and a "DATABASE_URL=" prefix, drops empty query params, percent-encodes the password (L67-85) |
| runs | int | **2** | repetitions per topic |
| concurrency | int | 4 | |
| seed | int | 42 | |
| query_set | Path | DOCS/"IFRS9_Requirement_Query_Set_BULK_5.txt" | a relative path resolves against Benchmark/ |
| reference_docx | Path | DOCS/`<reference memo .docx>` | same |

Settings are cached with `lru_cache` (`get_settings`). `run.main` mutates the cached object per run.

**.env.example (masked):**
- `ANTHROPIC_API_KEY=` (empty), `JUDGE_MODEL=claude-opus-5-5`, `JUDGE_EFFORT=high`, `JUDGE_BACKEND=api`, `CLAUDE_CODE_OAUTH_TOKEN=` (empty).
- `RAG_URL=http://127.0.0.1:8000`, `RAG_API_KEY=<masked>`, `WIKI_URL=http://127.0.0.1:8001`, `WIKI_API_KEY=<masked>`.
- `RAG_COLLECTION=ifrs9`, `SOURCES=all`, `WIKI_SLUG=ifrs9`.
- `DATABASE_URL=postgresql://postgres:<masked>@127.0.0.1:54322/postgres`.
- `REFERENCE_DOCX=../Docs/<reference memo .docx>`.
- `RUNS=3`, `CONCURRENCY=4`, `SEED=42`.
- Not in .env.example: MODE, USE_BATCH, USE_SAVED, CHECKS_MODEL, CONTEXT_MODEL, CLAUDE_BIN, JUDGE_TIMEOUT_S, BATCH_*, QUERY_SET. They are settable through pydantic.

**Runs-default inconsistency:**
- config.py says 2.
- .env.example and the DB column default (0001) say 3.
- README says both "default 3" (L26) and "Runs default to 2 repetitions" (L50).

**API backend, `judge._json_call` L83-92 and `_params` L67-70:**
- `client().beta.messages.create(model, max_tokens=16000, system, messages=[user], output_config={"effort": judge_effort, "format": {"type":"json_schema","schema": schema}}, betas=["server-side-fallback-2026-07-01"], fallbacks="default")`.
- `AsyncAnthropic(max_retries=5)` (L23); the SDK retries 408/409/429/5xx.

**claude-code backend, `judge._cli_call` L31-64:**
- Requires `CLAUDE_CODE_OAUTH_TOKEN`, otherwise RuntimeError.
- Env: a copy of os.environ minus `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL`, with `CLAUDE_CODE_OAUTH_TOKEN` set.
- Exact args: `[claude_bin, "-p", "--output-format", "json", "--json-schema", json.dumps(schema), "--model", model or judge_model, "--effort", judge_effort, "--system-prompt", system, "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence"]`.
- cwd is an empty TemporaryDirectory. The user prompt goes on stdin. `asyncio.wait_for(..., timeout=judge_timeout_s)`; on timeout the process is killed and a RuntimeError raised.
- An error is raised on non-JSON output, a non-zero exit or `is_error`.
- Data is read from `structured_output`, or else `json.loads(result)`.
- Usage comes from `modelUsage[model]` (or the first entry): input = inputTokens + cacheReadInputTokens + cacheCreationInputTokens; output = outputTokens.
- There is no max_tokens and no fallback on this path.

---

### 3.4 UI server (`UI/server/app/config.py`, `UI/server/.env.example`)

| Setting (env) | Default | Effect |
|---|---|---|
| `RAG_URL` | `http://127.0.0.1:8000` | RAG base. The validator strips a trailing `/` and adds `http://` if there is no scheme, because Render private services give host:port (`config.py:16, 35-40`) |
| `RAG_API_KEY` | **required** (no default) | Sent as X-API-Key to RAG [secret] |
| `WIKI_URL` | `http://127.0.0.1:8001` | Wiki base, same validator |
| `WIKI_API_KEY` | **required** | [secret] |
| `DATABASE_URL` | `postgresql://postgres:postgres@127.0.0.1:54322/postgres` (local Supabase) | Used for bench.runs, bench.rubrics, bench.references, ask.*, and wiki.sources (read directly). See the cleaning validator below |
| `BENCH_DIR` | `PROJECT/Benchmark` (two levels above UI/server) | Working directory for the benchmark subprocesses and for `prices.json` and `.env` |
| `BENCH_PYTHON` | None | Interpreter for the subprocesses. Falls back to `<bench_dir>/.venv/Scripts/python.exe`, then `<bench_dir>/.venv/bin/python`, then `sys.executable` (`config.py:42-48`) |
| `DEFAULT_QUERY_SET` | `PROJECT/Docs/IFRS9_Requirement_Query_Set_BULK_5.txt` | Bulk runs with no uploaded file (optional) |
| `GEMINI_API_KEY` | `""` | Ask follow-up rewrite [secret] |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model for the rewrite |
| `ASK_HISTORY_QUESTIONS` | `6` | At most this many earlier questions are used to rewrite a follow-up |
| `UI_PASSWORD` | `""` | Shared login. Empty means no login [secret] |
| `SESSION_SECRET` | `""` | Mixed into the cookie HMAC key [secret] |
| `WEB_DIST` | `UI/web/dist/web/browser` | Where the SPA is served from (the Dockerfile sets `/app/UI/web/dist/web/browser`) |

- The `DATABASE_URL` validator (`config.py:50-68`) does the following:
  - Strips whitespace and quotes, a pasted `DATABASE_URL=` prefix, and a leading `=`.
  - Drops empty query parts.
  - Percent-encodes the password literally with `quote(pw, safe='')`. The comment says "Do not percent-encode it yourself".
- `get_settings()` is `lru_cache`d (`config.py:71-73`).
- `UI/server/.env.example` has these lines:
  - `RAG_URL=http://127.0.0.1:8000`
  - `RAG_API_KEY=change-me`
  - `WIKI_URL=http://127.0.0.1:8001`
  - `WIKI_API_KEY=change-me`
  - commented: `BENCH_DIR=../../Benchmark`, `DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres`, `DEFAULT_QUERY_SET=../../Docs/IFRS9_Requirement_Query_Set_BULK_5.txt`
  - `UI_PASSWORD=` and `SESSION_SECRET=`, both empty
  - Not listed in `.env.example`: `GEMINI_API_KEY`, `GEMINI_MODEL`, `ASK_HISTORY_QUESTIONS`, `BENCH_PYTHON`, `WEB_DIST`.
- `UI/server/.gitignore` ignores `.venv/`, `__pycache__/` and `.env`.

---

### 3.5 All tunable and hard-coded constants at a glance

This table collects every number that shapes behaviour. "Setting" means it can be changed through the environment; "hard-coded" means it can be changed only in code or SQL. The details and line references are in the sections named.

| Area | Constant | Value | Kind | Where |
|---|---|---|---|---|
| Embeddings (RAG, Wiki) | model / dimension / batch | `gemini-embedding-001` / 768 / 100 texts per call | setting (dimension also hard-coded in SQL) | `*/app/config.py`; `vector(768)` in the migrations |
| Embeddings | task types | documents `RETRIEVAL_DOCUMENT`, queries `RETRIEVAL_QUERY`; vectors L2-normalised | hard-coded | `Rag/app/llm.py:embed`, `Wiki/app/llm.py:embed` |
| Generation | temperature | RAG **0.1**, Wiki **0.1**, Ask rewrite **0** | setting / setting / hard-coded | `Rag/app/config.py`, `Wiki/app/config.py`, `UI/server/app/ask.py:_gemini_json` |
| Gemini retries | attempts / codes / delay | 5 / {429, 500, 502, 503, 504} / `2**i * 2` s (2, 4, 8, 16) | hard-coded | `Rag/app/llm.py:_retry`, `Wiki/app/llm.py:_retry` |
| Wiki JSON retries | attempts | 3, no delay | hard-coded | `Wiki/app/llm.py:generate_json` |
| RAG chunking | max words per chunk / overlap | 500 (`CHUNK_MAX_WORDS`) / 50 words (plain text only) | setting / hard-coded | `Rag/app/config.py`, `Rag/app/ingest/text.py:chunk_plain` |
| RAG retrieval | top_k / candidates per list / RRF k / weights | 8 / `match_count*2` / 50 / 1 and 1 | setting / SQL / SQL / SQL | `Rag/app/config.py:top_k`; `hybrid_search` in `20261013000000_collections.sql` |
| RAG bulk | concurrency / k per query / max passages / word tolerance | 3 / 6 / 30 / 25% | setting ×3 / hard-coded | `Rag/app/config.py`, `Rag/app/bulk.py:WORD_TOLERANCE` |
| Wiki search | RRF k / candidates per list / snippet | 50 / `match_count*4` / 400 characters | SQL | `wiki.search_pages` in `Wiki/migrations/0001_init.sql` |
| Wiki page chunks | max words / split | 500 / at headings `#`–`###`, then sentences | setting / hard-coded | `Wiki/app/wiki/store.py:_chunks` |
| Wiki ingest | pages per ingest (incl. source page) | 17 | setting `MAX_PAGES_PER_INGEST` | `Wiki/app/config.py`, `ops/ingest.py` |
| Wiki ingest | source section / page part / page source / background words | 3000 / 4000 / 12000 / 2000 | settings | `Wiki/app/config.py` |
| Wiki ingest | routing batch | 120 paragraphs, retried at 40 | setting / hard-coded | `Wiki/app/config.py:route_batch`, `ops/ingest.py` |
| Wiki query | search hits / pages the model may pick / max pages read / saved answers | 8 / 8 / 13 / 2 | setting / setting / hard-coded / hard-coded | `Wiki/app/config.py`, `ops/query.py` (§6.5) |
| Wiki index | compact index cap | 60,000 characters | hard-coded | `Wiki/app/wiki/store.py:compact_index` |
| Wiki jobs | concurrent jobs / LLM concurrency | 2 / 4 | settings | `Wiki/app/config.py:job_workers`, `llm_concurrency` |
| Wiki lint | pages per lint call | 12 | setting | `Wiki/app/config.py:lint_batch_pages` |
| Uploads | Wiki max upload / UI benchmark upload cap | 50 MB / 20 MB | setting / hard-coded | `Wiki/app/config.py:max_upload_mb`, `UI/server/app/bench.py:MAX_UPLOAD` |
| Benchmark | repetitions per topic / seed / concurrency | 2 / see §3.3 / see §3.3 | settings | `Benchmark/bench/config.py` |
| Benchmark | judge max_tokens / CLI judge timeout | 16000 / 900 s | hard-coded / setting | `Benchmark/bench/judge.py`, `config.py:judge_timeout_s` |
| Benchmark | system HTTP timeout / attempts / backoff | 300 s / 3 / `5*(i+1)` s | hard-coded | `Benchmark/bench/systems.py:_post` |
| Benchmark | bootstrap resamples / CI | 10,000 / 95% | hard-coded | `Benchmark/bench/gaps.py` |
| Benchmark | citations checked per answer / paragraph chars / claims | 40 / 3000 / 40 | hard-coded | `checks.py:MAX_CITATIONS`, `MAX_PARAGRAPH`; `context.py:MAX_CLAIMS` |
| UI | proxy timeout / connect | 600 s / 10 s | hard-coded | `UI/server/app/proxy.py` |
| UI | session cookie lifetime | 7 days | hard-coded | `UI/server/app/auth.py:MAX_AGE` |
| UI | stale-run threshold / memo-label cache | 2 min / 15 min | hard-coded | `UI/server/app/bench.py:STALE`, `REF_TTL` |
| DB pools | max connections | 10 (Render: 4 via `DB_POOL_MAX`) | setting | `Rag/app/config.py`, `Wiki/app/config.py`, `render.yaml` |

## 4. Data model and database schema

All services share one Postgres database (Supabase): the RAG tables live in `public`, the wiki tables in schema `wiki`, the benchmark and Ask tables in schemas `bench` and `ask`. Each service applies only its own migrations (§10). DDL is reproduced verbatim from the migration files.

### 4.1 RAG schema (`Rag/supabase/migrations/*.sql`, applied by `Rag/app/migrate.py`)

#### `Rag/supabase/migrations/20261007000000_init.sql`
```sql
create schema if not exists extensions;
create extension if not exists vector with schema extensions;

create table if not exists public.documents (
  id uuid primary key default gen_random_uuid(),
  filename text not null,
  sha256 text not null unique,
  parser text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.chunks (
  id bigint generated always as identity primary key,
  document_id uuid not null references public.documents(id) on delete cascade,
  para_ref text,
  part int not null default 0,
  source_type text not null,
  page int,
  heading text,
  content text not null,
  embedding extensions.vector(768) not null,
  fts tsvector generated always as (
    to_tsvector('english', coalesce(para_ref, '') || ' ' || coalesce(heading, '') || ' ' || content)
  ) stored
);

create index if not exists chunks_embedding_idx on public.chunks using hnsw (embedding extensions.vector_cosine_ops);
create index if not exists chunks_fts_idx on public.chunks using gin (fts);
create index if not exists chunks_para_ref_idx on public.chunks (para_ref);
create index if not exists chunks_document_idx on public.chunks (document_id);

-- Hybrid search: full-text (OR of query terms, ranked by cover density) + vector cosine, fused with RRF.
create or replace function public.hybrid_search(
  query_text text,
  query_embedding extensions.vector(768),
  match_count int,
  include_types text[] default null,
  exclude_types text[] default null,
  full_text_weight float default 1,
  semantic_weight float default 1,
  rrf_k int default 50
)
returns table (
  id bigint, document_id uuid, para_ref text, part int, source_type text, page int,
  heading text, content text, score float
)
language sql stable
set search_path = public, extensions
as $$
with q as (
  select nullif(replace(plainto_tsquery('english', query_text)::text, '&', '|'), '')::tsquery as tsq
),
filtered as (
  select c.* from chunks c
  where (include_types is null or c.source_type = any(include_types))
    and (exclude_types is null or not (c.source_type = any(exclude_types)))
),
full_text as (
  select f.id, row_number() over (order by ts_rank_cd(f.fts, q.tsq) desc) as rank_ix
  from filtered f, q
  where q.tsq is not null and f.fts @@ q.tsq
  order by rank_ix
  limit match_count * 2
),
semantic as (
  select f.id, row_number() over (order by f.embedding <=> query_embedding) as rank_ix
  from filtered f
  order by rank_ix
  limit match_count * 2
)
select c.id, c.document_id, c.para_ref, c.part, c.source_type, c.page, c.heading, c.content,
  coalesce(1.0 / (rrf_k + ft.rank_ix), 0.0) * full_text_weight
  + coalesce(1.0 / (rrf_k + s.rank_ix), 0.0) * semantic_weight as score
from full_text ft
full outer join semantic s on ft.id = s.id
join chunks c on c.id = coalesce(ft.id, s.id)
order by score desc
limit match_count;
$$;
```
- Vector index: HNSW, opclass `vector_cosine_ops`, 768 dimensions, cosine distance (`<=>`). No HNSW parameters are given (`m` / `ef_construction` use the pgvector defaults).
- FTS: English config, a stored generated `tsvector` over para_ref, heading and content, with a GIN index.

#### `Rag/supabase/migrations/20261012000000_document_file.sql`
```sql
-- The original uploaded file in Supabase Storage: {bucket, path, content_type, size}, or null when not stored
alter table public.documents add column if not exists file jsonb;
```

#### `Rag/supabase/migrations/20261013000000_collections.sql`
```sql
-- Collections: independent sets of documents, searched separately (like wikis). Every document belongs to one.
create table if not exists public.collections (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  name text not null,
  description text not null default '',
  created_at timestamptz not null default now()
);
alter table public.collections enable row level security;  -- not exposed through the Supabase REST API

alter table public.documents add column if not exists collection_id uuid references public.collections(id) on delete cascade;

-- Documents ingested before collections existed keep working: they move into one collection, "ifrs9"
insert into public.collections (slug, name)
select 'ifrs9', 'IFRS 9' where exists (select 1 from public.documents where collection_id is null)
on conflict (slug) do nothing;
update public.documents set collection_id = (select id from public.collections where slug = 'ifrs9') where collection_id is null;
alter table public.documents alter column collection_id set not null;
create index if not exists documents_collection_idx on public.documents (collection_id);

-- The same file may be ingested into several collections, but only once into each
alter table public.documents drop constraint if exists documents_sha256_key;
create unique index if not exists documents_collection_sha256_key on public.documents (collection_id, sha256);

-- Hybrid search, now restricted to one collection (unchanged otherwise: same ranking, fusion and weights)
drop function if exists public.hybrid_search(text, extensions.vector, int, text[], text[], float, float, int);
create or replace function public.hybrid_search(
  query_text text,
  query_embedding extensions.vector(768),
  match_count int,
  include_types text[] default null,
  exclude_types text[] default null,
  full_text_weight float default 1,
  semantic_weight float default 1,
  rrf_k int default 50,
  p_collection_id uuid default null
)
returns table (
  id bigint, document_id uuid, para_ref text, part int, source_type text, page int,
  heading text, content text, score float
)
language sql stable
set search_path = public, extensions
as $$
with q as (
  select nullif(replace(plainto_tsquery('english', query_text)::text, '&', '|'), '')::tsquery as tsq
),
filtered as (
  select c.* from chunks c
  join documents d on d.id = c.document_id
  where (p_collection_id is null or d.collection_id = p_collection_id)
    and (include_types is null or c.source_type = any(include_types))
    and (exclude_types is null or not (c.source_type = any(exclude_types)))
),
full_text as (
  select f.id, row_number() over (order by ts_rank_cd(f.fts, q.tsq) desc) as rank_ix
  from filtered f, q
  where q.tsq is not null and f.fts @@ q.tsq
  order by rank_ix
  limit match_count * 2
),
semantic as (
  select f.id, row_number() over (order by f.embedding <=> query_embedding) as rank_ix
  from filtered f
  order by rank_ix
  limit match_count * 2
)
select c.id, c.document_id, c.para_ref, c.part, c.source_type, c.page, c.heading, c.content,
  coalesce(1.0 / (rrf_k + ft.rank_ix), 0.0) * full_text_weight
  + coalesce(1.0 / (rrf_k + s.rank_ix), 0.0) * semantic_weight as score
from full_text ft
full outer join semantic s on ft.id = s.id
join chunks c on c.id = coalesce(ft.id, s.id)
order by score desc
limit match_count;
$$;
```

**Schema-level notes**
- There are no views and no triggers. The only RLS is `collections` with RLS enabled and no policies. `documents` and `chunks` have no RLS.
- There is no CHECK constraint on `source_type`; the allowed values exist only in Python.
- FKs: `chunks.document_id` → `documents.id` and `documents.collection_id` → `collections.id`, both `on delete cascade`.
- The unique key on `documents` is now `(collection_id, sha256)`.
- [UNVERIFIED] Performance: the semantic CTE computes `row_number() over (order by embedding <=> q)` across the whole filtered set (a join plus filters). That shape probably stops the planner from using the HNSW index, which would mean exact brute-force cosine search. This is a likely planner behaviour, not something I measured.

**`Rag/app/migrate.py`** (`python -m app.migrate`)
- Connects with `psycopg.connect(database_url, autocommit=True, connect_timeout=15)`.
- Creates the tracking table `public.rag_schema_migrations (name text primary key, applied_at timestamptz default now())`.
- Applies every file in `sorted(Rag/supabase/migrations/*.sql)` whose name is not already in that table. Each file and its tracking insert run in one transaction (lines 53-64).
- The docstring says the SQL is idempotent, so running it after the Supabase CLI is safe. The CLI keeps its own tracking separately.
- `_explain` gives connection hints for: localhost URLs, the IPv6-only `db.*.supabase.co` direct host, port `6543` (transaction pooler, where session pooler 5432 is wanted), and bad passwords.
- `_redacted` masks the password in error output.

### 4.2 Wiki schema (`Wiki/migrations/*.sql`, applied by `Wiki/app/migrate.py`)

#### `migrations/0001_init.sql`
```sql
create schema if not exists extensions;
create extension if not exists vector with schema extensions;
create schema if not exists wiki;

create table wiki.wikis (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  name text not null,
  description text not null default '',
  schema_md text not null,
  created_at timestamptz not null default now()
);

create table wiki.sources (
  id uuid primary key default gen_random_uuid(),
  wiki_id uuid not null references wiki.wikis(id) on delete cascade,
  slug text not null,
  title text not null,
  kind text not null,               -- pdf | text | markdown | docx | url
  uri text,
  sha256 text not null,
  text text not null,
  meta jsonb not null default '{}',
  created_at timestamptz not null default now(),
  unique (wiki_id, sha256),
  unique (wiki_id, slug)
);

create table wiki.pages (
  id uuid primary key default gen_random_uuid(),
  wiki_id uuid not null references wiki.wikis(id) on delete cascade,
  slug text not null,
  title text not null,
  type text not null,               -- overview | entity | concept | topic | comparison | synthesis | source
  summary text not null default '',
  content_md text not null default '',
  tags text[] not null default '{}',
  version int not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (wiki_id, slug)
);

create table wiki.page_versions (
  id bigint generated always as identity primary key,
  page_id uuid not null references wiki.pages(id) on delete cascade,
  version int not null,
  title text not null,
  type text not null,
  summary text not null,
  content_md text not null,
  tags text[] not null default '{}',
  change_note text not null default '',
  job_id uuid,
  created_at timestamptz not null default now(),
  unique (page_id, version)
);

create table wiki.links (
  wiki_id uuid not null references wiki.wikis(id) on delete cascade,
  from_page_id uuid not null references wiki.pages(id) on delete cascade,
  to_slug text not null,
  primary key (from_page_id, to_slug)
);
create index on wiki.links (wiki_id, to_slug);

create table wiki.page_sources (
  page_id uuid not null references wiki.pages(id) on delete cascade,
  source_id uuid not null references wiki.sources(id) on delete cascade,
  primary key (page_id, source_id)
);

create table wiki.page_chunks (
  id bigint generated always as identity primary key,
  wiki_id uuid not null references wiki.wikis(id) on delete cascade,
  page_id uuid not null references wiki.pages(id) on delete cascade,
  content text not null,
  embedding vector(768) not null,
  fts tsvector generated always as (to_tsvector('english', content)) stored
);
create index on wiki.page_chunks using hnsw (embedding vector_cosine_ops);
create index on wiki.page_chunks using gin (fts);
create index on wiki.page_chunks (wiki_id);

create table wiki.log (
  id bigint generated always as identity primary key,
  wiki_id uuid not null references wiki.wikis(id) on delete cascade,
  ts timestamptz not null default now(),
  kind text not null,               -- ingest | query | lint | edit | apply | revert | delete
  title text not null,
  detail_md text not null default ''
);
create index on wiki.log (wiki_id, ts desc);

create table wiki.jobs (
  id uuid primary key default gen_random_uuid(),
  wiki_id uuid references wiki.wikis(id) on delete cascade,
  kind text not null,               -- ingest | lint
  status text not null default 'queued',  -- queued | running | succeeded | failed
  params jsonb not null default '{}',
  progress jsonb not null default '{}',
  result jsonb,
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);

create table wiki.changesets (
  id uuid primary key default gen_random_uuid(),
  wiki_id uuid not null references wiki.wikis(id) on delete cascade,
  job_id uuid references wiki.jobs(id) on delete set null,
  source_id uuid references wiki.sources(id) on delete set null,
  kind text not null,               -- ingest | query | lint
  status text not null default 'pending',  -- pending | applied | discarded
  summary text not null default '',
  created_at timestamptz not null default now(),
  applied_at timestamptz
);

create table wiki.changeset_ops (
  id bigint generated always as identity primary key,
  changeset_id uuid not null references wiki.changesets(id) on delete cascade,
  op text not null,                 -- create | update | delete
  slug text not null,
  title text,
  type text,
  summary text,
  content_md text,
  tags text[] not null default '{}',
  base_version int,                 -- page version the op was written against (conflict check)
  change_note text not null default ''
);

-- Hybrid page search: OR'ed full-text + cosine vector, fused with RRF; best chunk per page.
create or replace function wiki.search_pages(
  p_wiki_id uuid,
  query_text text,
  query_embedding vector(768),
  match_count int,
  rrf_k int default 50
)
returns table (page_id uuid, slug text, title text, type text, summary text, snippet text, score float)
language sql stable
set search_path = wiki, public, extensions
as $$
with q as (
  select nullif(replace(plainto_tsquery('english', query_text)::text, '&', '|'), '')::tsquery as tsq
),
full_text as (
  select c.id, row_number() over (order by ts_rank_cd(c.fts, q.tsq) desc) as rank_ix
  from wiki.page_chunks c, q
  where c.wiki_id = p_wiki_id and q.tsq is not null and c.fts @@ q.tsq
  order by rank_ix limit match_count * 4
),
semantic as (
  select c.id, row_number() over (order by c.embedding <=> query_embedding) as rank_ix
  from wiki.page_chunks c
  where c.wiki_id = p_wiki_id
  order by rank_ix limit match_count * 4
),
scored as (
  select c.page_id, c.content,
    coalesce(1.0 / (rrf_k + ft.rank_ix), 0.0) + coalesce(1.0 / (rrf_k + s.rank_ix), 0.0) as score
  from full_text ft
  full outer join semantic s on ft.id = s.id
  join wiki.page_chunks c on c.id = coalesce(ft.id, s.id)
),
best as (
  select distinct on (page_id) page_id, content, score from scored order by page_id, score desc
)
select p.id, p.slug, p.title, p.type, p.summary, left(b.content, 400), b.score
from best b join wiki.pages p on p.id = b.page_id
order by b.score desc
limit match_count;
$$;
```

#### `migrations/0002_page_flags.sql`
```sql
-- Flags on pages, e.g. a saved answer whose cited paragraphs were written up differently by a later upload
create table if not exists wiki.page_flags (
  page_id uuid not null references wiki.pages(id) on delete cascade,
  kind text not null,                       -- 'needs_checking'
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (page_id, kind)
);
```
The comment lists only `'needs_checking'`, but the code also writes `kind='citation_problems'` (`app/wiki/saved.py:37,42`).

#### Schema notes
- **Vector index**: HNSW, `vector_cosine_ops`, dimension 768, distance `<=>` (cosine). Default HNSW parameters; no m or ef_construction given (`0001_init.sql:78,81`).
- **Full-text index**: a GIN index on the generated stored column `fts = to_tsvector('english', content)` (`0001_init.sql:79,82`).
- **Other indexes**:
  - `links(wiki_id, to_slug)` and `log(wiki_id, ts desc)`.
  - `page_chunks(wiki_id)` (btree).
  - Implicit indexes from the unique and primary-key constraints.
- **Not in the schema**: no CHECK constraints (`kind`, `type` and `status` are free text, with the allowed values only in comments), no triggers, no views. `wiki.search_pages` is the only function.
- **Foreign keys**:
  - Everything cascades from `wikis`.
  - `changesets.job_id` and `changesets.source_id` are `on delete set null`.
  - `page_versions.job_id` has no FK.
  - `links.to_slug` is a slug, not an FK, so it can point at a missing page.
- **Mixed search**: in the RRF fusion, a full-text query that matches nothing gives `tsq` = null, so only semantic hits count.

#### `app/migrate.py`
- `python -m app.migrate` connects with `psycopg.connect(url, autocommit=True, connect_timeout=15)` (`:41`).
- Then (`:50-63`):
  1. `set search_path = public, extensions`.
  2. `create schema if not exists wiki`.
  3. Creates the tracking table `wiki.schema_migrations (name text primary key, applied_at timestamptz default now())`.
  4. Applies each `sorted(MIGRATIONS.glob("*.sql"))` file not yet recorded (lexical filename order), each in its own transaction, then inserts its name. It prints `applied <f>` and finally `migrations up to date`.
- There are no down migrations.
- Failures go through `_explain` (`:12-26`), which gives hints for localhost, the Supabase direct IPv6 host, port 6543 (transaction pooler; use session pooler 5432), and a wrong password. `_redacted` hides the password in the "invalid URL" message (`:29-36`).
- Note: 0001 uses plain `create table` (not `if not exists`). It relies on the tracking table and fails on a DB that already has the tables but no tracking row [inference].

### 4.3 Benchmark and Ask schema (`Benchmark/migrations/*.sql`, applied by `Benchmark/bench/migrate.py`)

**0001_init.sql**
```sql
create schema if not exists bench;

-- One benchmark run. `results` has the same shape the CLI used to write to results.json.
create table if not exists bench.runs (
  id text primary key,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),  -- heartbeat: bumped on every save
  status text not null default 'queued',  -- queued | running | finished | failed
  results jsonb not null default '{}'::jsonb,
  log text not null default '',
  topics text not null default '',
  runs int not null default 3,
  wiki_slug text not null default 'ifrs9',
  query_set_name text,
  query_set bytea,
  reference_name text,
  reference bytea
);
create index if not exists runs_created_idx on bench.runs (created_at desc);
```

**0002_rag_collection.sql**
```sql
-- Which RAG collection a run compares with its wiki
alter table bench.runs add column if not exists rag_collection text;
-- Runs from before RAG collections searched every RAG document; those all now sit in the "ifrs9" collection
update bench.runs set rag_collection = 'ifrs9'
where rag_collection is null and exists (select 1 from public.collections where slug = 'ifrs9');
```

**0003_sources.sql**
```sql
-- Which sources both systems may use in a run: 'standard' (Part A only) or 'all' (Parts A, B and C)
alter table bench.runs add column if not exists sources text;
-- Runs from before the switch had no restriction
update bench.runs set sources = 'all' where sources is null;
```

**0004_rubrics.sql**
```sql
-- Saved rubrics: the key points Claude makes from each topic's reference answer, built once per reference file
-- (identified by the file's SHA-256) and reused by every run with that file, so runs are scored against the same checklist
create table if not exists bench.rubrics (
  reference_sha256 text not null,
  topic_number int not null,
  reference_name text,
  topic_title text not null,
  key_points jsonb not null,
  key_points_usage jsonb,
  judge_model text,
  source_run text,  -- the run it was built in or copied from ("rebuild" when rebuilt on purpose)
  created_at timestamptz not null default now(),
  primary key (reference_sha256, topic_number)
);
```

**0005_use_saved.sql**
```sql
-- Whether the wiki also read saved answers (synthesis pages filed with Save) in a run. Null: older runs, before the setting.
alter table bench.runs add column if not exists use_saved boolean;
```

**0006_ask_chats.sql**
```sql
-- Saved chats on the Ask screen. Each message records which side(s) were asked, the question as typed, the full
-- question actually searched (follow-ups are rewritten from earlier questions only), the Sources setting and the answers.
create schema if not exists ask;

create table if not exists ask.chats (
  id uuid primary key default gen_random_uuid(),
  title text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists ask.messages (
  id bigserial primary key,
  chat_id uuid not null references ask.chats(id) on delete cascade,
  seq int not null,
  question text not null,                 -- as typed
  searched text not null,                 -- the full question sent to RAG and/or the wiki
  mode text not null check (mode in ('rag', 'wiki', 'both')),
  sources text not null check (sources in ('standard', 'all')),
  rag_collection text,
  wiki_slug text,
  rag jsonb,                              -- {answer, sources, ms, error}
  wiki jsonb,                             -- {answer, pages, ms, error}
  created_at timestamptz not null default now(),
  unique (chat_id, seq)
);
create index if not exists messages_chat on ask.messages (chat_id, seq);
```

**0007_run_mode.sql**
```sql
-- Quick (default): answers, the existing grading and the answer checks; Full: also faithfulness and context recall.
-- use_batch: grading through the Message Batches API (half price), falling back to the normal API.
alter table bench.runs add column if not exists mode text;
alter table bench.runs add column if not exists use_batch boolean;
```

**0008_rubric_review.sql**
```sql
-- Rubric review: you approve (or change) each topic's key points and its exact-match facts. Every change makes a new
-- version, kept in bench.rubric_versions; each run records the version of each topic's rubric it used.
-- Key point tags: standard (the Standard, Part A), supporting (documents published with it, Parts B and C),
-- beyond_standard (practice, regulation, opinion).
alter table bench.rubrics add column if not exists version int not null default 1;
alter table bench.rubrics add column if not exists reviewed_at timestamptz;        -- key points approved
alter table bench.rubrics add column if not exists facts jsonb;                    -- exact-match facts [{id, fact}]
alter table bench.rubrics add column if not exists facts_reviewed_at timestamptz;  -- facts approved

create table if not exists bench.rubric_versions (
  reference_sha256 text not null,
  topic_number int not null,
  version int not null,
  key_points jsonb not null,
  facts jsonb,
  reviewed_at timestamptz,
  facts_reviewed_at timestamptz,
  note text,
  created_at timestamptz not null default now(),
  primary key (reference_sha256, topic_number, version)
);

insert into bench.rubric_versions (reference_sha256, topic_number, version, key_points, facts, note, created_at)
select reference_sha256, topic_number, version, key_points, facts, 'as built', created_at from bench.rubrics
on conflict do nothing;
```

**0009_facts.sql**
```sql
-- Exact-match facts: the judge call that made each topic's list (its tokens and model), like the key points.
alter table bench.rubrics add column if not exists facts_usage jsonb;
alter table bench.rubrics add column if not exists facts_model text;
```

**0010_rubric_v3.sql**
```sql
-- Suggested rubric changes (tags with the backing paragraph, list merges, a hard-fact list), stored with each topic until
-- you accept or reject them on the Rubric review screen. Accepting and saving makes a new version; nothing else changes.
alter table bench.rubrics add column if not exists suggestions jsonb;
```

**0011_reference_labels.sql**
```sql
-- Reference memos are shown by a neutral label you can rename ("Reference memo 1"), never by their file name. Keyed by
-- the file's SHA-256, so existing rubrics and runs stay linked as they are.
-- tag_sources: the source documents you ticked for the rubric tag check (null = all); used by the next Suggest changes.
create table if not exists bench.references (
  reference_sha256 text primary key,
  label text not null,
  tag_sources jsonb,
  created_at timestamptz not null default now()
);

insert into bench.references (reference_sha256, label, created_at)
select sha, 'Reference memo ' || row_number() over (order by first_seen), first_seen
from (select sha, min(first_seen) as first_seen
      from (select encode(sha256(reference), 'hex') as sha, min(created_at) as first_seen from bench.runs where reference is not null group by 1
            union all
            select reference_sha256, min(created_at) from bench.rubrics group by 1) s
      group by sha) x
on conflict do nothing;

-- The documents a topic's approved tags were checked against, kept with each version
alter table bench.rubrics add column if not exists tag_sources jsonb;
alter table bench.rubric_versions add column if not exists tag_sources jsonb;
```

**migrate.py logic:**
- It connects with `psycopg.connect(url, autocommit=True, connect_timeout=15)`. On failure it exits with hints for localhost, the IPv6 Supabase host, port 6543, and wrong-password errors (`_explain`). An unparseable URL is printed redacted (`_redacted`).
- It runs `create schema if not exists bench` and `create table if not exists bench.schema_migrations (name text primary key, applied_at timestamptz default now())` (L51-52).
- Each `migrations/*.sql` file not yet in schema_migrations is applied in sorted order, inside one transaction per file, and its name is inserted (L54-60).

Not created here: 0002 references `public.collections`, and `library.py` reads `wiki.sources`. Both belong to the RAG and Wiki schemas.

---

### 4.4 Other persistent state

- **Supabase Storage** holds original uploads, but only when `SUPABASE_SECRET_KEY` is set. They go in the private bucket `STORAGE_BUCKET`, default `sources`, which is created on first use. Object keys are `rag/<document_id>/<file>` for the RAG (`Rag/app/storage.py:object_path`) and `wiki/<wiki_id>/<source_slug>/<file>` for the Wiki (`Wiki/app/storage.py:object_path`). The record `{bucket, path, content_type, size}` is kept in `public.documents.file` and in `wiki.sources.meta.file`.
- **Wiki index and log files.** No `index.md` or `log.md` file is stored. Both are rendered from the database on request (`Wiki/app/wiki/store.py:render_index`, `render_log`).
- **In-process state (lost on restart):**
  - Wiki job tasks and per-wiki locks (`Wiki/app/jobs.py`).
  - The UI server's running bulk jobs (`UI/server/app/bulk.py`).
  - Spawned benchmark processes (`UI/server/app/bench.py:_procs`).
  - The memo-label cache (`bench.py:_ref_cache`).
- **Browser storage.** The only browser storage is `localStorage` key `rag-collection`, which remembers the chosen RAG collection (`UI/web/src/app/core/collections.ts`).
- **No seed data.** No seed data is shipped. `Rag/supabase/config.toml` references `./seed.sql`, which does not exist. The only data migration is the backfill in `Rag/supabase/migrations/20261013000000_collections.sql`, which moves pre-existing documents into an `ifrs9` collection.

## 5. RAG pipeline (the control)

The RAG API is a conventional retrieve-then-generate service over IFRS paragraphs. Its prompts are reproduced in §7.1.

### 5.1 Service bootstrap and authentication

**`Rag/run.py`**
- Uses argparse: `--host` defaults to `"127.0.0.1"`, `--port` defaults to `8000` (int) (lines 11-12).
- Builds `uvicorn.Server(uvicorn.Config("app.main:app", host, port))`.
- On `win32` it runs inside `asyncio.SelectorEventLoop(selectors.SelectSelector())`, because psycopg async does not support the Proactor loop (lines 16-17). Elsewhere it uses plain `asyncio.run(server.serve())`.

**`Rag/Dockerfile`**
- `FROM python:3.12-slim`, with `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1`, `WORKDIR /app`.
- The build context is the repo root ("see render.yaml"). It copies `Rag/requirements.txt`, runs `pip install --no-cache-dir`, then `COPY Rag/ .`.
- `EXPOSE 10000`. CMD: `sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"`.
- A comment says migrations run as Render's pre-deploy command (`python -m app.migrate`).

**`Rag/app/main.py`**
- `logging.basicConfig(level=logging.INFO)`.
- `FastAPI(title="RAG API", version="0.1.0", lifespan=lifespan)` (line 29).
- `lifespan` calls `get_settings()` to fail fast on missing env, then `await db.open_pool()`, yields, then `db.close_pool()` (lines 21-26).
- Auth:
  - `APIKeyHeader(name="X-API-Key", auto_error=False)`.
  - `require_api_key` raises `HTTPException(401, "Invalid or missing API key")` if the key is missing or `not secrets.compare_digest(key, get_settings().api_key)`, a constant-time comparison (lines 13-18).
  - It is applied as a router dependency (`auth = [Depends(require_api_key)]`) to the `collections`, `documents`, `query` and `bulk` routers, in that order (lines 30-34).
- `GET /health` is not authenticated. It runs `select 1` on a pooled connection and returns `{"status":"ok"}` (lines 37-41).
- **No CORS middleware is configured anywhere in Rag/.** There is no `CORSMiddleware`, so browser calls from another origin would be blocked unless they are proxied. [UNVERIFIED] whether a proxy handles this; it is outside this scope.

**`Rag/app/db.py`**
- A global `AsyncConnectionPool(database_url, min_size=1, max_size=settings.db_pool_max, configure=_configure, open=False)`.
- `_configure` calls `register_vector_async(conn)` (pgvector) and sets `row_factory = dict_row`.
- `get_pool()` asserts the pool is open.

### 5.2 Ingestion: parsing, IFRS paragraph detection, chunking, embedding, storage

**Dispatch** (`Rag/app/ingest/pipeline.py:parse_file`, lines 25-37). `max_words = settings.chunk_max_words` (500).
- `.pdf`:
  - Open with `pymupdf.open(stream=data, filetype="pdf")`, then `pdf_ifrs.parse_document(doc, max_words)`.
  - Layout `"standard"` → parser `"ifrs"`.
  - Layout `"accompanying"` → parser `"ifrs_accompanying"`.
  - Otherwise → parser `"generic_pdf"`, `chunk_plain([p.get_text() for p in doc], max_words)`, plus one warning:
    - `UNRECOGNISED_IFRS` if `looks_like_ifrs(doc)`: "This PDF looks like an IFRS publication, but its paragraph numbering was not recognised: the text was kept as page-by-page chunks, without paragraph numbers."
    - otherwise `NOT_IFRS`: "This PDF does not have the IFRS layout: the text was kept as page-by-page chunks, without paragraph numbers."
- Anything else (`.txt` or `.md`) → parser `"text"`, `chunk_plain([data.decode("utf-8", errors="replace")], max_words)`. The whole file is one "page", so page=1. Markdown structure is not parsed.

**`ingest`** (`pipeline.py`, lines 40-80):
1. Compute the file's sha256.
2. If `(collection_id, sha256)` already exists, raise `DuplicateDocument(id)`.
3. Parse. Zero chunks raises `ValueError("No text extracted from document")`.
4. `llm.embed([c.embed_text() ...])`. This happens **before** the DB transaction.
5. In one transaction: insert the `documents` row (collection_id, filename, sha256, parser), then `executemany` the chunks (document_id, para_ref, part, source_type, page, heading, content, embedding as `np.float32`).
6. After commit: `storage.put(object_path("rag", <doc_id>, filename), data, content_type(filename))`. If that returns a record, `update documents set file = jsonb`.
7. Returns `{document_id, filename, parser, chunks, by_source_type: {type: count}, warnings}`.

**Source-type constants** (`Rag/app/ingest/models.py`):
- `BINDING_TYPES = ("standard","appendix_a","appendix_b","general")`
- `STANDARD_TYPES = ("standard","appendix_a","appendix_b")`
- `ACCOMPANYING_TYPES = ("example","implementation_guidance","basis_for_conclusions","dissenting_opinion")`
- `NON_BINDING_TYPES = ("note","intro","appendix_c","back_matter")`
- `ALL_TYPES` = the concatenation of all of the above.

**`Chunk` dataclass:** `para_ref: str|None, source_type, page: int, heading: str|None, content, part: int = 0`.

**`Chunk.embed_text()`** (lines 24-26): `head = " | ".join(x for x in (para_ref, heading) if x)`, then returns `f"{head}\n{content}"` if head, else `content`. So the embedded text is "para_ref | heading" plus a newline plus the content.

**Generic chunker** (`Rag/app/ingest/text.py`):
- `clean`: collapses whitespace with `_WS = re.compile(r"\s+")`, then `re.sub(r"\s+([,.;:)])", r"\1", ...)` removes spaces before punctuation.
- `_SENT = re.compile(r"(?<=[.;:])\s+")` is the sentence splitter. It also breaks after `;` and `:`.
- `split_long(text, max_words)`: returns `[text]` if it has ≤ max_words; otherwise greedily packs sentences up to max_words. A single sentence longer than the limit is kept whole.
- `chunk_plain(pages, max_words=400, overlap=50)`. The defaults are overridden by the caller: max_words=500 comes from settings, and the overlap stays at `50` words.
  - Per page, it splits paragraphs on `\n\s*\n` and cleans them.
  - It packs pieces into a buffer. When adding a piece would exceed max_words, it emits a chunk, and the new buffer starts with the last 50 words of the emitted chunk.
  - Chunks never cross pages. Fields: `para_ref=None, source_type="general", heading=None, part=0`.

**IFRS PDF parser** (`Rag/app/ingest/pdf_ifrs.py`)

The docstring lists the layout facts it relies on:
- Paragraph numbers sit in the left margin in the "Swift" font.
- Editorial text uses `HelveticaLTPro-BoldCond`.
- Headings use HelveticaLTPro Bold/Oblique at ≥ 9.5pt.
- The running header and footer use HelveticaLTPro-Roman at 9pt.

Constants (verbatim):
```python
PARA_RE = re.compile(r"^(?:B|C|BCZ?|IE|IG)?\d+(?:\.\d+)*[A-Z]{0,2}$")
ACCOMPANYING_RE = re.compile(r"^(IE|IG|BC[A-Z]{0,3}|DO)(?:\d+|\.\d+)(?:\.\d+)*[A-Z]{0,2}$")
ACCOMPANYING_KINDS = {"IE": "example", "IG": "implementation_guidance", "DO": "dissenting_opinion"}  # BC... -> basis_for_conclusions
RANGE_DASH = ("–", "-")
EDITORIAL_BRACKETS = re.compile(r"\[(?:Refer|Note|Link|now)\b[^\]]*\]", re.I)
MARGIN_MAX_X = 150
HEADER_Y, FOOTER_Y = 110, 720
```

Helper functions:
- **`_is_editorial(font, size=8.5, x=999)`**: `"BoldCond" in font or (font == "HelveticaLTPro-Bold" and size < 9 and x < 175)`. The second case catches IFRIC box sub-headings.
- **`_is_heading(font, size)`**: `font.startswith("HelveticaLTPro") and not _is_editorial(font) and "Roman" not in font and size >= 9.4`. The code uses 9.4; the docstring says 9.5.
- **`looks_like_ifrs`**: scans the first `min(page_count, 40)` pages and counts spans with `x0 < 150`, a font starting with `"Swift"` and text matching `PARA_RE`. It is true if there are `>= 10` hits.
- **`_lines(page)`**:
  - Collects non-blank spans, sorted by (y0, x0).
  - Groups spans into rows when y0 is within `3` points of the row's first span.
  - Yields each row sorted by x, so a margin label comes first on its row.
- **`_section_for_heading(text, current)`**, lower-cased:
  - starts with "international financial reporting standard" → `standard`
  - exactly "appendix a" / "appendix b" / "appendix c" → `appendix_a` / `appendix_b` / `appendix_c`
  - starts with "approval by the board", "basis for conclusions" or "dissenting" → `back_matter`
  - otherwise unchanged
  - The initial section is `intro`.
- **`_join`**: joins parts with a space, except it de-hyphenates when the previous text ends with "-" and the next part starts lower-case. It then runs `clean`.
- **`accompanying_kind(ref)`**: matches `ACCOMPANYING_RE` on the ref after stripping range dashes. IE, IG and DO map through the dict, any `BC*` prefix gives `basis_for_conclusions`, and no match gives `intro`.

**`parse_document(doc, max_words=500)`** (lines 112-126):
1. If `looks_like_ifrs`, run `parse(doc)` in Standard mode. If any chunk has `source_type == "standard"`, return layout `"standard"`.
2. Otherwise run `parse(doc, accompanying=True)`. If any chunk has a type in ACCOMPANYING_TYPES, return layout `"accompanying"`.
3. Otherwise return the step-1 chunks (possibly empty) with layout `""`. The pipeline then **discards** them and uses generic chunks.
- A short accompanying document can fail `looks_like_ifrs` and still be recognised in step 2.

**`parse(doc, max_words=500, accompanying=False)`**, per span in row order:
1. **Skip** a span if `"Roman" in font and size >= 8.9 and (y < 110 or y > 720)` (header/footer), or if `size < 6` (superscript footnote markers).
2. **Headings:** when `_is_heading`:
   - Multi-line headings join when they are on the same page, have the same (font, size), and `0 <= y - prev_y < 14`.
   - In Standard mode `_section_for_heading` can change the section. A change flushes the current paragraph and starts an unlabelled one.
   - `heading` is set to the joined heading text; the span is consumed.
   - In accompanying mode the section never changes.
3. **Accompanying-mode labels:** a label is a span with `x < 150`, a Swift font, and text (after stripping range dashes) matching `ACCOMPANYING_RE`.
   - Range continuation: if the current ref ends with a dash and the last label was on the same page with `0 < dy < 14`, the text is appended to the ref (e.g. `BC2.17A–BC2.17H`).
   - Otherwise it flushes and starts `_Para(text, accompanying_kind(text), page, heading)`.
4. **Standard-mode labels:** a span is a label when all of these hold:
   - `section in ("standard","appendix_a","appendix_b","appendix_c")`
   - `x < 150`
   - the font starts with "Swift"
   - `PARA_RE.match(text)`, or (in `appendix_a`) the font contains "Bold". This is how Appendix A defined terms become labels.
   - In appendix_a, a label on the same page within `0 < dy < 13` of the previous label is appended to the ref with a space (multi-line defined terms). Otherwise it flushes and starts a new paragraph.
   - In the `intro` and `back_matter` sections no labels are recognised. All text accumulates into unlabelled paragraphs (para_ref None).
5. **Body text:** if `_is_editorial(font, size, x)`, the text goes to `cur.notes`; otherwise to `cur.body`.

Building chunks from the paragraphs:
- Appendix A refs get the prefix `"Appendix A: "` (for example "Appendix A: credit loss").
- Body = `clean(EDITORIAL_BRACKETS.sub("", _join(body)))`, which removes inline `[Refer…]`, `[Note…]`, `[Link…]` and `[now…]`. It is split with `split_long(max_words)`; chunk `part` = index i, source_type = the paragraph's section or kind.
- Notes = `_join(notes)`, kept only if it has **more than 5 words**. They are split the same way into chunks with `source_type="note"`, the same ref, page and heading.
- So one paragraph can yield body parts 0..n and note parts 0..m that share a para_ref.
- `page` is the page where the label appeared, even if the text continues onto later pages.
- Body chunks are never merged or overlapped: one IFRS paragraph gives ≥ 1 chunks, with no overlap.

**Embedding** (`Rag/app/llm.py:embed`, lines 64-74):
- Model `settings.gemini_embed_model` (`gemini-embedding-001`).
- `EmbedContentConfig(task_type=task, output_dimensionality=768)`. Documents use `task="RETRIEVAL_DOCUMENT"`; queries use `embed_query` → `"RETRIEVAL_QUERY"`.
- Batches of `embed_batch=100` via `client().aio.models.embed_content`.
- Each vector is L2-normalised (`_normalize`; a zero vector is left as is).
- Each batch records a usage entry `{"step":"embed","model","texts","chars","input_tokens":None,"output_tokens":None}`.

**Storage** (`Rag/app/storage.py`):
- Enabled only if `supabase_secret_key` is set and `base_url()` resolves. That is `supabase_url`, or `https://<ref>.supabase.co` taken from a DATABASE_URL user `postgres.<ref>` (regex `r"://postgres\.([a-z0-9]+)[:@]"`).
- Bucket `settings.storage_bucket` (default `sources`). `_ensure_bucket` runs once per process and creates the bucket `{"public": False}` if `GET /bucket/{b}` is not 200.
- Object path: `rag/<document_uuid>/<sanitised filename>`. `object_path` replaces `[^\w.\- ()]` with `_` (empty name → `file`).
- Upload: `POST /storage/v1/object/{bucket}/{path}` with `x-upsert: true`. The httpx client has `timeout=120`.
- Headers: `apikey` always. `Authorization: Bearer` is added only if the key starts with `eyJ` (a legacy JWT).
- The record stored in `documents.file` is `{"bucket","path","content_type","size"}`.
- Upload failures are logged and return None; the ingest never fails because of storage.
- `CONTENT_TYPES`:
  - `.pdf` → application/pdf
  - `.docx` → the OOXML type
  - `.md` / `.markdown` → text/markdown
  - `.txt` → text/plain
  - anything else → application/octet-stream
- `signed_url(file, expires_s=3600)`: POSTs `/object/sign/...` with `{"expiresIn":3600}` and re-encodes the path.
- `remove`: `DELETE /object/{bucket}` with `{"prefixes":[path]}`; errors are logged and swallowed.

**`Rag/app/attach_file.py`** (`python -m app.attach_file <path>`):
- Backfills stored originals for documents ingested before storage existed.
- Finds every document with a matching sha256 across all collections, uploads to `rag/<doc_id>/<doc filename>`, and sets `documents.file`.
- Exits with an error if storage is disabled, nothing matches, or an upload fails.

### 5.3 Retrieval: hybrid full-text + vector search fused with RRF

**`search(query, k, include_types=None, include_editorial=False, embedding=None, collection_id=None)`** (lines 23-40):
- If no embedding is passed, it calls `embed_query` (RETRIEVAL_QUERY, 768 dimensions, normalised).
- `exclude = None if (include_editorial or include_types) else list(NON_BINDING_TYPES)`. Passing any `source_types` therefore turns off the editorial exclusion, and the include list alone governs.
- SQL: `select * from hybrid_search(%s, %s, %s, %s, %s, p_collection_id => %s)`. `full_text_weight=1`, `semantic_weight=1` and `rrf_k=50` are always the SQL defaults; Python never overrides them.

**Fusion** (in SQL):
- Full-text: `plainto_tsquery('english', q)` with `&` replaced by `|`, so terms are OR'ed. Matches are ranked by `ts_rank_cd` (cover density). There are `match_count*2` candidates.
- Semantic: ranked by cosine distance `<=>`, also `match_count*2` candidates.
- RRF: `score = 1/(50+rank_ft)*1 + 1/(50+rank_sem)*1`, with a missing side counting 0. The two lists are joined with a full outer join, ordered by score desc, `limit match_count`.
- Defaults: k=8 gives 16 candidates per side; bulk k=6 gives 12 per side.

**Defaults:**
- `top_k` is 8 (settings). The query request can override it within 1..50.
- By default, `note`, `intro`, `appendix_c` and `back_matter` are excluded; Standard, appendices A/B, `general` and the accompanying types (IE/IG/BC/DO) are included.

**`sources` switch** (`Rag/app/routers/query.py:_retrieve`, lines 61-66):
- When `sources == "standard"`: `types = [t for t in (types or STANDARD_TYPES) if t in STANDARD_TYPES]`, which gives a Part A-only include list.
- Caveat: if the user's `source_types` has no Part A types, the list becomes `[]`. An empty list is not None, so in SQL `c.source_type = any('{}')` is false and nothing is returned. Python also sees `include_types=[]` as falsy, so `exclude` is the NON_BINDING list. [UNVERIFIED in a run, but this follows from the code.]
- `"all"` (the default) uses the types as given.

**Collection scoping:** `p_collection_id` = the collection's id for the query and bulk endpoints. `search` with `collection_id=None` searches all collections, but no router does that except `/search/paragraphs`, which uses its own SQL.

**Other functions:**
- `chunk_id(row)` = `f"C{row['id']}"`.
- `cite_key(row)` = `para_ref` or `chunk_id`.
- `SOURCE_LABELS` maps each type to a display label, e.g. `appendix_b` → "Application Guidance" and `appendix_a` → "Appendix A (defined term)".

**`format_context(rows, with_ids=False)`** (lines 51-57, verbatim):
```python
blocks.append(f"[{cite_key(r)}] ({kind}, page {r['page']}{ids})\n{r['content']}")
return "\n\n---\n\n".join(blocks)
```
- `ids = f" | passage id {chunk_id(r)}"` when `with_ids` is set; bulk sets it, query does not.
- Document names are not included in the context, so passages from several documents in one collection that share a para_ref look the same to the model.

**`citation(row)`:** `{chunk_id, para_ref, source_type, page, heading, snippet: content[:300], score: round(score, 5)}`.

**`POST /search/paragraphs`** (`query.py`, lines 18-49):
- Body `ParagraphSearchIn {text: str min_length=3, k: int = 8 (1..30), filenames: list[str] | None}`.
- Pure vector search (no FTS, no RRF), across **all collections**: `embedding <=> emb`.
- Filters: `para_ref is not null` and source_type not in ('note','intro','back_matter','appendix_c'); optionally `d.filename = any(filenames)`.
- Fetches `k*4` rows, de-duplicates by (filename, para_ref), and returns up to k items of `{filename, para_ref, source_type, similarity: round(1-distance, 4)}`.
- The docstring says it is used by the benchmark's rubric tag check. It needs the API key (query router).

### 5.4 Generation, citations and streaming (prompt text also in §7.1)

**`Rag/app/llm.py`**
- The client is `genai.Client(api_key=...)`, `lru_cache`d.
- Chat model `gemini-2.5-flash`, `temperature=0.1`, via `GenerateContentConfig(system_instruction=system, temperature=...)`.
- **No thinking config is set** (no `thinking_config` / thinking budget), so the model's default thinking applies. `thoughts_token_count` is recorded only as `thinking_tokens`.
- No max_output_tokens, top_p or safety settings are set.

**Retry** (`_retry`, lines 22-31):
- `attempts=5`, `RETRYABLE = {429, 500, 502, 503, 504}`.
- Delay `2 ** i * 2` seconds, i.e. 2, 4, 8, 16. The fifth failure raises.
- Only `google.genai.errors.APIError` is caught. For `stream`, only creating the stream is retried, not errors mid-stream.

**`generate(system, prompt, schema=None)`:**
- With a schema it sets `response_mime_type="application/json"` and `response_json_schema=schema`.
- It records usage with step `"answer"` (no schema) or `"json"` (schema): `{step, model, input_tokens: prompt_token_count, output_tokens: candidates_token_count, thinking_tokens: thoughts_token_count}`.
- Returns `resp.text or ""`.

**`stream`:** `generate_content_stream` yields `chunk.text`. **No usage is recorded for the stream.**

**Usage ContextVar:** `_usage = ContextVar("llm_usage", default=None)`.
- `track_usage()` sets a fresh list, and `_record` appends to it if set.
- Tasks created afterwards inherit the context, so the `asyncio.gather` searches contribute.
- Only `/query` calls `track_usage`. Bulk does not, so bulk usage is not returned.

**Prompts** (`Rag/app/prompts.py`, verbatim)

`QUERY_SYSTEM`:
```
You answer questions using ONLY the passages provided in <context>.
Rules:
- Every statement must be supported by a passage. Do not use general knowledge.
- Each passage starts with its citation key in square brackets, e.g. [5.5.3], [B5.5.17], [Appendix A: credit loss].
- Cite inline by copying that key exactly, including the brackets, e.g. [5.5.3]. Cite several as [5.5.3][B5.5.17]. Never invent or alter keys, never cite page numbers.
- When the Standard allows or requires something only "if", "provided that", "unless" or "only when", state every condition in full.
- If the passages do not answer the question, say so plainly rather than guessing.
- Be concise.
```

`query_prompt(question, context)` → `f"<context>\n{context}\n</context>\n\nQuestion: {question}"`

`BULK_SYSTEM`:
```
You write IFRS requirement blocks using ONLY the passages provided in <context>.
The passages are the binding text of the Standard. Follow the run rules and the topic instructions exactly.
Do not use general knowledge. If a question cannot be answered from the passages, list it as not addressed.
Return JSON matching the schema. Do not put IFRS paragraph numbers in the prose; put them in the source list.
```

`BULK_SCHEMA` (verbatim):
```python
{"type":"object","properties":{
  "prose_paragraphs":{"type":"array","description":"Requirement text, one string per prose paragraph, no IFRS paragraph numbers.","items":{"type":"string"}},
  "source_list":{"type":"array","description":"One row per prose paragraph, same order.","items":{"type":"object","properties":{
      "para":{"type":"integer","description":"1-based prose paragraph number"},
      "covers":{"type":"string","description":"What it covers, a few words"},
      "ifrs_paragraphs":{"type":"array","items":{"type":"string"}},
      "passage_ids":{"type":"array","items":{"type":"string"},"description":"Passage ids, e.g. C123"}},
    "required":["para","covers","ifrs_paragraphs","passage_ids"]}},
  "not_addressed":{"type":"array","items":{"type":"object","properties":{"question":{"type":"string","description":"e.g. Q3"},"note":{"type":"string"}},"required":["question","note"]}},
  "standard_version":{"type":"string","description":"Version of the Standard used, if stated in the passages"}},
 "required":["prose_paragraphs","source_list","not_addressed"]}
```

`bulk_prompt(rules, topic_block, context)` → `f"<run_rules>\n{rules}\n</run_rules>\n\n<topic>\n{topic_block}\n</topic>\n\n<context>\n{context}\n</context>"`

`REVISE_INSTRUCTIONS`:
```
Review the draft against EVERY run rule and the SELF-CHECK list, then return the corrected block as JSON. In particular:
- Fix every detected issue.
- Remove any sentence not supported by a passage, and anything covered by the topic's "Leave out" line.
- No IFRS paragraph numbers in the prose; where the Standard names something only by number, use the name it gives it.
- Keep every "if", "provided that", "unless" and "only when" condition in full.
- Aim for roughly the word guide; cut repetition and supporting detail first, never required points or conditions.
- Every question is answered in the prose or listed under not addressed, after searching the passages.
- Source list: exactly one row per prose paragraph, citing only passage ids present in the context.
```

`revise_prompt(rules, topic_block, context, draft_json, issues)`:
- `found = "\n".join(f"- {i}" for i in issues) or "- (none detected automatically)"`
- returns `f"{bulk_prompt(...)}\n\n<draft>\n{draft_json}\n</draft>\n\n<detected_issues>\n{found}\n</detected_issues>\n\n{REVISE_INSTRUCTIONS}"`

**Citations** (`query.py`):
- `CITE_RE = re.compile(r"\[([^\[\]]+)\]")`.
- `_cited(answer, rows)`:
  - refs = every bracket match, split on `,` and stripped.
  - hit = rows whose `para_ref` or `C<id>` is in refs.
  - Returns `citation()` for the hits, **or for all retrieved rows if nothing matched** (fallback).
- A para_ref shared by several chunks (body parts or notes) returns all of them.
- Citations are matched only against the retrieved rows; an invented key is silently dropped.

**`POST /collections/{c}/query`** (lines 75-86) returns:
- `answer`
- `citations`: list of citation dicts
- `read`: every passage given to the model, as `{chunk_id, para_ref, source_type, page, document_id, content}`
- `usage`: the list of embed and answer call records
- With no rows: `{"answer":"No relevant passages found.","citations":[],"read":[],"usage":usage}` and no LLM call.

**`POST /collections/{c}/query/stream`** (lines 89-106) returns an `EventSourceResponse` with these events:
- `token`, whose data is `json.dumps(text_piece)` (a JSON string)
- then `citations` (JSON array)
- then `done` (empty data)
- With no rows it sends one token, "No relevant passages found.", then `citations` `[]`, then `done`.
- It has no `read` and no `usage`. Retrieval happens before the response starts.

### 5.5 Bulk requirement blocks

Regexes and constants:
- `TOPIC_RE = re.compile(r"^TOPIC (\d+) of (\d+):\s*(.+)$", re.M)`
- `DROP_RULE_RE = re.compile(r"^(HOW THIS RUN WORKS:|END OF EACH REPLY:|Rule 12 in bulk mode:).*$", re.M)`: chat-only rule lines removed from the rules
- `PARA_NUM_RE = re.compile(r"\b(?:B|BC|IE|IG)?\d+\.\d+(?:\.\d+)*[A-Z]?\b")`
- `WORD_TOLERANCE = 0.25`

**`parse_query_set(text)`:**
- Normalises CRLF.
- Rules = the text before the first TOPIC, with the DROP lines removed and a trailing `=+` stripped.
- Each topic block runs to the next TOPIC. Text from `\n=+\s*\nEND OF TOPICS.*` onwards is removed.
- `Topic` fields:
  - number and title, from the TOPIC line
  - `row_label`: the `Row label:` line
  - `word_guide`: from `about (\d+) words` in `Word guide:`
  - `leave_out`: the `Leave out:` line
  - `search_terms`: `Search terms:`, comma-split
  - `questions`: lines matching `^Q\d+\..*$`
- No TOPIC lines raises `ValueError` → 422.

**`_retrieve(topic, collection_id)`:**
- Queries = `[f"{title}. {', '.join(search_terms)}"] + questions`.
- One batched `embed(..., task="RETRIEVAL_QUERY")`.
- Parallel `retrieval.search(q, k=6, embedding=e, collection_id)`. Default editorial exclusion, no type filter, so accompanying types are included even though BULK_SYSTEM calls the passages "the binding text of the Standard".
- Round-robin merge by rank up to `bulk_max_chunks=30` unique chunks.

**`run_topic`:**
1. Context comes from `format_context(rows, with_ids=True)`.
2. Draft: `generate(BULK_SYSTEM, bulk_prompt, schema)`, then `json.loads`.
3. `check()` gives the draft issues:
   - paragraph numbers in the prose
   - word count > guide × 1.25
   - source_list length ≠ number of prose paragraphs
   - unknown passage ids
4. If `revise` (default True): a second generate with `revise_prompt`. Final `issues` = `check()` on the revised output.
5. Returns:
   - `revised`, `draft_issues`, `issues`
   - `topic_no`, `title`, `row_label`
   - `word_guide`, `word_count`
   - `prose_paragraphs`, `source_list`, `not_addressed`, `standard_version`
   - `answer_markdown`: from `_render`, i.e. `### title`, the bold row label, the prose, a Source list table with columns "Para | What it covers | IFRS paragraphs used | Passage / claim IDs", "Not addressed in the Standard", and "Word count"
   - `citations` (cited passage ids that were retrieved)
   - `unknown_passage_ids`
   - `retrieved` (count)

**`run(text, collection_id, only, revise)`:**
- Filters topics by number.
- `Semaphore(bulk_concurrency=3)`.
- A per-topic exception becomes `{"topic_no","title","error":"Type: msg"}`, and the other topics continue.
- Returns `{"topics_total": len(topics after filter), "topics": sorted by topic_no}`.

**Routes and limits:**
- `POST /collections/{c}/bulk`: multipart `file` (decoded as UTF-8 with replace), query `topics: list[int]|None`, `revise: bool = True`. The run is synchronous: one HTTP request covers all topics. There is no timeout, size cap or job queue.
- `POST /bulk/parse`: multipart `file`; no LLM and no collection. Returns `{"rules_chars", "topics": [Topic.__dict__ with block=None]}`. It still requires the API key.

### 5.6 HTTP endpoints

Everything except `/health` needs `X-API-Key`.

| Method | Path | Input | Output |
|---|---|---|---|
| GET | `/health` | none | `{"status":"ok"}` (no auth) |
| GET | `/collections` | none | rows `{id, slug, name, description, created_at, documents, chunks}`, ordered by created_at |
| POST | `/collections` (201) | `CollectionIn {slug: pattern ^[a-z0-9][a-z0-9-]{1,62}$, name: min_length 1, description: str = ""}` | the inserted row; 409 on a duplicate slug |
| PATCH | `/collections/{c}` | `CollectionPatch {slug?, name?, description?}` | updated row (unchanged row if no fields); 404 or 409 |
| DELETE | `/collections/{c}` (204) | none | cascades documents and chunks, then removes the stored files |
| POST | `/collections/{c}/documents` (201) | multipart `file`; extension must be in `(".pdf",".txt",".md")`, else 415 | ingest dict plus `collection` slug; 409 `{"message","document_id"}` for a duplicate; 422 for no text |
| GET | `/collections/{c}/documents` | none | `{id, filename, parser, created_at, has_file, chunks, collection}`, newest first |
| GET | `/documents` | none | the same, across all collections |
| GET | `/chunks` | query `para_ref` (required), `document_id: UUID?`, `collection: slug?`, `include_notes: bool=False` | rows `{id, para_ref, part, source_type, page, heading, content, filename, document_id}`, ordered by doc created_at, non-notes first, then part; 404 if none. Exact `para_ref` match. |
| GET | `/documents/{doc_id}/file` | none | `{url (signed, 3600s), name, content_type}`; 404, 503 (storage off) or 502 |
| DELETE | `/documents/{doc_id}` (204) | none | deletes the doc (chunks cascade) and the stored file; 404 |
| POST | `/search/paragraphs` | `{text (min 3), k=8 (1..30), filenames?}` | `[{filename, para_ref, source_type, similarity}]` |
| POST | `/collections/{c}/query` | `QueryIn {question: min_length 3; top_k: int? 1..50 (None → 8); source_types: list[str]?; include_editorial: bool=False; sources: "standard"\|"all" = "all"}` | `{answer, citations, read, usage}` |
| POST | `/collections/{c}/query/stream` | same `QueryIn` | SSE `token`/`citations`/`done` |
| POST | `/collections/{c}/bulk` | multipart file, `?topics=`, `?revise=` | `{topics_total, topics[]}` |
| POST | `/bulk/parse` | multipart file | `{rules_chars, topics[]}` |

Validation and error notes:
- `source_types` values are **not validated** against ALL_TYPES; the description only lists them.
- `{c}` is looked up by slug via `collection_dep` (404 `"Collection '<c>' not found"`).
- Swagger is at `/docs` (README:16).

**Postman** (`Rag/postman/RAG_API.postman_collection.json`):
- Variables `baseUrl=http://127.0.0.1:8000`, `apiKey` (placeholder `change-me`), `documentId`, `collection=ifrs9`. Collection-level apikey auth puts `X-API-Key` in the header.
- Requests: Health; List, Create, Rename and Delete collection; Documents/Ingest file; List documents; Delete document; Query; Query (Application Guidance only, `source_types:["appendix_b"]`); Query stream; Bulk parse; Bulk one topic; Bulk all topics; Auth check with no key (expects 401).
- **Stale:** these requests use paths that no longer exist:
  - `POST {{baseUrl}}/ingest`
  - `POST {{baseUrl}}/query`
  - `POST {{baseUrl}}/query/stream`
  - `POST {{baseUrl}}/bulk`
  The real paths are collection-scoped, so these four would 404/405. Only "Bulk - one topic" uses `/collections/{{collection}}/bulk?topics=1&revise=true`.

### 5.7 Collections and documents behaviour

**Delete behaviour**
- Deleting a collection reads the `file` records of its documents first. It then runs `delete from collections` (FK cascade to documents and chunks) and best-effort removes each stored file.
- Deleting a document runs `delete ... returning file`, then removes the stored file.

**Uploads and duplicates**
- There is **no explicit upload size limit** in the app. The whole file is read into memory (`await file.read()`). Supabase Storage locally has `file_size_limit = "50MiB"` (config.toml); the hosted limit is [UNVERIFIED].
- Duplicate detection uses SHA-256 per collection, so a byte-identical file is refused (409) only within the same collection.
- There is no re-ingest or update path: you delete and then upload again.

**Documents and lookups**
- `.docx` is in the storage CONTENT_TYPES but **not** in ALLOWED, so it cannot be uploaded.
- PATCH builds `update collections set {k} = %(k)s`. The keys come only from the model fields, so it is safe.
- `GET /chunks` is not collection-scoped unless `collection` is passed.

## 6. Wiki pipeline (the system under test)

### 6.0 Overview, the schema document and page types

**The idea.** `Wiki/llm-wiki.md` is an abstract "idea file". Instead of retrieving raw chunks at query time, an LLM builds and maintains a persistent, interlinked markdown wiki between the user and the raw sources, governed by a schema document. The design names three operations: ingest, query and lint, plus an index and an append-only log. §11.1 lists what the code implements from that idea and what it does not.

**The schema document governs the wiki.**
- Every wiki stores its own schema in `wiki.wikis.schema_md` (`Wiki/migrations/0001_init.sql`).
- When a wiki is created without one, `Wiki/app/schema_default.md` is used (`Wiki/app/routers/wikis.py:DEFAULT_SCHEMA`, read at import).
- It can be replaced with `PUT /wikis/{w}/schema` (`routers/wikis.py`) or on the Settings tab of the UI (`UI/web/src/app/pages/wiki/settings.ts`).
- The schema is prepended to most LLM calls by `prompts.with_schema` (§6.14, §7.2).
- **The code also parses it.** Schema headings of the form `### NN. Name` define *sections* (`Wiki/app/ops/ingest.py:_sections`, regex `^###\s*(\d+)\.\s*(.+)$`). Each source paragraph is routed to exactly one section, and each section gets one `topic` page (§6.4).
- A section whose brief contains the word `ADDITIVE` collects one-line "also recorded here" entries from paragraphs owned by other sections (§6.4, step 2b).
- **The default schema has no `### NN.` sections**, so with it, ingest runs in the "no fixed sections" mode. Each planned page is then written from up to `page_source_words` = 12000 source words (`Wiki/app/config.py`). The section-based behaviour applies only to wikis whose schema defines numbered sections. The IFRS wikis' own schemas live in the database, not in the repository [UNVERIFIED: their content is not part of the codebase].

**Page types.** The complete list in the code is `PAGE_TYPES = ("overview", "topic", "concept", "entity", "comparison", "synthesis", "source")` (`Wiki/app/wiki/store.py:PAGE_TYPES`). The same seven appear in the comment on `wiki.pages.type` (`Wiki/migrations/0001_init.sql`); the database itself does not enforce them (no CHECK constraint). Their meaning is given only by the default schema (verbatim below). Which types the code itself creates:

| Type | Meaning (`schema_default.md`) | Created by |
|---|---|---|
| `overview` | the single top-level page `overview` | ingest forces it into every plan (`ops/ingest.py:422-424`); any other page typed overview is dropped |
| `source` | one per ingested source, `source-<name>` | ingest writes it as the 17th page of every ingest (`ops/ingest.py`, §6.4) |
| `topic` | a broader theme | ingest: the planner, and every schema section page is typed `topic` (`ops/ingest.py:430-440`) |
| `concept` | an idea, term, rule, method or definition | ingest planner (enum in `PLAN_SCHEMA`), lint "new page", manual edit default (`routers/pages.py:PageIn.type` default `concept`) |
| `entity` | a specific thing: organisation, standard, document, instrument | ingest planner and lint "new page" (enums in `Wiki/app/prompts.py`); never forced by code |
| `comparison` | a side-by-side analysis | ingest planner and lint "new page" enums; never forced by code |
| `synthesis` | an answer filed back from a query | only `save_answer` (Ask/query `save=true`) and `ops/synthesis.py:save`; ingest never writes or rewrites one (`ops/ingest.py:414-421`) |

**`Wiki/app/schema_default.md` (verbatim):**

```markdown
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
```

### 6.1 Service bootstrap and authentication

**run.py**
- Launcher. Its arguments are `--host`, default `127.0.0.1`, and `--port`, default `8001` (`run.py:11-12`).
- It runs `uvicorn.Server(uvicorn.Config("app.main:app", ...))` (`run.py:15`).
- On Windows it forces a `SelectorEventLoop(selectors.SelectSelector())`, because psycopg async cannot use the Proactor loop (`run.py:1,16-17`).

**Dockerfile**
- `CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}`, with `EXPOSE 10000` (`Dockerfile:8,10`).
- Comment: "Render sets PORT; migrations run as the pre-deploy command (python -m app.migrate)" (`Dockerfile:9`).
- The build context is the repo root, "see render.yaml" (`Dockerfile:1`).

**main.py**
- `FastAPI(title="LLM Wiki API", version="0.1.0", lifespan=lifespan)` (`app/main.py:24`). Logging is `basicConfig(level=INFO)` (`:12`).
- Lifespan (`app/main.py:15-21`), in order:
  1. `get_settings()` fails fast if a required env var is missing.
  2. `db.open_pool()`.
  3. `jobs.recover()`: creates the job semaphore and marks leftover queued/running jobs as failed.
  4. `yield`.
  5. `db.close_pool()`.
- There is no job worker loop to start. Jobs are asyncio tasks created when a job is submitted (§10).
- Routers:
  - `wikis`, `sources`, `pages` and `ops` are mounted with `dependencies=[Depends(require_api_key)]` (`app/main.py:25-27`).
  - `view.router` is mounted without auth. Comment: "public, read-only" (`:28`).
- `GET /` redirects to `/view` and is hidden from the schema (`:31-33`).
- `GET /health` runs `select 1` on the pool and returns `{"status":"ok"}`, with no auth (`:36-40`).
- FastAPI's default `/docs`, `/redoc` and `/openapi.json` are not disabled, so they are public [inferred: FastAPI defaults, no override in main.py].

**auth.py**
- `APIKeyHeader(name="X-API-Key", auto_error=False)` (`app/auth.py:8`).
- `require_api_key` raises `401 "Invalid or missing API key"` when the key is missing or when `secrets.compare_digest(key, settings.api_key)` fails. The comparison is constant-time (`app/auth.py:11-13`).
- There is a single shared key: no users, roles, or per-wiki keys.

**db.py**
- `AsyncConnectionPool(database_url, min_size=1, max_size=db_pool_max, configure=_configure, open=False)` (`app/db.py:17`).
- Each connection gets `register_vector_async` (pgvector) and `row_factory = dict_row` (`app/db.py:10-12`).

**Views (public)**: see §12 (`app/routers/view.py`).

### 6.2 Source extraction (what a wiki is built from)

**Dispatch** (`extract.py:144-152`)
- `from_upload` dispatches on the file extension: `.pdf`, `.docx`, and `.txt/.md/.markdown` (`TEXT_EXT`).
- Anything else raises ValueError "Unsupported file type. Supported: .pdf, .docx, .txt, .md, .markdown", which becomes HTTP 415.
- Return type: `Extracted(title, kind, text, sections, meta)` (`:17-23`).
- `sections = _pack(blocks, section_words=3000)`: greedy packing of blocks joined by `\n\n`. A block is split by sentence only if it alone is over the limit (`:26-39`).

**PDF** (`from_pdf`, `extract.py:72-96`, pymupdf)
- `meta = {"pages": page_count, **non-empty PDF metadata}`, then `pdf_ifrs.parse_document(doc)`. There are three layouts:
  - **"standard" (Part A)**:
    - Keeps only chunks with `source_type in ("standard","appendix_a","appendix_b")`. It drops intro, note, appendix_c and back_matter.
    - Each block is `[<para_ref or 'p'+page>] <content>`.
    - `meta.parser="ifrs"`, `meta.headings` (one per block), `meta.outline` (numbered headings matching `^[A-Z]?\d+(\.\d+)*\s`, deduplicated, in order).
  - **"accompanying" (Parts B and C)**:
    - Keeps chunks whose type is in KIND_LABELS. Each block is `[<para_ref>] (<Kind label>) <content>`.
    - `meta.parser="ifrs_accompanying"`, plus `headings`, `kinds` and `outline`.
  - **Otherwise**:
    - Blocks are `[page i]\n<page text>` for non-empty pages. `meta.parser="pdf"`.
    - `meta.warnings` is `[UNRECOGNISED_IFRS]` if `looks_like_ifrs`, else `[NOT_IFRS]`.
- The text stored in `wiki.sources.text` is these labelled blocks joined by `\n\n`. Title comes from the filename (extension removed, `_` turned into spaces).
- `KIND_LABELS` (`:61-66`): `example → "Illustrative example"`, `implementation_guidance → "Implementation guidance"`, `basis_for_conclusions → "Basis for Conclusions"`, `dissenting_opinion → "Dissenting opinion"`.
- Warning strings (`:67-69`):
  - "This PDF looks like an IFRS publication, but its paragraph numbering was not recognised: the text was kept page by page, without paragraph numbers."
  - "This PDF does not have the IFRS layout: the text was kept page by page, without paragraph numbers."
- Warnings are returned in the upload response (`routers/sources.py:42-43`).

**IFRS parser** (`pdf_ifrs.py`)
- Docstring layout assumptions:
  - Paragraph numbers sit in the left margin in the "Swift" font.
  - Editorial text uses HelveticaLTPro-BoldCond.
  - Headings use HelveticaLTPro Bold/Oblique at 9.5pt or more.
  - Running header and footer use HelveticaLTPro-Roman 9pt.
- Regexes and constants, verbatim (`:18-31`):
```python
PARA_RE = re.compile(r"^(?:B[A-Z]\.|B|C|BCZ?|IE|IG)?\d+(?:\.\d+)*[A-Z]{0,2}$")
ACCOMPANYING_RE = re.compile(r"^(IE|IG|BC[A-Z]{0,3}|DO)(?:\d+|\.\d+)(?:\.\d+)*[A-Z]{0,2}$")
ACCOMPANYING_KINDS = {"IE": "example", "IG": "implementation_guidance", "DO": "dissenting_opinion"}  # BC... -> basis_for_conclusions
IG_HEADING_RE = re.compile(r"^([A-G])\.(\d+)\s+\S")
IG_TITLE_RE = re.compile(r"^Guidance on implementing\b", re.I)
IG_INTRO = "IG introduction"
PLACEHOLDER = "not included in this edition"
RANGE_DASH = ("–", "-")
EDITORIAL_BRACKETS = re.compile(r"\[(?:Refer|Note|Link|now)\b[^\]]*\]", re.I)
MARGIN_MAX_X = 150
HEADER_Y, FOOTER_Y = 110, 720
```
- `_is_editorial` (`:44-46`): the font contains "BoldCond", or it is `HelveticaLTPro-Bold` with size < 9 and x < 175.
- `_is_heading` (`:49-50`): the font starts with HelveticaLTPro, is not editorial, has no "Roman", and size ≥ 9.4.
- `looks_like_ifrs` (`:53-61`): at least 10 margin spans (x < 150, Swift font, matching PARA_RE) in the first 40 pages.
- `_lines` (`:64-80`): groups spans into rows when y differs by ≤ 3pt, sorted left to right.
- Section switching, in Part A mode only (`_section_for_heading`, `:83-95`):
  - A heading starting "international financial reporting standard" switches to `standard`.
  - "appendix a", "appendix b" and "appendix c" switch to `appendix_a`, `appendix_b` and `appendix_c`.
  - "approval by the board", "basis for conclusions…" and "dissenting…" switch to `back_matter`.
  - The start section is `intro`.
- `parse` (`:134-235`), skip rules:
  - Header and footer: a "Roman" font with size ≥ 8.9 and y < 110 or y > 720.
  - Spans under 6pt (footnote markers).
- `parse`, headings:
  - Consecutive heading lines (same page, font and size, under 14pt apart) are joined.
  - In accompanying mode:
    - An `IG_HEADING_RE` heading starts a paragraph labelled `IG A.1` and so on, of type implementation_guidance.
    - The "Guidance on implementing" title starts `IG introduction`.
    - Placeholder paragraphs ("not included in this edition") are closed at the next heading.
- `parse`, margin labels:
  - Part A: a label is x < 150, Swift font, and matches PARA_RE (or a Bold term in appendix_a), in sections standard, appendix_a, appendix_b or appendix_c. Multi-line Appendix A defined terms are joined when under 13pt apart.
  - Accompanying: a label matches ACCOMPANYING_RE. A range label ending in a dash (e.g. `BC2.17A–`) is joined with the next line's label when under 14pt apart.
- `parse`, output:
  - Appendix A refs are prefixed `Appendix A: `.
  - Body text has editorial brackets stripped and is cleaned, then split with `split_long(max_words=500)` into parts numbered by `part`.
  - Editorial notes longer than 5 words become `note` chunks; extraction then drops them.
- `accompanying_kind` (`:111-114`): the prefix maps through ACCOMPANYING_KINDS; `BC*` gives basis_for_conclusions; anything else gives `intro`.
- `parse_document` (`:117-131`):
  1. If `looks_like_ifrs`, run a Part A parse; any `standard` chunk means layout `"standard"`.
  2. Else run an accompanying parse; any accompanying-type chunk means `"accompanying"`.
  3. Else `""`.

**`models.py`**
- `Chunk(para_ref, source_type, page, heading, content, part=0)` with `embed_text()`.
- Type groups:
  - `BINDING_TYPES = ("standard","appendix_a","appendix_b","general")`
  - `STANDARD_TYPES = ("standard","appendix_a","appendix_b")`
  - `ACCOMPANYING_TYPES = ("example","implementation_guidance","basis_for_conclusions","dissenting_opinion")`
  - `NON_BINDING_TYPES = ("note","intro","appendix_c","back_matter")`
  - `ALL_TYPES`
- Only `ACCOMPANYING_TYPES` and `Chunk` are used in Wiki/app. `BINDING_TYPES`, `STANDARD_TYPES`, `NON_BINDING_TYPES`, `ALL_TYPES` and `embed_text` are unused code shared with Rag.

**`text.py`**
- `clean`: collapses whitespace and removes the space before `,.;:)`.
- `split_long(text, max_words)`: splits on `(?<=[.;:])\s+` and packs sentences up to max_words.
- `chunk_plain(..., 400, overlap 50)`: unused in Wiki/app.

**DOCX** (`extract.py:99-114`, python-docx)
- Non-empty paragraphs become blocks; paragraphs whose style name starts with "heading" become `## <text>`.
- Every table is appended after all paragraphs, as rows `cell | cell` (cells cleaned). Original table position is lost.
- Title is the core-properties title or the filename. meta is `{}`.

**Text and Markdown** (`extract.py:117-123`)
- Decoded as UTF-8 with `errors="replace"`; CRLF becomes LF.
- kind is `markdown` for `.md/.markdown`, else `text`. For markdown the title is the first `# ` heading.
- Blocks are split on blank lines. meta is `{}`.
- Pasted text (`/sources/text`) is treated as `<title>.md` with the given title.

**URL** (`extract.py:126-141`)
- httpx with `follow_redirects=True`, `timeout=30`, User-Agent `Mozilla/5.0 (compatible; llm-wiki/0.1; +https://github.com/)`.
- A PDF content type, or a URL ending in `.pdf`, goes through `from_pdf` with kind set to `url`.
- Otherwise `trafilatura.extract(output_format="markdown", include_tables=True, include_links=False)`. Empty text raises ValueError, which becomes 422.
- Title is the trafilatura metadata title or the URL. meta is `{"url","content_type"}`.

**Source rows** (`ops/ingest.py:28-53`; in ops but needed here)
- `sha256` of the extracted text. A duplicate in the same wiki gives 409 `{"message":"Source already ingested","source":slug}` (`routers/sources.py:34-35`).
- Slug is `"source-" + slugify(title)[:60]`, with `-2`, `-3` and so on added if it collides with a source or page slug.
- Stores kind, uri (filename, URL, or None for pasted text), text and meta.

**Storage of originals** (`app/storage.py`)
- Only for file uploads; URL and pasted-text sources are not stored (`routers/sources.py:36-37,76,82`).
- Bucket: `STORAGE_BUCKET` (default `sources`). Created private (`public: False`) if it is missing (`:64-74`).
- Object key: `wiki/<wiki_id>/<source_slug>/<filename>`, with the filename sanitised by `[^\w.\- ()]` → `_` (`storage.object_path`, `:43-47`).
- Upload: POST `/storage/v1/object/<bucket>/<path>` with `x-upsert: true`. A failure is logged and returns None; it never fails an ingest (`:77-90`).
- Auth headers: `apikey`, plus `Authorization: Bearer` when the key is a legacy JWT starting `eyJ` (`:50-53`). httpx timeout is 120s.
- The record `meta.file = {bucket, path, content_type, size}` is merged into `sources.meta` (`routers/sources.py:61-67`).
- Content types (`:16-22`): pdf, docx, md/markdown, txt; otherwise `application/octet-stream`.
- Signed URL `expiresIn` is 3600s (`:93-98`).
- Delete: DELETE `/object/<bucket>` with prefixes `[path]` (`:101-108`).
- Base URL: `SUPABASE_URL` if set, else `https://<ref>.supabase.co` taken from `://postgres.<ref>[:@]` in DATABASE_URL (`:25-31`).

**`app/attach_file.py`**
- CLI: `python -m app.attach_file <wiki-slug> <source-slug> <path>`.
- For sources ingested before storage existed. It re-extracts the file (with `section_words`), requires the same SHA-256 of the text, then uploads and attaches it. It exits if storage is not enabled (`:21-43`).

### 6.3 Shared plumbing used by every operation

**Models and settings** (`config.py:8-37`). These are defaults and can be changed through env vars or `.env` (`config.py:9`, pydantic-settings):

| Setting | Default |
|---|---|
| `gemini_chat_model` | `"gemini-2.5-flash"` |
| `gemini_embed_model` | `"gemini-embedding-001"` |
| `embed_dim` | `768` ("must match vector(768) in migrations") |
| `embed_batch` | `100` |
| `temperature` | `0.1` |
| `section_words` | `3000` (source split size for note extraction) |
| `chunk_max_words` | `500` (page chunk size for search) |
| `max_pages_per_ingest` | `17` ("including the source page") |
| `page_source_words` | `12000` |
| `page_part_words` | `4000` |
| `page_background_words` | `2000` |
| `route_batch` | `120` |
| `llm_concurrency` | `4` |
| `job_workers` | `2` |
| `query_top_k` | `8` |
| `query_max_pages` | `8` |
| `lint_batch_pages` | `12` |
| `max_upload_mb` | `50` |

The API keys (`api_key`, `gemini_api_key`) have no defaults. Their values are not reproduced here.

**LLM calls** (`llm.py`):
- **One chat model for every call.** `generate` and `stream` always use `get_settings().gemini_chat_model` (`llm.py:89,109`). `temperature` is always `get_settings().temperature` (0.1) through `_cfg` (`llm.py:82-83`). No call overrides the model or temperature. No `max_output_tokens`, thinking budget or top-p is set anywhere.
- **JSON mode.** `generate(..., schema)` sets `response_mime_type="application/json"` and `response_json_schema=schema` (`llm.py:87`). If the response has no text it raises `EmptyResponse`. With a schema, any `finish_reason` other than `STOP` (for example RECITATION or MAX_TOKENS) also raises `EmptyResponse` (`llm.py:93-99`).
- **API retries.** `_retry` makes 5 attempts on HTTP codes `RETRYABLE = {429, 500, 502, 503, 504}`. The delay is `2 ** i * 2`, giving 2, 4, 8 and 16 seconds (`llm.py:15,23-32`).
- **JSON retries.** `generate_json` makes 3 attempts on `EmptyResponse` or `JSONDecodeError` (`llm.py:116-124`).
- **Concurrency.** `gather_limited` caps parallel calls with a semaphore of `llm_concurrency` (4) (`llm.py:127-135`).
- **Embeddings.** Requests go in batches of 100, with `task_type` `RETRIEVAL_DOCUMENT` by default or `RETRIEVAL_QUERY` for queries, `output_dimensionality=768`. Vectors are L2-normalised (`llm.py:59-79`).
- **Usage tracking.** `track_usage()` and a contextvar record step, model, input, output and thinking tokens per call (`llm.py:35-56`). Only `query.answer` turns it on (`ops/query.py:151`).

**Jobs** (`jobs.py:1-72`):
- Jobs run in-process, one instance only. Jobs left over from a previous process are marked failed on restart.
- Jobs on the same wiki run one at a time through `_wiki_locks`. At most `job_workers` (2) run at once overall.
- `ctx.progress(**kw)` merges a JSONB object into `wiki.jobs.progress`. The job's return value is stored in `wiki.jobs.result`.

**Hybrid search** (`Wiki/migrations/0001_init.sql`, function `wiki.search_pages`):
- Reciprocal rank fusion with `rrf_k` default `50` over page chunks.
- Full text uses `plainto_tsquery('english')`, with `&` replaced by `|` (an OR query) and `ts_rank_cd`, limited to `match_count * 4`.
- The vector side uses cosine `<=>`, also limited to `match_count * 4`.
- Each page keeps its best chunk. The snippet is the first 400 characters (`left(content,400)`). The function returns at most `match_count` pages.
- `search_many` runs several queries and keeps each page's best score (`wiki/search.py:20-31`).

**Search chunks** (`wiki/store.py:_chunks:98-106`): a page is split at `#`, `##` or `###` headings, then into pieces of up to 500 words (`split_long`, broken at sentence boundaries). Each chunk is prefixed with the page title.

**Compact index for prompts** (`wiki/store.py:compact_index:312-323`):
- One `slug | type | title | summary` line per page, ordered by type and then slug (`list_pages`, `store.py:72`).
- Capped at `limit_chars=60000`. Past the cap it adds `"... (N more pages not shown)"`.
- An empty wiki gives `"(wiki is empty)"`.

---

### 6.4 Building the wiki on ingest

#### 1.0 Hand-off from extraction
1. Uploads arrive through `POST /wikis/{w}/sources` (file), `/sources/url` or `/sources/text` (`routers/sources.py:46-82`).
   - Extraction runs with `section_words`, so `ex.sections` are packs of about 3000 words.
   - Blocks are never split unless one alone is too long (`sources/extract.py:_pack:26-39`).
   - Uploads over 50 MB get HTTP 413 (`routers/sources.py:51-52`). Empty text gets 422 (`routers/sources.py:30-31`).
2. **IFRS Standard PDFs** (`extract.py:76-82`):
   - Only `source_type in ("standard","appendix_a","appendix_b")` is kept.
   - Each block is `"[{para_ref or 'p'+page}] {content}"`.
   - `meta.parser="ifrs"`, plus `meta.headings` (one per block) and `meta.outline` (numbered headings).
3. **Accompanying documents** (Parts B and C) (`extract.py:83-90`):
   - Each block is `"[{para_ref}] ({KIND_LABEL}) {content}"`.
   - `meta.parser="ifrs_accompanying"`, plus `meta.kinds`.
4. **Other PDFs** become `"[page i]\n..."` blocks with a warning (`extract.py:91-94`). DOCX, text and URL sources have no headings, kinds or outline.
5. **`save_source`** (`ingest.py:28-53`):
   - It takes a SHA-256 of `ex.text`. If the same hash already exists in the wiki it raises `DuplicateSource`, which the router turns into 409 (`routers/sources.py:34-35`).
   - The slug is `"source-" + slugify(title)[:60]`, made unique against both sources and pages with `-2`, `-3` and so on.
   - It inserts a row into `wiki.sources` with `text` and `meta`.
6. The original file is stored, if storage is configured. The job is then submitted with `ingest.run_safe` (`routers/sources.py:36-41`).
   - `mode` comes from the query string, default `"auto"`, and must be `auto` or `review` (`routers/sources.py:16`, `routers/deps.py:7`).
7. **`run_safe`** (`ingest.py:668-683`): if anything fails, it deletes the source row when no `page_sources` row uses it, removes the stored file, and re-raises. The upload can then be retried.

#### 1.1 Step 1: notes per section (`ingest.py:284-321`)
- Progress is reported as `stage="notes"` with the section count.
- **Call per section.** `llm.generate_json(MAINTAINER_SYSTEM, with_schema(schema, notes_prompt(ex.title, i, len(ex.sections), sec)), NOTES_SCHEMA)`.
- **Failure handling** (`extract_notes`, `ingest.py:291-308`). On any exception:
  - The section is split at `"\n\n"` into two halves. Both halves are retried in parallel, recursing to `depth` 2, so a section can end up in at most 4 pieces.
  - The code comments: "e.g. RECITATION blocks: smaller inputs usually pass".
  - If both halves succeed, the results are merged: summaries are concatenated with a space and the lists are joined (`merge`, `ingest.py:288-289`). Otherwise the half that worked is kept, with its error.
- **Failed sections** are recorded as `{"section","error","partial"}`. One bad section does not stop the ingest (`ingest.py:310-314`).
  - If every section fails, it raises `RuntimeError("Note extraction failed for every section: ...")` (`ingest.py:317-318`).
  - Failures are reported in progress as `failed_sections`.
- **`_notes_md`** (`ingest.py:56-68`) turns the notes into one text with these parts:
  - `### Section i`
  - the summary
  - `Claims:` bullets
  - `Open questions (posed by the source, NOT facts):`
  - `Entities:` and `Concepts:` as `- name: description`

#### 1.2 Step 2: route each paragraph to one schema section (`ingest.py:323-380`)
- **Paragraphs.** `paras` is `ex.text` split on blank lines. All of them are embedded with `RETRIEVAL_DOCUMENT` (`ingest.py:324-325`).
- **Schema sections** (`_sections`, `ingest.py:83-90`):
  - Section headings match `^###\s*(\d+)\.\s*(.+)$` in `wiki.schema_md`.
  - A brief runs from its heading to the next line matching `^##`. That also matches `###` and `####`, so a brief ends at the next heading of any level from 2 down, including a sub-heading inside it. This is an observation from the regex; check whether the schema relies on sub-headings inside briefs.
- **Routing runs only if** the schema has sections and the source has paragraphs. Progress is `stage="route"`.
- **Headings.** `heads` comes from `meta.headings` if its length equals the paragraph count; otherwise every heading is blank (`ingest.py:331-332`).
- **Examples section, placed by code** (`ingest.py:334-341`):
  - This is the first section whose name contains "example".
  - A paragraph goes there if `meta.kinds[i]=="example"`, or, where no kinds exist, if it matches `EXAMPLE_LABEL = re.compile(r"\b(?:Example|Instrument|Scenario|Illustration)\s+(?:\d+[A-Z]?|[A-Z])\b")` (`ingest.py:156`).
  - Paragraphs are grouped by their reference label, so every chunk that shares a label goes along.
- **The model routes the rest.**
  - `targets` are all sections except the examples section. `briefs` are their briefs joined.
  - `note` (verbatim, `ingest.py:345-347`):
    `f"Section {ex_sec['num']:02d} ({ex_sec['name']}) is not offered: the issuer's labelled examples have already been placed there, and every other paragraph, including application guidance that says \"for example\", goes to the section that owns its requirement."`
    The note is empty if there is no examples section.
  - `outline` is `meta.outline` joined by newlines.
  - Each batch line is `f"{i} | {heads[i] or '-'} | {first 60 words}"` (`ingest.py:351`).
  - The call is `llm.generate_json(system, prompts.route_prompt(briefs, lines, outline, note), ROUTE_SCHEMA)`. This is not wrapped in `with_schema`, so the wiki schema is not prepended.
  - The model's assignments are kept only where the id is in the batch and the section number is valid. A batch that fails returns `{}` (`ingest.py:352-357`).
- **Two rounds** (`ingest.py:359-365`): batches of `route_batch`=120, then batches of 40 for whatever the first round missed.
- **Fallback placement** (`ingest.py:366-380`):
  1. A majority vote of where the paragraph's group went. Groups come from `_group_key`: `5.5.3` belongs to `5.5`, `B5.5.17` to `B5.5`, all Appendix A terms form one group, and unlabelled paragraphs stand alone (`ingest.py:103-113`).
  2. Otherwise the closest section brief by embedding, using `brief[:8000]` embedded as RETRIEVAL_QUERY, dotted with the paragraph vector.
  - Every fallback placement is recorded in `unassigned` as `{"paragraph","placed_in","by"}` (`by` is "its paragraph group" or "closest section brief") and reported in progress.

#### 1.3 Step 2b: "Also record here" (ADDITIVE) sections (`ingest.py:382-399`)
- This applies to any section whose brief contains the word `ADDITIVE` (`re.search(r"\bADDITIVE\b", ...)`), and only when routing produced owners.
- **Candidates.** All paragraphs not owned by that section and not placeholders.
- **Batches.** Groups of `route_batch`=120. Each line is `f"{i} | {first 200 words}"`.
- **Call.** `generate_json(system, also_prompt(sec["brief"], lines), ALSO_SCHEMA)`, without `with_schema`. A failed batch returns `[]`.
- **Result.** `also[sec_num]` holds the sorted ids the model picked.

#### 1.4 Step 3: planning (`ingest.py:401-443`)
- Progress: `stage="plan"`.
- **Inputs:**
  - **Index.** `compact_index(wiki_id, exclude_types=("synthesis",))`. Saved answers are never planning material (`ingest.py:403-404`).
  - **Candidates.** `search.search_many(wiki_id, _names(notes), k=3)`:
    - `_names` gives the top 40 entity and concept names by how often they appear (`ingest.py:71-76`).
    - Synthesis hits are dropped. At most 40 lines are kept, as `slug | type | title | summary`, or `"(none)"` (`ingest.py:405-406`).
- **Call.** `generate_json(system, with_schema(schema, plan_prompt(ex.title, source["slug"], notes_md, index, candidates, s.max_pages_per_ingest - 1)), PLAN_SCHEMA)`. The model is told "At most 16 pages" (17 - 1).
- **Update or create is decided by code, not the model.** The plan's `action` is overwritten: `"update" if slug in existing else "create"` (`ingest.py:421`). Slugs are `slugify`'d.
- **The plan is then cleaned** (`ingest.py:414-421`):
  - The source slug and repeated slugs are skipped.
  - Any page of type `overview` whose slug is not `overview` is skipped.
  - Any planned or existing `synthesis` page is skipped ("an upload never writes or rewrites one").
- **The overview is forced in** if missing. It gets title = `wiki["name"]` and focus `f"Integrate the new source {ex.title} into the overview"` (`ingest.py:422-424`).
- **Section mapping** (`ingest.py:425-429`):
  - Only `type=="topic"` items are matched.
  - `_section_for` finds the longest section name, normalised, that appears in the title or slug (`ingest.py:93-100`).
  - One page per section: the first match wins.
- **Every section gets a page** (`ingest.py:430-440`):
  - A missing section gets slug `prefix + slugify(sec name)`. The prefix is taken from an already-mapped page whose slug ends with its section's slugified name, for example `ifrs-9-`.
  - It is added as `type "topic"` with focus `f"Section {num:02d}: {name}"`.
- **Page cap** (`ingest.py:441-443`). Items are sorted by rank (section pages 0, overview 1, others 2; the sort is stable) and cut to `max_pages_per_ingest - 1` = **16** items. The source page is the 17th.
  - **Consequence (inference):** if the schema has 16 or more sections, the overview and every non-section page are dropped.

#### 1.5 Step 4: writing pages (`ingest.py:445-640`)
- Progress: `stage="write"`, `pages=len(items)+1`.
- **Linkable pages.** `linkable` is the index, plus `f"{source slug} | source | {ex.title}"`, plus each planned item as `"slug | type | title (being written now)"` (`ingest.py:447-448`).
- **Material.** `material` is `f"Source: {ex.title}\n\n{notes_md}"` (`ingest.py:449`).
- **`own[section]`** is the list of paragraph indices each section owns (`ingest.py:454-456`).
- **`relevant(query, budget, exclude)`** (`ingest.py:458-463`):
  - It embeds `query[:8000]` as a query and scores the paragraphs not excluded.
  - `_select` (`ingest.py:116-134`) ranks paragraph groups by mean similarity and takes whole groups while they fit the word budget.
  - At the first group that does not fit, it adds that group's paragraphs in similarity order where each fits, then **stops**: no later groups are considered.
  - The result comes back in document order.

**`write(slug, title, ptype, focus, source_slug)`** (`ingest.py:465-617`):
- **Existing "Also recorded here" lines.** On an existing section page, `_split_also` pulls them out of the old content, so the writer sees only the rest, `cur_body` (`ingest.py:469`, `_split_also:233-243`).
- **Section page** (`sec` set) (`ingest.py:472-485`):
  - `given` is the section's own paragraphs. `extra` is its also-record ids.
  - **Nothing from this source.** If the page exists, it returns `None` and the page is left untouched. If not, it creates a page with:
    - summary `"Empty: no source content yet"`
    - content `f"This section is empty: no paragraph of [[{source_slug}]] belongs to it."`
    - change_note `f"Created empty: {ex.title} has nothing for this section"`
  - **Otherwise:**
    - `auto_gaps=True`.
    - `page_material` is only `f"Source: {ex.title}"`, because "the notes cover every section and would leak other sections' points in".
    - `background` is up to 2000 words of other paragraphs most relevant to the section brief (`page_background_words`), with their own paragraphs and also-record paragraphs excluded and their `[label]` removed. Background is gathered only if `given` is non-empty.
- **Overview, source and other composed pages, when routing ran** (`ingest.py:486-488`). `given=[]`. Background is up to 2000 words relevant to `title\nfocus`, with labels removed. These pages get the full `material`, meaning all the notes.
- **Schema without fixed sections** (`ingest.py:489-490`). `given` is the most relevant paragraphs: up to `page_part_words` (4000) words for `overview` or `source` pages, otherwise `page_source_words` (12000).
- **Parts** (`ingest.py:491-512`):
  - `_parts(given, 4000)` makes document-order groups of about 4000 words. A tail under 1000 words (`max_words // 4`) is folded into the previous part (`ingest.py:137-152`).
  - Pages with no `given` paragraphs are written once, unless there are only `extra` lines, in which case they get zero writing calls.
  - Each part is a call to `generate_json(system, with_schema(schema, write_page_prompt(...)), PAGE_SCHEMA)`, with `part=(n,total)` when there is more than one part. `earlier_parts` is the content of the parts already written.
  - A failed part is logged and added to `failed_pages` as `"slug (part n of N)"`. A failed single-call page raises.
  - If every part fails, it raises `RuntimeError("every part of {slug} failed")`.
- **Joining.** Parts are joined by `_join_parts`, which drops any block whose normalised text repeats an earlier block (`ingest.py:262-271`).
  - On section pages, any "Also recorded here" section the model wrote is stripped.
  - If there are only extra lines and no given paragraphs on an existing page, the content stays `cur_body` (`ingest.py:516-519`).
- **Extra passes for missed paragraphs** (`auto_gaps` pages, `ingest.py:532-559`). There are two attempts.
  - `_uncited(content, given)` finds the labelled paragraphs that no `[[x|label]]` citation on the page covers (`ingest.py:206-219`). It skips paragraphs with no label, page labels (`p\d+` or `page \d+`), and placeholders.
    - Coverage is decided by `_covers` (`ingest.py:175-187`): an exact clause match bounded so it is not part of a longer number; ranges `A–B` within the same prefix and parent with the last number inside the range; and an `Appendix A:` term as a substring of the label.
  - The missing paragraphs are cut into 4000-word groups. Each group is a call to `write_page_prompt(..., existing_md=None, fill=True, earlier_parts=<the page's ##–#### headings>)` with `FILL_SCHEMA`.
  - From each reply, `cited_only` keeps only blocks or bullet lines that cite one of the requested references, plus bare headings, with trailing bare headings dropped (`ingest.py:521-530`). The kept text is appended with `_join_parts`.
  - Each pass is recorded in `fill_passes` as `{page, attempt, asked, returned, kept_words, still_missing}` or `error`.
  - Paragraphs still uncited after both attempts go to `missed` as `{"page","paragraphs","reason":"not written up after two extra passes"}`.
- **Also-recorded lines** (`ingest.py:561-600`):
  - Each also-record paragraph is given with `(main page: [[<owner's section page or 'overview'>]])` inserted after its label.
  - There are two attempts. Each takes the paragraphs not yet cited in the accumulated lines, cut into 4000-word groups, and calls `with_schema(schema, also_record_prompt(...))` with `FILL_SCHEMA`.
  - Bullets run together are split (`]]- ` becomes a newline and `- `). `cited_only` filters the reply. Heading lines are dropped.
  - Every `[[source-...|` is rewritten to the current source slug.
  - Then, for lines that fold the main page and the paragraph number into one link with no `[[source-…|` citation (`[[main-page|4.3.7]]`), the link is rewritten to `see [[main-page]] [[source|4.3.7]]` (`ingest.py:596-598`).
  - Still missing: `missed` gets `{"page","paragraphs","reason":"not recorded after two tries"}`.
- **Rebuilding the "Also recorded here" section** (`ingest.py:602-605`):
  - Old lines come first, but an old line is dropped when a new line has the same `_also_key`. The key is the sorted set of `source-…|label` citations, so a later upload replaces the entry for the same paragraph (`ingest.py:256-259`).
  - `_with_also` places `## Also recorded here` (`ALSO_HEADING`, `ingest.py:230`) before any closing "Not yet covered" note (`ingest.py:246-253`).
- **"Not yet covered" note** (`ingest.py:606-609`):
  - On `auto_gaps` pages with given paragraphs, it appends `"\n\nNot yet covered: (paragraphs of this section that it does not cite) <refs>"`, or `"\n\nNot yet covered: none"`.
  - Otherwise, when the page was written in more than one part, it appends the same note with the default wording `"source paragraphs given for this page"` (`_not_covered`, `ingest.py:222-227`).
- **The returned `Op`** (`ingest.py:610-617`):
  - Title, summary and change_note come from the first part's output. A fallback is used for pages with only extra lines: summary `f"{title}: items also recorded here"`, change_note `f"Also recorded from {ex.title}"`.
  - Tags are the union of all parts' tags, else the existing tags.
  - `base_version` is the current version, used for conflict detection.
  - `op` is `update` if the page exists, else `create`.
- **Source page** (`ingest.py:619-634`):
  - Written as `write_safe(source slug, ex.title, "source", source_focus, None)`. Because `source_slug=None`, no citation instruction is added to its prompt.
  - `source_focus` (verbatim):
    `"Source page: what the source is, its scope, key takeaways, and which wiki pages it informs " f"(link them). One-line summary: {plan['source_summary']}"`
- **Running the writes.** All writes run through `write_safe`, so one failing page goes into `failed_pages` instead of stopping the ingest, under `gather_limited` (4 at a time).
  - If no ops come back at all, it raises `RuntimeError("Page writing failed for every page: ...")`.
  - Progress reports `failed_pages` and `missed_paragraphs` (`ingest.py:632-641`).

#### 1.6 Placeholders (`ingest.py:190-203`)
- `_placeholder` treats as a placeholder any paragraph whose body (after the label and an optional `(kind)`) contains "included in this edition" and has no word of 3 or more letters once these are stripped:
  - the stub regex `_STUB`: `\[?(?:This paragraph refers|These paragraphs refer)[^\]]*?not included in this edition\.?\]?` (case-insensitive)
  - stub tails and starts
  - reference labels
- Placeholders are never "uncited" and are never also-record candidates. They are still routed and still given to page writers as `source_paragraphs`.

#### 1.7 After writing (`ingest.py:642-649`)
- **Links to pages that will not exist** become plain text through `_unlink`: the label if there is one, else the link text. Valid targets are existing slugs, the slugs of the ops, and the source slug (`ingest.py:274-276`).
- **Citation check.** `citecheck.check_ops(wiki_id, ops)` (`wiki/citecheck.py:87-106`):
  - Each `[[source-slug|label]]` (`CITE_RE`) is checked against the paragraph labels of the source it names.
  - If the clause is not in that source but is in exactly one other source, the citation is **corrected in place** to name that source.
  - If it is in no source, or in several, it is **flagged** and left alone.
  - A bare number that would move to another source is flagged, never moved.
  - Labels with no digit (citing the whole source) are skipped.
  - `STANDARD_NAME` (`\b(?:IFRS|IAS|IFRIC|SIC)\s*\d+\b`) is removed from labels before matching.
  - The report `{corrected:[{page,count,moves,labels[:50]}], flagged:[{page,source,label,reason,count}]}` goes to progress as `citations`.

#### 1.8 Step 5: commit, modes, versions and logs (`ingest.py:651-665`, `wiki/store.py`)
- Progress: `stage="commit"`. The call is `store.commit(wiki_id, "ingest", f"Ingest: {ex.title}", ops, mode, job_id, source_id)` (`store.py:283-292`).
- **What `commit` does:**
  - It always creates a `wiki.changesets` row and `wiki.changeset_ops` rows.
  - With `mode=="auto"` it applies the changeset at once and returns `status "applied"`.
  - With `review` it returns `{"changeset_id","status":"pending","ops":[...]}`.
  - With no ops it returns `status "empty"`.
- **`apply_changeset`** (`store.py:154-230`). This also runs later from `POST /changesets/{id}/apply?force=` (`routers/ops.py:183-189`).
  - **Embeddings first.** All pages' chunks are embedded before the transaction opens.
  - **Conflicts.** Each page row is locked `for update`. Unless `force` is set:
    - A `create` for a page that now exists is skipped as a conflict.
    - An `update` whose `base_version` no longer equals the page's current version is skipped as a conflict.
  - **Writes.** The page is updated (`version=version+1`) or inserted.
  - **Version history.** Every applied op gets a `wiki.page_versions` snapshot with `change_note` and `job_id`.
  - **Reindexing** (`_reindex_page`). `wiki.links` is rebuilt from `[[...]]`. `[[source-*]]` links are also added as `page_sources`. Page chunks and embeddings are replaced.
  - **Source link.** If the changeset has a `source_id`, a `page_sources` link is inserted.
  - **Saved answers.** For non-synthesis pages, `saved.changed_clauses(old,new)` finds the cited paragraphs whose statements changed. `saved.flag_changed` then flags any saved answer citing them with `needs_checking` (`wiki/saved.py:61-91`). These are returned as `saved_answers_to_check`, which ingest reports in progress (`ingest.py:655-656`).
  - **Log.** An `"apply"` entry lists the applied ops and any skipped conflicts.
- **Discarding** (`store.py:257-280`). Discarding a pending ingest changeset also deletes the source when no page uses it, plus its stored file. The router logs `"edit"` (`routers/ops.py:192-200`).
- **Ingest log entry** (`ingest.py:657-660`):
  - kind `"ingest"`, title `ex.title`.
  - detail: `"Source [[slug]] (kind, N sections). <source_summary>\n- <op> [[slug]]: <change_note>..."` followed by `"\n\nMode: {mode} ({status})"`.
- **Job result** (`ingest.py:661-665`):
  - `source`, `mode`
  - `failed_sections`, `failed_pages`
  - `routing` (`"NN name"` mapped to paragraph labels)
  - `unassigned`, `also_recorded`, `missed_paragraphs`
  - `citations`, `fill_passes`
  - `pages` (op and slug)
  - plus the commit result
- **"Index updates."** No index page is stored. `render_index` builds a markdown index from the pages on demand, grouped by `PAGE_TYPES` (`store.py:297-309`). The index is kept current only through each page's `summary` field and the chunk reindex.
- **Contradictions are not detected by code.** They are flagged only by a prompt instruction: "flag contradictions with the schema's contradiction callout rather than silently replacing claims" (`prompts.py:190,196`). What that callout looks like is defined in the wiki's `schema_md`, which lives in the database and was not read [UNVERIFIED].

---

### 6.5 Retrieval and answering on the wiki side

**Route** (`routers/ops.py:19-27`). `QueryIn` takes:
- `question` (at least 3 characters)
- `save=False`
- `mode="auto"`
- `sources` (`"standard"` or `"all"`, default `"all"`)
- `use_saved=True`

#### `_select_pages` (`query.py:16-34`)
1. `synth` is the set of all synthesis slugs.
2. `hits = search_pages(question, query_top_k=8)`. If any synthesis page is in the top 5, it searches again with `8 + len(synth)`. Synthesis hits are then removed.
3. `index` is the compact index without synthesis pages. The call is `generate_json(MAINTAINER_SYSTEM, select_prompt(question, index, query_max_pages=8), SELECT_SCHEMA)`, without `with_schema`.
4. `order` is the top **5** search hits, then the model's picks (`slugify`'d), with duplicates and synthesis pages removed. Hits 6 to 8 are fetched but never used.
5. Pages fetched are `order[: query_max_pages + 5]`, so **at most 13 pages** are read, in that order.
- **No word budget on what is read.** Each page's full `content_md` is sent. The only limit is the 60,000-character cap on the index in the select prompt.

#### `_select_saved` (`query.py:37-46`)
- Rows come from `saved.saved_answers(readable_only=True)`. These are synthesis pages tagged `saved-answer`, or whose first version's change_note starts with "Filed from query". Pages carrying a `citation_problems` flag are excluded (`saved.py:12-31`).
- The listing is `slug | title | summary`. The call is `generate_json(MAINTAINER_SYSTEM, select_saved_prompt(...), SELECT_SCHEMA)`.
- At most **2** are kept, each marked `saved: True`.
- Saved answers are read only if `use_saved` is set and at least one page was found (`query.py:114`).

#### Sources setting "standard" (`query.py:49-96`)
The regexes, verbatim:
```python
_SOURCE_CITE = re.compile(r"\[\[(source-[^\]|#]+)")
_STATEMENT = re.compile(r"(?:\[\[source-[^\]]+\]\][\s,;]*)+[.;:]?")  # a statement ends with its citation group
_HEADING = re.compile(r"^\s*#{1,6} ")
```
- **`_standard_slugs`** is the set of sources with `meta->>'parser' = 'ifrs'` (Part A only).
- **`standard_only(md, standard)`:**
  - Blank lines and headings are kept.
  - Other lines are cut into statements, each ending at its `[[source-…]]` citation group. A statement is kept only if it cites at least one source and **all** its cited sources are Standards.
  - Text after the last citation on a line, and lines with no source citation, are dropped.
  - Headings left with nothing under them are dropped: no following content, or only a heading at the same or a higher level.
  - Runs of 3 or more newlines are collapsed.
- **`_restrict`.** With `sources != "standard"` the pages are unchanged. Otherwise each page is filtered and kept only if a source citation survives. It applies to both pages and saved answers.

#### Prompt assembly and the answer
- **`_pages_md`** (`query.py:99-103`):
  - Saved answers: `<saved_answer slug="…" title="…" saved="YYYY-MM-DD">\n…\n</saved_answer>`, dated by `updated_at`.
  - Pages: `<page slug="…" title="…" type="…">\n…\n</page>`.
  - Blocks are joined by blank lines.
- **`_prompt`.** It uses `query_prompt`, or `query_saved_prompt` when there are saved answers, always wrapped in `with_schema(wiki.schema_md, …)` (`query.py:118-120`).
- **`answer()`** (`query.py:149-165`):
  - Usage tracking is turned on.
  - **No pages.** A fixed answer, with no model call:
    - `"The wiki has no Standard (Part A) material relevant to this question."` when sources is standard
    - `"The wiki has no pages relevant to this question yet."` otherwise
  - **Otherwise.** `llm.generate(QUERY_SYSTEM, prompt)`, as free text with no JSON schema.
  - **Result:**
    - `answer`
    - `pages`, from `_cited`: per page `{slug, title, cited (slug linked in the answer), saved}`
    - `read`, from `_read_record`
    - `usage`
    - `saved`, when `save` is set and pages were found
  - **Log.** Kind `"query"`, title `question[:200]`, detail `"Sources: {sources}. Pages read: [[…]]…"`, plus `". Saved answers read: …"` and `"\n\nSaved as [[slug]] (status)"` where they apply.
- **`_read_record`** (`query.py:143-146`). Per page or saved answer: `{slug,title,type,version,saved,words,sha256}`. The hash is SHA-256 of the text after the Sources filter.
- **`read_text`** (`query.py:123-140`, route `POST /wikis/{w}/read-text`):
  - It rebuilds each recorded page from `wiki.page_versions` at the recorded version and applies `standard_only` again when sources is standard.
  - It returns `{slug,version,saved,text,matches}`.
  - Reasons: `"version not found"`, or `"the rebuilt text differs from what was read"`.

#### Streaming (`query.py:168-172`, `routers/ops.py:97-111`)
- `stream_answer` selects pages and saved answers the same way and writes the log entry **before** the answer is generated. It then returns `llm.stream(QUERY_SYSTEM, prompt)`.
- SSE events through `EventSourceResponse`:
  - `event: "token"`: the data is a JSON string of each text chunk.
  - `event: "pages"`: the data is a JSON list of `{slug,title,cited,saved}`.
  - `event: "done"`: the data is `""`.
- **Streaming differs from `answer` in four ways:**
  - The `save` flag is ignored.
  - There is no `read` record and no `usage`.
  - With no pages there is no fixed message; the model is still called with empty `<wiki_pages>`. This is inferred from the code, which has no `if not pages` branch in `stream_answer`.
  - Version and hash are not reported.

#### Saving an answer (`save_answer`, `query.py:175-192`)
- The call is `generate_json(MAINTAINER_SYSTEM, with_schema(schema, save_answer_prompt(question, answer_md, index)), PAGE_SCHEMA)`. Here the index **includes** synthesis pages.
- The slug is `slugify(title)`, made unique with `-2`, `-3` and so on.
- The op is a create with `type "synthesis"`, tags `["saved-answer", …model tags]` (`SAVED_TAG`, `saved.py:12`), and change_note `f"Filed from query: {question[:150]}"`. The model's own `change_note` is ignored.
- `citecheck.check_ops` runs, then `store.commit(wiki_id,"query",f"Save answer: {title}",[op],mode)`.
- It returns `{slug,status,changeset_id,citations}`.

---

### 6.6 Synthesis pages (saved answers)

The module docstring says the draft uses only the wiki answers, never RAG answers, and only their citations. The record of questions is written by code, and nothing is written until `save()` (`synthesis.py:1-6`).

**Routes** (`routers/ops.py:29-72`):
- `POST /synthesis/draft` takes `{chat_id (at least 4 characters), chat_title, answers[{searched, answer, sources, date}]}`.
- `POST /synthesis/check`.
- `POST /synthesis` saves. The slug must match the pattern `^[a-z0-9][a-z0-9-]*-synthesis-[a-z0-9]+$`. A `ValueError` becomes HTTP 409.

**Slug rule** (`slug_for`, `synthesis.py:23-33`):
- The slug is `f"{framework}-synthesis-{chat_id lower-cased, non-alphanumerics removed, first 8 characters}"`.
- `framework` is the most common match of `FRAMEWORK_RE = r"^([a-z]+-\d+[a-z]?)-"` (so `ifrs-9-measurement` gives `ifrs-9`):
  - first among the non-source links in the answers,
  - else among the wiki's non-synthesis page slugs,
  - else `slugify(wiki_name)`.
- The same chat always gives the same slug.

**Record** (`record`, `synthesis.py:36-40`), written by code:
- It starts with `"## Questions answered"` (`RECORD_HEADING`).
- Each line is `"{i}. {searched} — answered {date[:10]}, Sources: {'Standard only' | 'All'}"`.

**Draft** (`synthesis.py:64-78`):
- `body` is made of `<answer n="i" question="…">\n…\n</answer>` blocks.
- The call is `generate_json(MAINTAINER_SYSTEM, with_schema(schema, synthesis_prompt(chat_title, body)), SYNTHESIS_SCHEMA)`.
- `content` is `record + "\n\n" + content_md`.
- It returns the page fields, `exists`, `version`, and the result of `check`.

**Check** (`synthesis.py:43-61`). It changes nothing and only reports problems:
- `"wrong source"`: something citecheck would correct.
- `"citation to check"`: something citecheck flags.
- `"not in the wiki answers"`: a `(slug,label)` link that appears in no answer.
- `"no such page"`: an allowed link to a page that does not exist.
- It also returns `corrections`. These are reported but **not applied**.

**Save** (`synthesis.py:81-97`):
- It runs `check` again.
- If an existing page with that slug is not a synthesis page, it raises `ValueError`.
- The op is a create or update with `type "synthesis"`, the `saved-answer` tag, `base_version`, and change_note `f"Synthesis of an Ask chat ({n} wiki answer(s))"`.
- It always commits with `"auto"` as kind `"query"` and summary `f"Synthesis: {title}"`, whatever mode was asked for.
- A conflict raises `ValueError("The page changed while you were editing: …")`.
- **Needs checking.** `saved.set_citation_problems` writes a `citation_problems` flag when there are problems. A page with that flag is not read by queries until it is saved again without problems, which clears the flag (`saved.py:34-45`).
- It returns `{slug,status,needs_checking,problems,corrections}`.
- The citecheck correction is **not** applied here: the content is saved as submitted (inference, since `check_ops` is never called in `save`).

---

### 6.7 Lint and coverage passes

**Route** (`routers/ops.py:75-79,114-119`). The body is `{llm=False, fix=False, mode="review"}`.
- With neither flag, the structural checks run synchronously, as a fast path.
- Otherwise lint runs as a job through `lint.run`.

**Structural checks**, all SQL (`lint.py:15-61`):
- `broken_links`: link targets with no page, grouped with the pages linking to them, most-linked first.
- `orphans`: pages other than `overview` that no other page links to.
- `missing_metadata`: `summary = ''` or no tags.
- `thin_pages`: under **40** words, split on whitespace.
- `unsourced_pages`: type not in (`overview`, `synthesis`, `source`), with no `page_sources` row and no `[[source-` in the content.
- `possible_duplicates`: titles lower-cased, a trailing `s` removed from each word (`s\b`), then non-alphanumerics removed; groups with more than one slug.
- `EXEMPT_ORPHAN = ("overview",)` is defined (`lint.py:12`) but never used. The SQL hard-codes `'overview'` instead.

**LLM check** (`llm_check`, `lint.py:68-97`):
- Pages are sent in batches of `lint_batch_pages`=12. Each batch is one call: `generate_json(MAINTAINER_SYSTEM, with_schema(schema, lint_prompt(pages_md, index)), LINT_SCHEMA)`.
  - `pages_md` is made of `<page slug="…" title="…">\n{content}\n</page>` blocks.
  - `index` is the full compact index, synthesis pages included.
- Results are merged per key.
- `missing_pages` are filtered to slugs that do not already exist, with duplicates removed.
- `missing_links` are filtered so both slugs exist and differ.
- `contradictions`, `stale_claims`, `questions` and `sources_to_find` are passed through unfiltered.
- Pages in different batches are never compared with each other (inference from the batching).

**Fix** (`fix`, `lint.py:107-174`):
- **New pages.**
  - Candidates are the broken-link targets (title from the slug, `type "concept"`, reason `"Linked from other pages but does not exist"`) and the LLM's `missing_pages`.
  - Singular and plural variants are skipped with `key = re.sub(r"(es|s)$","",slug)`.
  - The list is capped at `max_pages_per_ingest` = **17**.
- **Writing a new page.** Each is a call to `with_schema(schema, write_page_prompt(..., focus=f"{reason}. Write the page from what the wiki already says; keep claims attributed to their sources.", existing_md=None, material=_mentions(...), source_slug=None))` with `PAGE_SCHEMA`.
  - `_mentions` uses the `mentioned_in` pages, or else the top 4 search hits for the title (`lint.py:100-104`).
  - The op is a create with `change_note "Lint fix: {reason}"`.
- **Link edits.**
  - Candidates are the LLM's `missing_links` and the orphans. Each orphan is linked from the best of its top 3 search hits that is not itself, else from `overview`.
  - Capped at **17** pages.
  - Each is a call to `add_links_prompt(slug, content, "[[t]]\n...")` with `PAGE_SCHEMA`. This call is **not** wrapped in `with_schema`.
  - The page keeps its existing title and type. The existing summary and tags win over the model's.
  - `change_note "Lint fix: add links to …"`.
- `citecheck.check_ops` runs on all fix ops, then `store.commit(wiki_id,"lint","Lint fixes",ops,mode)`.
- **Not fixed:** contradictions, stale claims, missing metadata, thin pages, unsourced pages and duplicates are reported only.

**Output and storage** (`lint.run`, `lint.py:177-191`):
- The result is `{"structural", "llm", "fix"?}`, stored as the job result.
- A log entry of kind `"lint"` is written, titled `"Lint"`, `" + LLM"` or `" + fix"`, with counts per key and the fix status.
- There is no separate findings table.
- **There is no coverage pass in lint.** The paragraph coverage check exists only in ingest, as "Not yet covered".

---

### 6.8 Pages, versions, changesets, links, index and change log (`store.py`)

**Constants and helpers**
- `PAGE_TYPES = ("overview", "topic", "concept", "entity", "comparison", "synthesis", "source")` (`:14`). The order is the grouping order in index.md and the viewer.
- `LINK_RE = r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]"` matches `[[slug]]`, `[[slug#anchor]]` and `[[slug|label]]` (`:15`).
- `slugify(text)`: lower-cases, turns each `[^a-z0-9]+` run into `-`, strips `-`, truncates to 80 characters, and falls back to `"page"` (`:22-24`).
- `extract_links(md)`: the set of slugified link targets (`:27-28`).
- `NotFound` exception (`:18`).

**Wikis and log**
- `get_wiki(slug)` raises NotFound (`:33-38`).
- `add_log(wiki_id, kind, title, detail="", conn=None)` inserts into `wiki.log`, optionally inside the caller's transaction (`:41-47`).
- The change log lives only in the `wiki.log` table. log.md is rendered from it (below).

**Page reads**
- `get_page`, `get_pages` (`slug = any`), and `list_pages(wiki_id, with_content=False)`. The latter selects `id, slug, title, type, summary, tags, version, updated_at`, ordered by `type, slug` (`:52-73`).
- `backlinks` (`:76-84`).
- `page_sources(page_id)` returns the slug, title, kind and uri of the sources, ordered by created_at (`:87-95`).

**Page chunks (search units)** (`_chunks`, `:98-106`)
1. Splits `content_md` before every heading of level 1 to 3: `re.split(r"\n(?=#{1,3} )", md)`.
2. Splits each section with `split_long(sec, chunk_max_words=500)`, which breaks on sentence boundaries.
3. Prefixes each chunk with `f"{title}\n"`.
4. If nothing is left, the single chunk is `f"{title}\n{summary}"`.

There is no overlap between chunks. The summary is not embedded unless the content is empty.

**`Op` dataclass** (`:111-121`)
- Fields: `op` (create, update or delete), `slug`, `title`, `type`, `summary`, `content_md` (the last four `str|None`), `tags: list = []`, `base_version: int|None`, `change_note: str = ""`.

**Changesets**
- `create_changeset(wiki_id, kind, summary, ops, job_id, source_id)`: inserts into `wiki.changesets` (status defaults to `pending`) plus one `wiki.changeset_ops` row per op, in one transaction (`:124-140`). Proposed changes are stored as full page contents per op, not as diffs.
- `get_changeset`: returns the changeset and its ops ordered by id (`:143-151`).
- `apply_changeset(id, force=False)` (`:154-230`):
  1. Raises ValueError unless the status is `pending`.
  2. Embeds all chunks of all non-delete ops before the transaction (network calls), including ops later skipped as conflicts.
  3. In one transaction, for each op, takes `select ... for update` on the page. Unless `force`:
     - A `create` op on a page that already exists is a conflict: "page was created elsewhere since (now vN)".
     - An op whose `base_version` is set and differs from the page's version is a conflict: "page is at vX, op written against vY".
     - Conflicted ops are skipped.
  4. For pages that are not synthesis, records `saved.changed_clauses(old, new)`.
  5. A `delete` op deletes the page row (cascading to versions, links, chunks, sources and flags).
  6. Type is `o.type` if it is in PAGE_TYPES, else the existing page's type, else `"concept"`.
  7. An update sets `title = o.title or old`, `summary` = the new one if not None, `content_md = o.content_md`, `tags = o.tags or old tags` (so empty tags cannot clear tags), `version = version + 1`, `updated_at = now()`. A create inserts the page at version 1.
  8. Snapshots the page after the write into `page_versions`, with `change_note` and the changeset's `job_id`. So `page_versions` holds every version including the current one, and version 1 is the create.
  9. Calls `_reindex_page`.
  10. If the changeset has a `source_id`, inserts `page_sources(page, source)` with `on conflict do nothing`.
  11. Sets the changeset to `status='applied', applied_at=now()`.
  12. Runs `saved.flag_changed(...)` over the applied slugs.
  13. Writes a log row of kind `apply`: a list `- op [[slug]]` plus "Conflicts (skipped):".
  14. Returns `{changeset_id, applied[{slug,op,version}], conflicts[{slug,reason}], saved_answers_to_check}`.
- Conflicted ops are skipped, never merged (README:87).
- Edge case [UNVERIFIED]: an update op with `content_md=None` would violate `not null`. In-scope callers always pass content.
- `_reindex_page` (`:233-254`):
  - Replaces the page's `wiki.links` with `extract_links(md)`.
  - Adds `page_sources` for every link starting `source-` that matches a source slug in the wiki. A citation therefore makes a page "sourced".
  - Replaces the page's `page_chunks` (content plus float32 embedding).
- `discard_changeset(id)` (`:257-280`):
  - Sets `status='discarded'` only if it was pending; otherwise raises ValueError.
  - For `kind='ingest'` with a source, it deletes the source if no `page_sources` row references it, and removes the stored file. That frees the sha256 for re-ingest. Returns the removed source slug.
- `commit(wiki_id, kind, summary, ops, mode, job_id, source_id)` (`:283-292`):
  - No ops: `{"changeset_id": None, "status": "empty"}`.
  - Otherwise it creates the changeset. With `mode=="auto"` it applies it and returns `{..., "status":"applied"}`; otherwise it returns `{"changeset_id", "status":"pending", "ops":[{op,slug}]}`.

**index.md and log.md**
- `render_index(wiki)` (`:297-309`):
  - Starts with `# <name> — Index`, then the description.
  - Then per PAGE_TYPES group, `## <Type> pages (n)` followed by lines `- [[slug|title]] — summary`.
  - Generated on request; never stored.
- `compact_index(wiki_id, limit_chars=60000, exclude_types=())` (`:312-323`):
  - The catalogue given to the LLM: lines `slug | type | title | summary`.
  - Cut off at 60,000 characters with `... (N more pages not shown)`. Empty wiki: `(wiki is empty)`.
- `render_log(wiki, limit=500)` (`:326-337`): the last 500 rows in chronological order, as `## [YYYY-MM-DD HH:MM] kind | title` plus detail_md. This is the parseable prefix format from llm-wiki.md.

**Contradiction flags**
- There is no DB structure for contradictions.
- They exist only as the schema convention `> [!warning] Contradiction: ...` (`schema_default.md:29-30`), which the viewer renders as a callout (`view.py:19,45`), plus LLM lint (in `ops/`, §6.5).

**page_flags**: see §7.

### 6.9 Page search (`search.py`)

- `search_pages(wiki_id, query, k, embedding=None)`:
  - Embeds the query with `llm.embed_query` (task type `RETRIEVAL_QUERY`) when no embedding is given.
  - Calls the SQL function `wiki.search_pages(wiki_id, query, vec, k)` with the default `rrf_k=50` (`search.py:9-17`).
- `search_many(wiki_id, queries, k)` (`:20-31`):
  - Batch-embeds the queries as RETRIEVAL_QUERY.
  - Runs each search and keeps the best score per slug, sorted by score descending.
- Method:
  - Full-text: `plainto_tsquery('english')` with `&` replaced by `|`, so terms are OR'ed. Ranked by `ts_rank_cd`; top `4*k` chunks.
  - Vector: cosine `<=>` over all chunks of the wiki; top `4*k`.
  - Fusion: Reciprocal Rank Fusion `1/(50+rank)` summed across both lists.
  - Keeps the best chunk per page and returns k pages, with a 400-character `snippet` (`0001_init.sql:135-176`).
- There is no reranker.
- Page embeddings: `gemini-embedding-001`, 768 dimensions, task `RETRIEVAL_DOCUMENT`, L2-normalised (`llm.py:65-75`). Chunk text is `title + "\n" + section part`, at most 500 words (§5).
- The viewer search uses `k=20` (`view.py:64`).

### 6.10 Saved answers and needs-checking flags (`saved.py`)

**What counts as a saved answer**
- `SAVED_TAG = "saved-answer"` (`:12`).
- `SAVED_SQL` (`:14-17`): `p.type = 'synthesis'` and either the tag is in `p.tags`, or version 1 of the page has a `change_note like 'Filed from query%'`. The second branch recognises legacy saved answers.
- `CITE_RE = r"\[\[(source-[^\]|#]+)(?:#[^\]|]*)?\|([^\]]+)\]\]"` (`:18`): source citations with a label only.
- `saved_answers(conn, wiki_id, readable_only=False)` (`:21-31`):
  - Returns saved answers ordered by `updated_at desc`.
  - `readable_only` excludes pages with a `citation_problems` flag; those are not read by Ask until saved again cleanly.

**Flags**
- `set_citation_problems(conn, page_id, problems)` (`:34-45`):
  - With no problems, it deletes the `citation_problems` flag.
  - Otherwise it upserts the flag with detail `{why: "saved with N citation problem(s)", paragraphs: [link...][:50], pages: [], problems[:50]}`.
- `_statements(md)` (`:48-58`): for each cited `(source, label)`, the set of "statements". A statement is the last sentence or line of the text before the citation (split on `(?<=[.;:!?])\s+|\n`), with `[[...]]` removed and whitespace normalised.
- `changed_clauses(old, new)` (`:61-64`): the (source, label) keys whose statement sets differ, meaning added, removed or reworded.
- `flag_changed(conn, wiki_id, changes, why)` (`:73-91`):
  - For each saved answer (all of them, including citation-problem ones) that cites any changed clause, it upserts a `needs_checking` flag.
  - Detail: `{why, paragraphs: hit[:50] ("source|label"), pages: changed pages it cites}`.
  - Called from `apply_changeset` with `why = changeset summary or kind`.
- `flags(conn, wiki_id)` (`:94-108`): a map slug → flag. `citation_problems` wins, and the other flag is nested under `also`. Each entry includes `kind` and `since` (ISO).

**Clearing flags**
- `DELETE /wikis/{w}/pages/{slug}/needs-checking` clears only `needs_checking` (`routers/pages.py:48-53`).
- `citation_problems` clears only when the synthesis is saved again without problems (README:24).

**Exclusion from material**: per the module docstring and the README, saved answers are never among the chosen pages and are not used by uploads. That logic is in `ops/` (§6.3–§6.6).

### 6.11 Citation check (`citecheck.py`)

**Regexes, verbatim** (`:16-20`)
```python
CITE_RE = re.compile(r"\[\[([^\]|#]+)(#[^\]|]*)?\|([^\]]+)\]\]")
LABEL_RE = re.compile(r"^\[([^\]\n]+)\]", re.M)
RANGE_RE = re.compile(r"\s*[–-]\s*")
STANDARD_NAME = re.compile(r"\b(?:IFRS|IAS|IFRIC|SIC)\s*\d+\b")
FILLER = re.compile(r"\([^)]*\)|\b(?:paragraphs?|paras?|and|to|also)\b|[\s,;:.–\-–]+", re.I)
```

**Algorithm**
- `_norm(label)` (`:23-26`):
  1. `App A:` or `Appendix A :` becomes `Appendix A: `.
  2. `(\d[A-Z]{0,2})([a-z]{1,2})\b` becomes `\1(\2)`, so `3a` becomes `3(a)` and `11Aa` becomes `11A(a)`.
  3. Collapses whitespace and removes Standard names such as "IFRS 9".
- `_matcher(source_text)` (`:29-43`):
  - Collects every stored paragraph label at the start of a line (`[5.5.17]`, `[IE4]`, `[IG A.1]`, `[Appendix A: ...]`), normalised.
  - For labels that are not appendix labels, it adds each end of a range and each parent section prefix of length 2 or more (5.5 of 5.5.17; B5.5 of B5.5.17).
  - Builds one case-insensitive alternation, longest first: `(?<![\w.])(?:...)(?![\w]|\.\d)`.
- `sources(wiki_id)`: slug → matcher for every source in the wiki that has labels (`:46-49`).
- `_covered(key, pat)` (`:52-54`): the label consists only of this source's clauses plus filler.
- `check(content, matchers)`, per `[[slug(#a)?|label]]` (`:57-84`):
  - Slug not a source with labels: left alone.
  - Normalised label with no digit: left alone (it cites the source as a whole).
  - `para` = the key without a leading `p` before a paragraph number (`p35A` becomes `35A`). If the named source matches `key` or `para`: left alone.
  - `others` = other sources fully covering the key (or `para` as a fallback).
  - Exactly one other and the key is a bare number (`(?:paragraphs?\s*)?\d+(?:\([^)]*\))*`): flagged "bare number, not in this source (it is in X)", not moved.
  - Exactly one other, not a bare number: corrected to `[[other#anchor|label]]`.
  - Otherwise flagged "not in any source" or "in several sources: a, b".
- `check_ops(wiki_id, ops)` (`:87-106`):
  - Mutates `o.content_md` in place.
  - Report: `{corrected:[{page,count,moves[{from,to,count}],labels[:50]}], flagged:[{page,source,label,reason,count}]}`.
  - Called from ops/ (ingest, lint, synthesis, query save).

### 6.12 Job queue (`jobs.py`)

- Docstring: "In-process background jobs with state persisted in wiki.jobs. Single-instance by design" (`:1-4`).
- State lives in the `wiki.jobs` table. Statuses: `queued` (insert default), `running`, `succeeded`, `failed`. Kinds used: `ingest` (`routers/sources.py:39`) and `lint` (`routers/ops.py:118`).
- `submit(wiki_id, kind, params, fn)` (`:42-53`): inserts the job row and starts `asyncio.create_task(_run(...))` straight away. There is no polling worker loop, so there is no polling interval. Tasks are held in `_tasks` to prevent garbage collection.
- `_run` (`:56-71`):
  - Takes the per-wiki `asyncio.Lock`, then the global `Semaphore(job_workers=2)`. A queued job holds its wiki lock while waiting for the semaphore.
  - Then `status='running', started_at=now()` and `await fn(JobContext)`.
  - Any exception: `failed` with error `"<Type>: <msg>"`, and the traceback logged.
  - Otherwise: `succeeded` with the result, JSON round-tripped with `default=str`. `finished_at` is set either way.
- Retries: none at job level. Retries exist only in llm.py (§11).
- `JobContext.progress(**kw)` merges `progress || jsonb` (`:27-29`).
- `recover()` at startup (`:32-39`): marks all `queued` and `running` jobs as failed with "Interrupted by server restart". They are not resumed.
- `_wiki_locks` is a dict that is never pruned (`:20`).
- Multiple instances would not coordinate: the locks are process-local (README:86).

### 6.13 Model calls (`llm.py`)

**Client and retries**
- Client: `genai.Client(api_key=gemini_api_key)`, cached (`:18-20`).
- `_retry(fn, attempts=5)` (`:23-32`):
  - Retries `errors.APIError` with codes `RETRYABLE = {429, 500, 502, 503, 504}`.
  - Delay is `2**i * 2` seconds, so 2, 4, 8, 16s between the 5 attempts.

**Generation**
- Model `gemini_chat_model` (default `gemini-2.5-flash`). `GenerateContentConfig(system_instruction=system, temperature=0.1)` (`:82-83`).
- Not set: max_output_tokens, thinking config, top_p and so on.
- `generate(system, prompt, schema=None)` (`:86-100`):
  - JSON mode when `schema` is given: `response_mime_type="application/json"`, `response_json_schema=schema`.
  - Empty text raises `EmptyResponse` with finish_reason or block_reason.
  - In JSON mode, a finish reason other than `STOP` raises `EmptyResponse`, which covers truncated JSON such as RECITATION or MAX_TOKENS.
- `generate_json(..., attempts=3)` (`:116-124`): retries on `EmptyResponse` or `JSONDecodeError`, with no delay.
- `stream(system, prompt)` (`:107-113`): `generate_content_stream`, yielding `chunk.text`. Retry covers only opening the stream.
- `gather_limited(coros, limit=None)` (`:127-135`): a semaphore, by default `llm_concurrency=4`.

**Embeddings** (`embed(texts, task="RETRIEVAL_DOCUMENT")`, `:65-75`)
- Model `gemini-embedding-001`, `output_dimensionality=768`, batches of `embed_batch=100`.
- Each vector is L2-normalised with numpy float32 (`_normalize`, `:59-62`).
- `embed_query` uses `RETRIEVAL_QUERY` (`:78-79`). These are the only two task types used.

**Usage recording** (`:35-56`)
- A `contextvars` list started by `track_usage()` collects usage.
- Generation entries: `{step: "json"|"answer", model, input_tokens: prompt_token_count, output_tokens: candidates_token_count, thinking_tokens: thoughts_token_count}`.
- Embed entries: `{step:"embed", model, texts, chars, input_tokens: None, output_tokens: None}`. Embedding tokens are not counted.
- Streamed calls are not recorded.
- Used by `query.answer`, which returns `usage` in the response (`ops/query.py:151,158`). For the benchmark: "cost per query".

### 6.14 Model and temperature per call

Every generative call uses `gemini_chat_model` (default `gemini-2.5-flash`) at `temperature` (default `0.1`), from `config.py:13,17` through `llm.py:83,89,109`.

| Call | Function | JSON schema | Wiki schema prepended |
|---|---|---|---|
| Notes | `ingest.py:293` | NOTES_SCHEMA | yes |
| Route | `ingest.py:353` | ROUTE_SCHEMA | no |
| Also pick | `ingest.py:392` | ALSO_SCHEMA | no |
| Plan | `ingest.py:407` | PLAN_SCHEMA | yes |
| Write page / part | `ingest.py:496` | PAGE_SCHEMA | yes |
| Fill pass | `ingest.py:541` | FILL_SCHEMA | yes |
| Also record | `ingest.py:577` | FILL_SCHEMA | yes |
| Lint check | `lint.py:74` | LINT_SCHEMA | yes |
| Lint new page | `lint.py:134` | PAGE_SCHEMA | yes |
| Lint add links | `lint.py:160` | PAGE_SCHEMA | no |
| Query select | `query.py:26` | SELECT_SCHEMA | no |
| Saved-answer select | `query.py:44` | SELECT_SCHEMA | no |
| Answer | `query.py:157` (`generate`) and `query.py:172` (`stream`) | none; system QUERY_SYSTEM | yes |
| Save answer | `query.py:178` | PAGE_SCHEMA | yes |
| Synthesis draft | `synthesis.py:67` | SYNTHESIS_SCHEMA | yes |

Embeddings use `gemini-embedding-001` with 768 dimensions:
- source paragraphs: RETRIEVAL_DOCUMENT
- section briefs and query text: RETRIEVAL_QUERY
- page chunks at apply time: RETRIEVAL_DOCUMENT (`store.py:165`)

---

### 6.15 HTTP endpoints and the public viewer

All endpoints need `X-API-Key` except `/`, `/health` and `/view*`. `{w}` is the wiki slug; an unknown slug gives 404 via `wiki_dep` (`routers/deps.py:10-14`). `Mode = Literal["auto","review"]` (`deps.py:7`).

**Wikis** (`routers/wikis.py`)

`POST /wikis` (201)
- `WikiIn`: `slug` must match `^[a-z0-9][a-z0-9-]{1,62}$`; `name` (str, required); `description` (default ""); `schema_md` (optional, defaulting to `schema_default.md` read at import, `:17`).
- A duplicate slug gives 409. Logs `edit "Wiki created"`. Returns the row (`:20-44`).

`GET /wikis`
- id, slug, name, description, created_at, plus page and source counts (`:47-57`).

`GET /wikis/{w}`
- The wiki row plus `pages`, `sources`, `last_change_id`, `last_change_at` (latest applied changeset). Comment: "a benchmark run records it" (`:60-71`).

`DELETE /wikis/{w}` (204)
- Cascades the whole wiki and removes stored files (`:74-83`).

`GET /wikis/{w}/schema` (text) and `PUT /wikis/{w}/schema`
- PUT takes `{schema_md}` with min_length 20 and logs `edit "Schema updated"` (`:86-96`).

`GET /wikis/{w}/graph`
- Nodes are pages `{id: slug, title, type, summary, missing: false, inbound, outbound, orphan}`. `orphan` means not `overview` and inbound = 0.
- Link targets with no page become `type:"missing"` nodes. Edges are links, with self-links excluded (`:99-129`).

`GET /wikis/{w}/index.md` and `/log.md`
- Plain text from `render_index` and `render_log` (500 rows) (`:132-139`).

`GET /wikis/{w}/export.zip` (`:146-181`)
- An Obsidian vault named `<slug>-wiki.zip` containing:
  - `<slug>/index.md`
  - `<slug>/log.md` (limit 100000)
  - `<slug>/SCHEMA.md`
  - `<slug>/pages/<slug>.md`, with YAML front matter `title, type, summary, tags, version, updated, sources` and then `# title` plus content
  - `<slug>/raw/<source>.txt` (the source text) and `<source>.meta.yaml` (`title, kind, uri, added`)
- Built fully in memory.

**Sources** (`routers/sources.py`)

`mode` query parameter: default `auto` ("apply changes now"); `review` creates a pending changeset (`:16`).

`POST /wikis/{w}/sources` (202), multipart `file`
- Reads the whole file, then checks it against 50 MB (413). The filename defaults to `upload.txt`.
- Extraction runs in a thread; an unsupported type gives 415.
- Then `_start`:
  1. Empty text gives 422 "No text extracted".
  2. `save_source`; a duplicate gives 409.
  3. Stores the original.
  4. Submits an `ingest` job with params `{source, mode}`.
- Returns `{job_id, source, title, sections, mode, warnings}` (`:28-58`).

`POST /wikis/{w}/sources/url` (202)
- `{url: HttpUrl}`. A fetch or extract error gives 422 "Could not fetch URL: …" (`:70-76`).

`POST /wikis/{w}/sources/text` (202)
- `{title (min 1), text (min 20)}` (`:79-82`).

`GET /wikis/{w}/sources`
- id, slug, title, kind, uri, meta, file, chars, created_at (`:85-94`).

`GET /wikis/{w}/sources/{slug}?include_text=false`
- The row plus the pages that use it. `text` is truncated to 2000 characters unless `include_text` (`:97-114`).

`GET /wikis/{w}/sources/{slug}/file`
- Returns `{url (signed, 1h), name, content_type}`.
- 404 if there is no source or no file; 503 if storage is off; 502 on a storage error (`:117-134`).

`DELETE /wikis/{w}/sources/{slug}` (204)
- Deletes the source and its file. Pages are kept; `page_sources` rows cascade (`:137-147`).

**Pages** (`routers/pages.py`)

`GET /wikis/{w}/pages`
- The page list plus `saved_answer` (bool) and `needs_checking` (flag object or null) (`:27-30`).

`GET /wikis/{w}/pages/{slug}`
- The full row plus `backlinks`, `sources`, `saved_answer`, `needs_checking` (`:40-45`).

`DELETE /wikis/{w}/pages/{slug}/needs-checking` (204)
- Clears the needs_checking flag (`:48-53`).

`PUT /wikis/{w}/pages/{slug}`
- `PageIn`: `title` (required), `type` (default `concept`, must be in PAGE_TYPES else 422), `summary` (""), `content_md` (required), `tags` ([]), `base_version` (optional; 409 if stale), `change_note` (default "Manual edit").
- The slug is slugified. The change is committed as a changeset of kind `edit`, applied with mode `auto` (`:56-68`).

`DELETE /wikis/{w}/pages/{slug}` (204)
- A delete op through `commit(..., "auto")` (`:71-74`).

`GET .../pages/{slug}/versions`
- version, title, summary, change_note, job_id, created_at, chars; newest first (`:77-87`).

`GET .../versions/{v}`: the full version row (`:90-99`).

`POST .../revert/{v}`
- Applies an update op restoring the old title, type, summary, content and tags as a new version (change_note "Revert to vN"), plus a `revert` log row (`:102-111`).

**Operations** (`routers/ops.py`; the logic is in `ops/`, see §6.3–§6.6)

`POST /wikis/{w}/query`
- `QueryIn`: `question` (min_length 3), `save` (false), `mode` ("auto"), `sources` (`"standard"|"all"`, default "all"), `use_saved` (true).
- Returns `{answer, pages (cited), read [{slug,title,type,version,saved,words,sha256}], usage, saved?}` (`ops/query.py:143-158`).

`POST /wikis/{w}/query/stream` (SSE via sse-starlette)
- Event `token`: data is a JSON-encoded text piece.
- Then event `pages`: JSON `[{slug,title,cited,saved}]`, where `cited` means the slug appears in the answer links.
- Then event `done`: empty data.
- Does not support `save`, and has no usage or read record (`routers/ops.py:97-111`).

`POST /wikis/{w}/read-text`
- `ReadTextIn`: `read: list[dict]` (an answer's read record) and `sources` ("all").
- Returns, per page, `{slug, version, saved, text, matches, reason?}`, rebuilt from `page_versions` with a sha256 check. Changes nothing (`routers/ops.py:81-89`, `ops/query.py:123-140`).

`POST /wikis/{w}/synthesis/draft`
- `SynthDraftIn`: `chat_id` (min 4), `chat_title` (""), `answers` (min 1) of `SynthAnswer{searched, answer, sources: standard|all, date (ISO)}`.
- Saves nothing (`:29-57`).

`POST /wikis/{w}/synthesis/check`
- `{content_md, answers}`. Returns `{problems, corrections}` (`:60-63`, `ops/synthesis.py:61`).

`POST /wikis/{w}/synthesis` (201)
- `SynthSaveIn`: the check fields plus `slug` (must match `^[a-z0-9][a-z0-9-]*-synthesis-[a-z0-9]+$`), `title` (min 1), `summary`, `tags`.
- ValueError gives 409. Returns `{slug, status, needs_checking, ...}` (`:66-72`).

`POST /wikis/{w}/lint` (202)
- `LintIn`: `llm` (false), `fix` (false), `mode` ("review").
- Neither flag set: synchronous `{"structural": ...}`. Otherwise a `lint` job, returning `{job_id}` (`:75-119`).

Jobs
- `GET /jobs/{job_id}`: the full job row, or 404 (`:122-127`).
- `GET /wikis/{w}/jobs`: the last 50, without `result` (`:130-139`).

Changesets
- `GET /wikis/{w}/changesets?status=`: latest 100, with an op count (`:144-154`).
- `GET .../changesets/{id}?diff=true`: ops with a unified `diff` against the current page, plus `current_version` (`:167-180`).
- `POST .../{id}/apply?force=false`: not pending gives 409 (`:183-189`).
- `POST .../{id}/discard`: returns `{ok, removed_source}` and logs `edit` (`:192-200`).
- A changeset from another wiki gives 404 (`:157-164`).

**Viewer** (`routers/view.py`; public; prefix `/view`; not in schema)

Routes
- `GET /view`: list of wikis (`home.html`).
- `GET /view/{w}?q=`: grouped index, or hybrid search results with k=20 (`index.html`).
- `GET /view/{w}/log`: rendered log.
- `GET /view/{w}/schema`: rendered schema.
- `GET /view/{w}/{slug}`: page with backlinks and sources (`page.html`). A missing slug gives 404 with `missing.html` (linked-from list, hint to run lint `fix`).

Rendering
- markdown-it `commonmark`, raw HTML disabled, `table` and `strikethrough` enabled.
- `[[links]]` become `<a class="wl">` anchors via private-use placeholders. Links to missing pages get class `broken`.
- `> [!kind]` callouts are rendered (`:17-46`).
- Templates (`templates/base.html`): light and dark CSS variables; header nav Overview, Log, Schema, All wikis; a search box.

**Postman** (`postman/LLM_Wiki.postman_collection.json`)
- Variables: `baseUrl, apiKey, wiki, slug, jobId, changesetId, version`.
- Requests:
  - Health
  - Wikis: create, list, get, get/put schema, index.md, log.md, export.zip, delete
  - Sources: upload `?mode=auto` and `?mode=review`, URL `?mode=review`, text `?mode=auto`, list, get `?include_text=false`, delete
  - Jobs: get, list
  - Query: plain, save, stream
  - Lint: structural, LLM, LLM+fix review
  - Changesets: list pending, get, apply, discard
  - Pages: list, get, PUT `my-notes`, versions, version, revert, delete
  - "Auth check - no key (expect 401)"
- Not in Postman: `/read-text`, `/synthesis/*`, `/graph`, `/sources/{slug}/file`, `/pages/{slug}/needs-checking`.

## 7. Prompts

Every prompt in the codebase, with its location and the output schema it expects. The model and temperature used for each call are in §6.14 (Wiki), §5.4 (RAG) and §8.4 (Benchmark).

| Service | Prompt constants and builders | File | Where reproduced verbatim |
|---|---|---|---|
| RAG | `QUERY_SYSTEM`, `query_prompt`, `BULK_SYSTEM`, `BULK_SCHEMA`, `bulk_prompt`, `REVISE_INSTRUCTIONS`, `revise_prompt`; context format `retrieval.format_context` | `Rag/app/prompts.py`, `Rag/app/retrieval.py` | §7.1 |
| Wiki | `MAINTAINER_SYSTEM`, `with_schema`, `NOTES_SCHEMA`/`notes_prompt`, `ONE_TOP_PAGE`/`PLAN_SCHEMA`/`plan_prompt`, `PAGE_SCHEMA`/`FILL_SCHEMA`/`write_page_prompt`, `ROUTE_SCHEMA`/`ALSO_SCHEMA`/`also_prompt`/`also_record_prompt`/`route_prompt`, query prompts (`QUERY_SYSTEM`, `query_prompt`, `query_saved_prompt`, `SELECT_SCHEMA`), synthesis and save-answer prompts, lint prompts, plus prompt text built inside `ops/*.py` | `Wiki/app/prompts.py`, `Wiki/app/ops/*.py` | §7.2 |
| Benchmark | `KEY_POINTS_SYSTEM`, `GRADE_SYSTEM`, their user templates and JSON schemas | `Benchmark/bench/judge.py` | §8.4 |
| Benchmark | `HARD_FACTS_SYSTEM`, `SUGGEST_SYSTEM`, `HARD_FACTS_SCHEMA`, `SUGGEST_SCHEMA`; `checks.FACTS_SYSTEM` is an alias of `HARD_FACTS_SYSTEM` | `Benchmark/bench/suggest.py`, `Benchmark/bench/checks.py` | §8.5 |
| Benchmark | `CHECK_SYSTEM`, `CHECK_SCHEMA` (answer checks); `SYSTEM`, `SCHEMA` (faithfulness and context recall) | `Benchmark/bench/checks.py`, `Benchmark/bench/context.py` | §8.6 |
| UI server | `REWRITE_SYSTEM`, `REWRITE_SCHEMA` (Ask follow-up rewrite) | `UI/server/app/ask.py` | §7.3 |

### 7.1 RAG prompts (`Rag/app/prompts.py`) and how they are used

**`Rag/app/llm.py`**
- The client is `genai.Client(api_key=...)`, `lru_cache`d.
- Chat model `gemini-2.5-flash`, `temperature=0.1`, via `GenerateContentConfig(system_instruction=system, temperature=...)`.
- **No thinking config is set** (no `thinking_config` / thinking budget), so the model's default thinking applies. `thoughts_token_count` is recorded only as `thinking_tokens`.
- No max_output_tokens, top_p or safety settings are set.

**Retry** (`_retry`, lines 22-31):
- `attempts=5`, `RETRYABLE = {429, 500, 502, 503, 504}`.
- Delay `2 ** i * 2` seconds, i.e. 2, 4, 8, 16. The fifth failure raises.
- Only `google.genai.errors.APIError` is caught. For `stream`, only creating the stream is retried, not errors mid-stream.

**`generate(system, prompt, schema=None)`:**
- With a schema it sets `response_mime_type="application/json"` and `response_json_schema=schema`.
- It records usage with step `"answer"` (no schema) or `"json"` (schema): `{step, model, input_tokens: prompt_token_count, output_tokens: candidates_token_count, thinking_tokens: thoughts_token_count}`.
- Returns `resp.text or ""`.

**`stream`:** `generate_content_stream` yields `chunk.text`. **No usage is recorded for the stream.**

**Usage ContextVar:** `_usage = ContextVar("llm_usage", default=None)`.
- `track_usage()` sets a fresh list, and `_record` appends to it if set.
- Tasks created afterwards inherit the context, so the `asyncio.gather` searches contribute.
- Only `/query` calls `track_usage`. Bulk does not, so bulk usage is not returned.

**Prompts** (`Rag/app/prompts.py`, verbatim)

`QUERY_SYSTEM`:
```
You answer questions using ONLY the passages provided in <context>.
Rules:
- Every statement must be supported by a passage. Do not use general knowledge.
- Each passage starts with its citation key in square brackets, e.g. [5.5.3], [B5.5.17], [Appendix A: credit loss].
- Cite inline by copying that key exactly, including the brackets, e.g. [5.5.3]. Cite several as [5.5.3][B5.5.17]. Never invent or alter keys, never cite page numbers.
- When the Standard allows or requires something only "if", "provided that", "unless" or "only when", state every condition in full.
- If the passages do not answer the question, say so plainly rather than guessing.
- Be concise.
```

`query_prompt(question, context)` → `f"<context>\n{context}\n</context>\n\nQuestion: {question}"`

`BULK_SYSTEM`:
```
You write IFRS requirement blocks using ONLY the passages provided in <context>.
The passages are the binding text of the Standard. Follow the run rules and the topic instructions exactly.
Do not use general knowledge. If a question cannot be answered from the passages, list it as not addressed.
Return JSON matching the schema. Do not put IFRS paragraph numbers in the prose; put them in the source list.
```

`BULK_SCHEMA` (verbatim):
```python
{"type":"object","properties":{
  "prose_paragraphs":{"type":"array","description":"Requirement text, one string per prose paragraph, no IFRS paragraph numbers.","items":{"type":"string"}},
  "source_list":{"type":"array","description":"One row per prose paragraph, same order.","items":{"type":"object","properties":{
      "para":{"type":"integer","description":"1-based prose paragraph number"},
      "covers":{"type":"string","description":"What it covers, a few words"},
      "ifrs_paragraphs":{"type":"array","items":{"type":"string"}},
      "passage_ids":{"type":"array","items":{"type":"string"},"description":"Passage ids, e.g. C123"}},
    "required":["para","covers","ifrs_paragraphs","passage_ids"]}},
  "not_addressed":{"type":"array","items":{"type":"object","properties":{"question":{"type":"string","description":"e.g. Q3"},"note":{"type":"string"}},"required":["question","note"]}},
  "standard_version":{"type":"string","description":"Version of the Standard used, if stated in the passages"}},
 "required":["prose_paragraphs","source_list","not_addressed"]}
```

`bulk_prompt(rules, topic_block, context)` → `f"<run_rules>\n{rules}\n</run_rules>\n\n<topic>\n{topic_block}\n</topic>\n\n<context>\n{context}\n</context>"`

`REVISE_INSTRUCTIONS`:
```
Review the draft against EVERY run rule and the SELF-CHECK list, then return the corrected block as JSON. In particular:
- Fix every detected issue.
- Remove any sentence not supported by a passage, and anything covered by the topic's "Leave out" line.
- No IFRS paragraph numbers in the prose; where the Standard names something only by number, use the name it gives it.
- Keep every "if", "provided that", "unless" and "only when" condition in full.
- Aim for roughly the word guide; cut repetition and supporting detail first, never required points or conditions.
- Every question is answered in the prose or listed under not addressed, after searching the passages.
- Source list: exactly one row per prose paragraph, citing only passage ids present in the context.
```

`revise_prompt(rules, topic_block, context, draft_json, issues)`:
- `found = "\n".join(f"- {i}" for i in issues) or "- (none detected automatically)"`
- returns `f"{bulk_prompt(...)}\n\n<draft>\n{draft_json}\n</draft>\n\n<detected_issues>\n{found}\n</detected_issues>\n\n{REVISE_INSTRUCTIONS}"`

**Citations** (`query.py`):
- `CITE_RE = re.compile(r"\[([^\[\]]+)\]")`.
- `_cited(answer, rows)`:
  - refs = every bracket match, split on `,` and stripped.
  - hit = rows whose `para_ref` or `C<id>` is in refs.
  - Returns `citation()` for the hits, **or for all retrieved rows if nothing matched** (fallback).
- A para_ref shared by several chunks (body parts or notes) returns all of them.
- Citations are matched only against the retrieved rows; an invented key is silently dropped.

**`POST /collections/{c}/query`** (lines 75-86) returns:
- `answer`
- `citations`: list of citation dicts
- `read`: every passage given to the model, as `{chunk_id, para_ref, source_type, page, document_id, content}`
- `usage`: the list of embed and answer call records
- With no rows: `{"answer":"No relevant passages found.","citations":[],"read":[],"usage":usage}` and no LLM call.

**`POST /collections/{c}/query/stream`** (lines 89-106) returns an `EventSourceResponse` with these events:
- `token`, whose data is `json.dumps(text_piece)` (a JSON string)
- then `citations` (JSON array)
- then `done` (empty data)
- With no rows it sends one token, "No relevant passages found.", then `citations` `[]`, then `done`.
- It has no `read` and no `usage`. Retrieval happens before the response starts.

### 7.2 Wiki prompts (`Wiki/app/prompts.py` and prompt text in `Wiki/app/ops/*.py`)

Unless noted otherwise, every call uses `system = MAINTAINER_SYSTEM`.

#### `MAINTAINER_SYSTEM` (`prompts.py:5-7`)
```
You are the maintainer of a persistent, interlinked markdown wiki.
You follow the wiki's schema document exactly. You only write what the provided material supports.
You never invent sources, facts or page slugs that you were not given, unless asked to propose new pages.
```

#### `with_schema` (`prompts.py:10-11`)
```python
def with_schema(schema_md: str, body: str) -> str:
    return f"<wiki_schema>\n{schema_md}\n</wiki_schema>\n\n{body}"
```
- **Used by:** notes, plan, write page, fill, also_record, lint check, lint new page, query answer, save_answer, synthesis.
- **Not used by:** route, also (pick), select, select_saved, add_links.

#### `NOTES_SCHEMA` and `notes_prompt` (`prompts.py:16-52`)
```python
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
```

#### `ONE_TOP_PAGE`, `PLAN_SCHEMA` and `plan_prompt` (`prompts.py:57-99`)
```python
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
```

#### `PAGE_SCHEMA`, `FILL_SCHEMA` and `write_page_prompt` (`prompts.py:104-209`)
```python
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
```

#### `ROUTE_SCHEMA`, `ALSO_SCHEMA`, `also_prompt`, `also_record_prompt` and `route_prompt` (`prompts.py:214-273`)
```python
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
        f"Every paragraph in <paragraphs> comes from the source [[{source_slug}]]. Cite each one to that source, as "
        f"[[{source_slug}|<paragraph number>]], and never to any other source page.\n"
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
```
`also_record_prompt` is called with `FILL_SCHEMA`, not a schema of its own (`ingest.py:581`).

#### Query prompts (`prompts.py:278-319`)
```python
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


def select_saved_prompt(question: str, listing: str) -> str:
    return (
        "These are saved answers: earlier questions answered from the wiki and filed back into it. Pick at most 2 that "
        "answer the same question or a closely related one, so they can be read alongside the wiki pages. Return their "
        "slugs; return none if none is clearly related.\n\n"
        f"<saved_answers>\nslug | title | summary\n{listing}\n</saved_answers>\n\nQuestion: {question}"
    )


def query_saved_prompt(question: str, pages_md: str, saved_md: str) -> str:
    return (
        f"<wiki_pages>\n{pages_md}\n</wiki_pages>\n\n<saved_answers>\n{saved_md}\n</saved_answers>\n\n"
        "The saved answers are earlier answers filed back into the wiki, given only as a guide. Check every point against "
        "the wiki pages: state only what the wiki pages support, citing the wiki pages and their source paragraphs as usual. "
        "Never cite a saved answer, and do not repeat a point from a saved answer that the wiki pages do not support.\n\n"
        f"Question: {question}"
    )
```
- `select_saved_prompt` reuses `SELECT_SCHEMA`.
- The answer call (`query_prompt` or `query_saved_prompt`) uses `QUERY_SYSTEM` as its system prompt and **has no output schema**.

#### Synthesis and save-answer prompts (`prompts.py:322-353`)
```python
SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "A concise descriptive title for what the chat established"},
        "summary": {"type": "string", "description": "One line for the index"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "content_md": {"type": "string", "description": "The consolidated summary (markdown, no top-level # title, no list of the questions)"},
    },
    "required": ["title", "summary", "tags", "content_md"],
}


def synthesis_prompt(chat_title: str, answers: str) -> str:
    return (
        f"These are the wiki's answers to the questions of one chat (\"{chat_title}\"), oldest first. Write ONE consolidated "
        "summary of what they establish, organised by topic, for a synthesis page.\n"
        "- Use only what the answers say: no outside knowledge, no new facts, no conclusions they do not draw.\n"
        "- Keep each statement's citations exactly as they appear in the answers (same [[...]] links, same labels); cite "
        "nothing that is not in the answers. Where answers repeat a point, state it once.\n"
        "- If answers differ or one is narrower than another, say so rather than merging them.\n"
        "- Do not list the questions or the dates: they are recorded on the page separately.\n"
        "- Write plain markdown (headings, paragraphs, - bullet lists); never HTML tags such as <ul> or <li>.\n\n"
        f"<answers>\n{answers}\n</answers>"
    )


def save_answer_prompt(question: str, answer: str, linkable: str) -> str:
    return (
        "Turn this question and answer into a synthesis page for the wiki. Keep every citation link. "
        "Link only slugs in <linkable_pages>. Choose a concise descriptive title.\n\n"
        f"<linkable_pages>\n{linkable}\n</linkable_pages>\n\nQuestion: {question}\n\n<answer>\n{answer}\n</answer>"
    )
```
`save_answer_prompt` is called with `PAGE_SCHEMA`.

#### Lint prompts (`prompts.py:358-407`)
```python
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
```
`add_links_prompt` is called with `PAGE_SCHEMA`.

#### Prompt text built inside the ops files
| Where | Text |
|---|---|
| `ingest.py:345-347` | route `note` (quoted in 1.2) |
| `ingest.py:424` | overview focus: `f"Integrate the new source {ex.title} into the overview"` |
| `ingest.py:439` | added section page focus: `f"Section {sec['num']:02d}: {sec['name']}"` |
| `ingest.py:619-622` | `source_focus` (quoted in 1.5) |
| `ingest.py:565` | also-record item prefix: `f"(main page: [[{slug}]])"` |
| `lint.py:138` | lint new-page focus: `f"{info['reason']}. Write the page from what the wiki already says; keep claims attributed to their sources."` |
| `lint.py:127` | broken-link reason: `"Linked from other pages but does not exist"` |
| `query.py:154-155` | fixed no-pages answers (quoted in section 3) |

---

### 7.3 UI server prompt: Ask follow-up rewrite (`UI/server/app/ask.py`)

Used by `POST /api/ask/chats/{id}/rewrite` (`ask.py:rewrite`). It is sent to Gemini REST `v1beta/models/{GEMINI_MODEL}:generateContent` with `responseMimeType: application/json`, `responseJsonSchema: REWRITE_SCHEMA` and `temperature: 0`, with a 60 s timeout (`ask.py:_gemini_json`). Only the chat's earlier *questions* (the `searched` column), at most `ASK_HISTORY_QUESTIONS` = 6 of them, are sent; no answers are sent (`ask.py:rewrite`, `UI/server/app/config.py`). If there are no earlier questions, no call is made.

`REWRITE_SYSTEM` (verbatim):
```
You rewrite a follow-up question from a chat into one complete question that can be searched on its own.
Use the earlier questions only to work out what the follow-up refers to (pronouns, "and for...", "what about...").
Keep the follow-up's meaning, scope and wording as far as possible; do not answer it, and do not add facts, conditions or
assumptions that are not in the questions. If the follow-up is already complete on its own, return it unchanged.
```

`REWRITE_SCHEMA`: `{"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}`

User prompt (`ask.py:rewrite`):
```python
"Earlier questions in this chat, oldest first:\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(earlier, 1)) + f"\n\nFollow-up: {q}"
```

### 7.4 Benchmark prompts

The judge, rubric-suggestion, answer-check and context-check prompts are reproduced verbatim inside the evaluation section, next to the logic that uses them:
- §8.4: `KEY_POINTS_SYSTEM`, `GRADE_SYSTEM`, user templates, `KEY_POINTS_SCHEMA`, `GRADE_SCHEMA`
- §8.5: `HARD_FACTS_SYSTEM`, `SUGGEST_SYSTEM`, user templates, schemas
- §8.6: `CHECK_SYSTEM`, context-check `SYSTEM`, user templates, schemas

## 8. Evaluation and benchmark

### 8.0 Method in one page

**1. Inputs** (`Benchmark/bench/data.py`, `UI/server/app/bench.py:start`).
- A *query set* `.txt` defines the topics. Each topic has a title and questions `Q1..Qn`.
- A *reference* `.docx` holds one human-written answer per topic. In this project that is the client memo, shown only as "Reference memo N".
- Both files are stored with the run in `bench.runs` (`query_set`, `reference` bytea).

**2. Configuration** (`bench.runs` columns, `Benchmark/bench/config.py`):
- the topics, given as a list or ranges;
- repetitions per topic (`runs`, default 2);
- the RAG collection and the wiki;
- `sources`: `standard` (Part A only) or `all`;
- `use_saved`: whether the wiki may read saved answers;
- `mode`: `quick`, or `full`, which adds faithfulness and context recall and requires an approved rubric (`UI/server/app/bench.py:_ensure_approved`, `run.py:main`);
- `use_batch`: Anthropic Message Batches, used only with the API backend.

**3. Querying** (`Benchmark/bench/systems.py`). For every topic and repetition, the identical question text (title plus questions) is sent once to each system:
- RAG: `POST /collections/{c}/query`
- Wiki: `POST /wikis/{w}/query` with `save=false`

The answer is recorded with its citations, latency, what was read (`read`) and the model token usage (`usage`). Answers are saved before any grading, so a run can resume (`run.py:answer_topic`).

**4. Judge** (`Benchmark/bench/judge.py`).
- Claude, by default `claude-opus-5-5` at effort `high`.
- Called through the Anthropic API (`JUDGE_BACKEND=api`) or the local Claude Code CLI (`claude-code`) (`config.py`, `judge.py:_cli_call`).

**5. What is graded against.**
- Key points are derived once per reference file (keyed by its SHA-256) from the human reference answer and stored as a versioned *rubric* in `bench.rubrics` (`rubric.py`).
- Each key point carries a tag: `standard`, `supporting` or `beyond_standard`.
- The rubric can be reviewed, edited and approved in the UI (§9.3), and changes can be suggested with paragraph evidence (`suggest.py`, §8.5).

**6. Blind A/B grading in both orders** (`run.py:_labels`, `_per_order`, `_record`).
- The judge sees the two answers as "A" and "B", never the system names.
- Order 1 is a seeded shuffle (`random.Random(f"{seed}-{topic}-{rep}")`); order 2 swaps it.
- Each pair is graded twice. Scores are averaged, and a win counts only when both orders pick the same system; otherwise it is a tie.

**7. Further per-answer tests.**
- Answer checks: completeness, exact match, Standard-only exact match and citation accuracy, from one Sonnet call per answer (`checks.py`).
- Full mode only: faithfulness, context recall and Standard-only context recall, from one Sonnet call per answer against exactly what the answer read (`context.py`).
- Latency and cost per query (`metrics.py`).

**8. Uncertainty** (`gaps.py`). Every wiki-minus-RAG gap gets a 95% bootstrap confidence interval over topics, from 10,000 resamples with a fixed seed. The verdict is "Wiki better" or "RAG better" only when the interval excludes 0; otherwise "no clear difference".

**9. Storage and display.**
- Everything is stored in the `bench.runs.results` JSON (§8.8).
- The UI shows it on the runs list, the run page scorecard, the topic page, the compare page and the rubric screen (§9.3).

### 8.0.1 Metric summary

| Metric | Unit | Per answer or pair | Definition in short | Code |
|---|---|---|---|---|
| Similarity | 0–10 (integer per order) | pair | judge's overall closeness to the reference; mean of both orders | `judge.py:GRADE_SCHEMA`, `run.py:_record` |
| Coverage | % | pair | `100 × Σ weight / #key points`, with full 1, partial 0.5, missing 0; mean of both orders | `run.py:coverage`, `WEIGHT` |
| Standard-only coverage | % | pair | the same, over key points tagged `standard` | `run.py:coverage(..., "standard")` |
| Standard + Supporting coverage | % | pair | the same, over `standard` and `supporting`; only when `sources == "all"` | `run.py:_record` |
| Wins | count; gap as share of answers | pair | the system both orders pick, else a tie | `run.py:_record`, `aggregate` |
| Completeness | % | answer | answered 1, partly 0.5, not answered 0, over the topic's questions | `checks.py:score` |
| Exact match | % | answer | share of the topic's hard facts the answer states | `checks.py:score` |
| Standard-only exact match | % | answer | the same, over facts tagged `standard` | `checks.py:score` |
| Citation accuracy | % | answer | supported 1, partly 0.5, not supported 0, over citations whose paragraph could be found; others are counted as not checkable | `checks.py` |
| Faithfulness | % | answer, Full mode | share of the answer's claims backed by what it read | `context.py:score` |
| Context recall | % | answer, Full mode | key points present (1), partly (0.5) or absent (0) in what was read | `context.py:score` |
| Standard-only context recall | % | answer, Full mode | the same, over key points tagged `standard` | `context.py:score` |
| Latency | seconds | answer | wall-clock time of the HTTP call, including the client's retries | `systems.py:ask` |
| Cost per query | USD | answer | the answer's recorded generation tokens × `prices.json`; embeddings excluded | `metrics.py:cost_usd` |

**Named frameworks.** No named evaluation framework is used. RAGAS, RGB, DeepEval, TruLens and similar are neither in any `requirements.txt` nor imported (§8.9). "Faithfulness" and "context recall" share names with RAGAS metrics, but they are implemented from scratch as single Claude calls (`Benchmark/bench/context.py`).

### 8.1 Entry points, run creation and resume

All are `python -m bench.<module>`, run from `Benchmark/`.

| Command | Args | Source |
|---|---|---|
| `bench.run` | `--topics` ("e.g. 1,2,5-7 (default: all)"), `--runs` (int), `--run-id` ("stored run to execute or resume") | `run.py:main` L322-327 |
| `bench.rubric list` / `rebuild <sha256>` / `seed <run-id>` | | `rubric.py:main` L101-116 |
| `bench.checks facts <sha256>` / `backfill <run-id>\|all` | | `checks.py` L418-425 |
| `bench.suggest <sha256> [topics e.g. 1,5 or ranges]` | | `suggest.py` L343-354 |
| `bench.metrics backfill <run-id>\|all` | | `metrics.py` L130-134 |
| `bench.migrate` | none | `migrate.py:main` |
| `bench.import_results <dir> [dirs...]` | reads `<dir>/results.json`. A relative dir resolves against `Benchmark/`. | `import_results.py:main` |
| `bench.data` | prints the topic-to-reference mapping check | `data.py` L82-86 |

**Topic parsing.** `parse_topics` splits on "," and handles "a-b" ranges. An empty spec means all topics 1..n (`run.py:parse_topics` L30-37).

**New run (CLI), `run.py:_new_run` L304-319:**
- It requires `RAG_COLLECTION` and `WIKI_SLUG`, otherwise it exits.
- `SOURCES` must be `standard` or `all`.
- `run_id = datetime.now().strftime("%Y%m%d-%H%M%S")`.
- It inserts into `bench.runs`: id, topics, runs, rag_collection, wiki_slug, sources, use_saved, mode, use_batch, query_set_name, and the query_set bytes, reference_name and reference bytes read from the local files.

**Run/resume, `run.py:main` L330-432:**
- The row is loaded. It fails if the query_set or reference is missing, or if there is no rag_collection.
- These settings are overridden from the row:
  - `rag_collection`, `wiki_slug`, `sources` (default "all").
  - `use_saved = row["use_saved"] is not False`, so null means True.
  - `mode = row.mode or settings`.
  - `use_batch`: the row value unless null.
- If `judge_backend == "claude-code"`, `use_batch` is forced to False (L344-345).
- `runs = args.runs or row["runs"]`.
- `ref_sha` is the SHA-256 of the reference bytes (`rubric.sha256`).
- The inputs are written to a temp dir and loaded with `data.load`. Topics are filtered by `--topics`, or by the row's `topics` column.
- **Full mode gate** (L361-367): every chosen topic needs a `bench.rubrics` row with `reviewed_at is not null and facts is not null and facts_reviewed_at is not null`. Otherwise it raises: "Full runs need an approved rubric...".
- If `store.data` is empty, the config is built (section 10).
- Pipeline order:
  1. `answer_topic` for every topic (gather, `return_exceptions=True`).
  2. `config.rubric_used`.
  3. `metrics.compute`, then save.
  4. `grade_all`.
  5. `checks.run_checks` (an exception is logged and the checks show as not measured).
  6. In Full mode, `context.run_context`.
  7. `metrics.compute` again.
  8. `errors`, `aggregate`, `config.finished`.
  9. Status "finished". On any BaseException the status is "failed" and the exception is re-raised.
- **Resume behaviour:**
  - `answer_topic` skips a repetition that already has `answers` or `judgement` (L131-134).
  - `key_points` is reused from the stored topic record if present (L103).
  - `grade_all` only grades runs that have answers and no judgement, and only the orders not yet stored (L213-229).
  - The batch id is reused if the custom_ids match (L231-233).
  - Answers are saved before grading (L135-138).

**Store and heartbeat, `run.py:Store` L64-93:**
- `LOG_LINES = 300`: only the last 300 log lines are kept.
- `heartbeat()` runs `update bench.runs set updated_at = now()` every 30 s, so the UI can tell a live run from one that was killed.
- `save(status)` writes results, log, `status = coalesce(%s, status)` and `updated_at = now()`.
- An asyncio.Lock serialises DB access.

**Concurrency, `run.py` L392-393:**
- One `asyncio.Semaphore(concurrency)` is shared by topic answering, grading, checks and context calls.
- `answer_topic` holds the semaphore for the whole topic. Inside it, its repetitions run sequentially, and the two systems are asked in parallel (`asyncio.gather`, L136).

---

### 8.2 Topics and the human reference answers (`data.py`)

**Query set:**
- `TOPIC_RE = re.compile(r"^TOPIC (\d+) of (\d+):\s*(.+)$", re.M)` (L11).
- Each block runs from its match to the next match.
- `code, _, title = group(3).strip().partition(" ")`: the code is the first token (e.g. "2.1.2") and the title is the rest.
- Questions are `re.findall(r"^Q\d+\..*$", block, re.M)`.
- CRLF is normalised (L29-38).
- `question_text()` is `f"{title}\n" + "\n".join(questions)`; the code is not sent to the systems (L25-26).

**Reference .docx, `load_references` L45-62:**
- The most recent "Heading 2" paragraph is the section. Each non-empty "Heading 3" paragraph is a topic title, paired with the current section.
- `tables = d.tables[1:]` (table 0 is the status summary). If the counts differ it raises ValueError.
- For each table, **only the first row** is used: `cells[0]` is the `label` and `cells[1]` is the reference `text`. Other rows are ignored.

**Pairing, `load` L65-79:**
- Pairing is positional (`zip`), not by number. The topic and reference counts must be equal.
- Title check: `difflib.SequenceMatcher` ratio of normalised titles (`[^a-z0-9]+` becomes a space) must be ≥ 0.6, or the query title must be contained in the docx title. Otherwise ValueError.
- An empty reference is an error.
- It sets `reference_label`, `reference`, `docx_title` and `section`.

---

### 8.3 How both systems are queried (`systems.py`)

`SYSTEMS = ("rag","wiki")`.

**`_post` (L13-26):**
- Header `X-API-Key`, `timeout=300`, 3 attempts.
- On a 5xx with attempts left, it sleeps `5*(i+1)` s and retries.
- On `httpx.TransportError`/`TimeoutException` it retries the same way until the last attempt.
- 4xx raises immediately.

**RAG, `ask` L32-36:**
- `POST {rag_url}/collections/{quote(rag_collection)}/query` with body `{"question": question, "sources": sources}`.
- `sources` = `[c.get("para_ref") or c.get("chunk_id") for c in data["citations"]]`.

**Wiki, L37-41:**
- `POST {wiki_url}/wikis/{wiki_slug}/query` with body `{"question", "save": False, "sources", "use_saved"}`. The slug is not URL-quoted.
- `sources` = slugs of `pages` with `cited`.
- `saved_answers_read` = slugs of `pages` with `saved`.

**Recorded per answer, L44-45:**
- `answer`, `sources`, (wiki: `saved_answers_read`).
- `read` and `usage` if the service returned them.
- `latency_s` = round(perf_counter delta, 2). This **includes retries and backoff sleeps**.

**`describe` (L48-67), the snapshot stored in config.systems:**
- RAG: `GET /collections/{c}/documents`, giving filename and chunks.
- Wiki: `GET /wikis/{slug}`, giving id, name, slug, pages, sources, created_at, last_change_id, last_change_at.
- Errors are stored, not raised.

`Benchmark/README.md` line 6 says both systems use "the same Gemini model at temperature 0.1". The Benchmark does not set it; the services' own defaults agree: RAG 0.1 (`Rag/app/config.py:temperature`), Wiki 0.1 (`Wiki/app/config.py:temperature`).

---

### 8.4 The judge: key points and blind grading (`judge.py`)

**KEY_POINTS_SCHEMA (verbatim):**
```python
{"type": "object","properties": {"key_points": {"type": "array","items": {"type": "object","properties": {
  "id": {"type": "string", "description": "K1, K2, ..."},
  "point": {"type": "string", "description": "One atomic, checkable point, paraphrased"},
  "kind": {"type": "string", "enum": ["standard", "beyond_standard"]}},
  "required": ["id", "point", "kind"],"additionalProperties": False}}},
 "required": ["key_points"],"additionalProperties": False}
```
The judge can only emit standard or beyond_standard. "supporting" only arrives through review or suggestions.

**KEY_POINTS_SYSTEM (verbatim):**
```
You are an IFRS 9 expert preparing a grading rubric.
Break the human-written reference answer into its key points: atomic, independently checkable statements of substance
(requirements, conditions, definitions, examples, nuances). Cover the whole reference; do not add anything it does not say.
Merge trivial restatements; keep distinct conditions separate.
Tag each point:
- "standard": a requirement, definition or condition that comes from the IFRS 9 / IFRS 7 Standard text itself.
- "beyond_standard": industry practice, regulatory or ITG guidance, Basel references, examples or opinions not in the Standard.
```

**Key points user template (L128-131):**
```
f"Topic: {topic.code} {topic.title}\n\nQuestions the topic asks:\n" + "\n".join(topic.questions)
+ f"\n\n<reference_answer label=\"{topic.reference_label}\">\n{topic.reference}\n</reference_answer>"
```

**GRADE_SCHEMA (verbatim):**
```python
{"type": "object","properties": {
  "point_grades": {"type": "array","description": "One entry per key point, in rubric order","items": {"type": "object","properties": {
      "id": {"type": "string"},
      "A": {"type": "string", "enum": ["full", "partial", "missing"]},
      "B": {"type": "string", "enum": ["full", "partial", "missing"]},
      "note": {"type": "string", "description": "Short justification, quoting wording where useful"}},
    "required": ["id", "A", "B", "note"],"additionalProperties": False}},
  "contradictions": {"type": "object","description": "Statements in each answer that contradict the reference or are wrong",
    "properties": {"A": {"type": "array", "items": {"type": "string"}}, "B": {"type": "array", "items": {"type": "string"}}},
    "required": ["A", "B"],"additionalProperties": False},
  "similarity": {"type": "object","description": "0-10 overall closeness to the reference answer",
    "properties": {"A": {"type": "integer"}, "B": {"type": "integer"}},"required": ["A", "B"],"additionalProperties": False},
  "winner": {"type": "string", "enum": ["A", "B", "tie"]},
  "rationale": {"type": "string", "description": "3-6 sentences: where each answer aligns with or misses the reference"}},
 "required": ["point_grades", "contradictions", "similarity", "winner", "rationale"],"additionalProperties": False}
```

**GRADE_SYSTEM (verbatim):**
```
You are an impartial IFRS 9 expert judging how close two answers are to a human-written reference answer.
The answers come from two different systems; their order is random and carries no meaning. Do not favour length or style.
For each key point of the rubric, grade each answer:
- full: the answer states the point with its substance and conditions intact (wording may differ);
- partial: the answer touches the point but loses a condition, nuance or part of it;
- missing: absent, or the answer says the material does not address it.
Then score overall similarity to the reference from 0 to 10 (10 = covers everything the reference says, with nothing contradictory),
list contradictions or errors relative to the reference, pick the closer answer (or tie), and explain briefly.
```

**Grade user template, `_grade_user` L186-193.** The reference label is not included here.
```
rubric = "\n".join(f"{p['id']} [{p['kind']}]: {p['point']}" for p in points)
f"Topic: {topic.code} {topic.title}\n\nQuestions asked:\n" + "\n".join(topic.questions)
+ f"\n\n<reference_answer>\n{topic.reference}\n</reference_answer>\n\n<rubric>\n{rubric}\n</rubric>"
+ f"\n\n<answer_A>\n{answer_a}\n</answer_A>\n\n<answer_B>\n{answer_b}\n</answer_B>"
```
The judge sees each point's tag in the rubric.

**Blind labels, `run.py:_labels` L141-147:**
- `seq=["rag","wiki"]`, shuffled with `random.Random(f"{seed}-{t.number}-{r}")`.
- Order 2 reverses the list. A = seq[0], B = seq[1].
- `ORDERS=(1,2)`: every pair is graded twice.

**`_per_order` (L153-162):**
- It maps A/B back to system names.
- winner: "tie", or the system name.
- It stores per-system grades, the integer similarity and contradictions, plus point_notes, rationale, judge_model, judge_usage, batch and backend.

**`_record` (L170-205), combining the two orders:**
- `point_weight[id]` = mean over the 2 orders of WEIGHT[grade], with `WEIGHT={"full":1.0,"partial":0.5,"missing":0.0}` (L27).
- `grades` = order 1 grades; `grades_by_order` = both.
- `similarity`, `coverage`, `coverage_standard` and `coverage_std_supp` = `_avg` of the per-order values (rounded to 2).
- `contradictions` = the ordered, de-duplicated union of both orders.
- **Winner:** `w={x["winner"]}`. If the set has one element it is that value (both rag, both wiki, or both tie); otherwise "tie".
- Also stored: `winners_by_order`; rationale as the joined text "Order k (X first): ..."; point_notes from order 1; `orders_graded=2`; judge_usage summed over both orders; `judge_batch` = all orders batched; `judge_backend`; `judgement: True`.

**Batch path:**
- `grade_params` gives the same `_params` without the fallback beta (L200-202).
- `grade_batch` (L205-235):
  - It creates the batch unless resuming, and stores the batch id through `on_submit` as `grading_batch {id, custom_ids}`.
  - It polls every `batch_poll_s`. After `batch_timeout_s` it cancels once and keeps polling until "ended".
  - Each "succeeded" result is parsed with `_parse(batch=True)`. A non-succeeded result, a parse exception, or a missing custom_id becomes an Exception.
  - The caller then grades those normally, with the fallback (`run.py:grade_all` L240-252).
- custom_id format: `t{n}-r{r}-o{k}`.
- If the batch itself fails, everything is graded normally.

**Refusal and max_tokens, `_parse` L73-80:**
- `stop_reason=="refusal"` raises `JudgeRefused(stop_details)`.
- `"max_tokens"` raises a RuntimeError ("Judge output truncated (max_tokens)").
- Otherwise the first text block is parsed as JSON.

**Fallback:** non-batch API calls send `betas=["server-side-fallback-2026-07-01"], fallbacks="default"` (L86-91).

**Per-order failures:** a failed order is recorded in `errors[t.number]` (`grade_all` L255-262). Order results are saved as they arrive, so a resume finishes the missing order.

---

### 8.5 The rubric: versions, approval and suggested changes (`rubric.py`, `suggest.py`, `library.py`)

**Rubric build, `run.py:answer_topic` L102-130:**
- The rubric is looked up by (ref_sha, topic_number).
- If it is missing, or `topic_title != t.title` ("stale"), `judge.key_points` builds it and `rubric.save` stores it with `replace=stale`.
- If `facts is None`, `checks.make_facts` and `save_facts` run.
- The topic record stores key_points, key_points_usage, facts and `rubric {built_in, saved_at, version, approved, facts_approved}`.

**`rubric.save` (L32-51):**
- Insert; on conflict, do nothing, or with `replace`, update the fields, `version+1` and `reviewed_at=null`. Facts and their approval are kept.
- It always copies to `rubric_versions` with note "built" or "rebuilt" (on conflict do nothing).

**Other rubric functions:**
- `rebuild` uses the latest run with that reference SHA. It only rebuilds topics already in the rubric (L69).
- `seed` copies a run's key_points with `replace=True`.

**Approval** (setting reviewed_at / facts_reviewed_at, tags, edits) happens in the UI. Those writes are made by the UI server (`UI/server/app/bench.py:review_topic`, `update_reference`; see §9.2).

**Facts, `checks.py` L37-104:**
- FACTS_SCHEMA: `{"facts":[{"id": "F1, F2, ...", "fact": "One short, specific, self-contained fact"}]}`. Required id and fact; `additionalProperties` False.
- The system prompt is `suggest.HARD_FACTS_SYSTEM`.
- User template: `f"Topic: {topic_title}\n\nQuestions the topic asks:\n" + "\n".join(questions) + f"\n\n<reference_answer label=\"{reference_label}\">\n{reference}\n</reference_answer>"`.
- `save_facts` only acts where `facts is null`. It sets facts_usage and facts_model, `version+1` and `facts_reviewed_at=null`, and writes a version with note "facts made".
- `make_facts` output has no `kind`. A fact's tag comes only from accepted suggestions (UI).

**HARD_FACTS_SYSTEM (verbatim):**
```
You are an IFRS 9 expert preparing an exact-match checklist for grading answers.
From the human-written reference answer, list only its hard facts: numbers, amounts and percentages, time periods
(days, months, years), thresholds, dates, and the yes/no answer to a question when the reference gives one.
- Each fact is one short sentence that contains the hard value and what it applies to, so it can be checked as
  stated, contradicted or not stated.
- Do not list definitions, explanations, lists of examples or general requirements without a hard value.
- Never list remarks about the reference itself (e.g. "the reference gives two approaches", "the answer lists three
  examples"): only facts about IFRS that an answer could state.
- Only facts the reference itself states. At most 10. If it has none, return an empty list.
```

**HARD_FACTS_SCHEMA:** the same shape as FACTS_SCHEMA, but the fact description is "One short sentence holding the hard fact".

**ITEM / SUGGEST_SCHEMA (verbatim):**
```python
ITEM = {"type": "object", "properties": {
    "id": {"type": "string"},
    "tag": {"type": "string", "enum": ["standard", "supporting", "beyond_standard"]},
    "paragraph": {"type": "string", "description": "The paragraph number that backs the tag, as shown; empty for beyond_standard"},
    "document": {"type": "string", "description": "That paragraph's document, as shown; empty for beyond_standard"},
    "check": {"type": "boolean", "description": "true ONLY if you believe a Standard does state this but none of the paragraphs shown does; false when it is backed by a paragraph shown, or when it comes from practice, regulation or opinion"},
    "reason": {"type": "string"}},
    "required": ["id", "tag", "paragraph", "document", "check", "reason"], "additionalProperties": False}
SUGGEST_SCHEMA = {"type": "object","properties": {
    "points": {"type": "array", "items": ITEM},
    "facts": {"type": "array", "items": ITEM},
    "merges": {"type": "array", "items": {"type": "object", "properties": {
        "ids": {"type": "array", "items": {"type": "string"}},
        "point": {"type": "string", "description": "One point keeping every item of the list"},
        "tag": {"type": "string", "enum": TAGS},
        "reason": {"type": "string"}},
        "required": ["ids", "point", "tag", "reason"], "additionalProperties": False}}},
  "required": ["points", "facts", "merges"], "additionalProperties": False}
```

**SUGGEST_SYSTEM (verbatim):**
```
You review an IFRS grading rubric against the original source texts.
The candidate paragraphs (P1, P2, ...) are given once, in full, each marked with its document and tier; each key point
(K...) and fact (F...) lists the ids of its closest paragraphs, found by words and by meaning. Tiers:
- Standard: a Standard's own text (Part A, including its appendices);
- Supporting: documents published with the Standard (Part B implementation guidance and illustrative examples,
  Part C basis for conclusions).
1. For every key point and fact, suggest a tag from the paragraphs shown only, never from memory:
   standard = a Standard paragraph shown states its substance; supporting = only a Supporting paragraph shown states it;
   beyond_standard = no paragraph shown states it (practice, regulation, opinion, or the text shown does not say it).
   Give the paragraph number (e.g. 5.5.5, not P3) and document that back the tag (empty for beyond_standard).
   You may use any paragraph listed, not only the item's own. Set check = true only when you believe a Standard does
   say it but none of the paragraphs shown does, so a person looks it up; a point that comes from practice, regulation
   or opinion is beyond_standard with check = false.
2. Suggest merges: key points that are only items of one list in the reference (e.g. a list of indicators or
   examples) should be a single point that keeps every item. Never merge distinct requirements or conditions, and
   never merge points whose tags differ (now or as you suggest them).
   Return no merges if there are none.
Give a short reason for each.
```

**Suggest user prompt, `suggest._user` L210-228:**
- `Topic: {title}`, then `<reference_answer>`, then `<paragraphs>`.
- Each paragraph is `"{Pn} [{paragraph}] {document} (Standard|Supporting):\n{whitespace-collapsed text}"`, in full and de-duplicated across items.
- Then `<key_points>`: `"{id} (now tagged {kind}): {text}\n  closest paragraphs: P.., ..."`, or "(none found)".
- Then `<facts>`, or "(none)".
- Facts have no "now tagged" part.

**suggest_topic flow (L240-294):**
1. A hard-facts call. Facts matching META_FACT are dropped, but kept in `dropped`.
2. Candidates for each key point and fact via `Finder.find`.
3. A SUGGEST call. `check` is renamed to `found = not check`.
4. Second look:
   - For each item, the reason is scanned by `_named` (NAMED and NAMED_TERM) for paragraphs not shown, which are fetched with `lookup`.
   - It is also scanned by `_definitions` (the DEFINITION regexes), with each phrase resolved by `define` to an "Appendix X: term" paragraph.
   - Items that gain paragraphs are re-asked in a single SUGGEST call. Only those items' verdicts are replaced, with a `second_look` list.
5. Merge filter (L277-283): a merge needs ≥ 2 ids, all existing key point ids, and exactly one tag across the current kinds and the suggested tags.
6. Stored in `bench.rubrics.suggestions`:
   - `made_at`, `model`, `backend`, `base_version`.
   - `usage {hard_facts, suggest, second_look?}`.
   - `search`: "words and meaning" or "words only".
   - `points {id: {tag, paragraph, document, found, reason, second_look?, status: None}}`.
   - `merges`.
   - `facts {status, dropped, items}`.
   - `documents`.
- Source documents are limited to `bench.references.tag_sources` when it is set (L311-313).

**Regexes (verbatim):**
```
NAMED = re.compile(r"\b(?:Appendix [A-Z]: [a-z][a-z \-]+?(?=[,.;)]|$)|IG [A-Z]\.\d+|[A-Z]{1,3}\d+(?:\.\d+)+[A-Z]?|\d+\.\d+(?:\.\d+)+[A-Z]?|IE\d+|BC\d+(?:\.\d+)*|\d{1,3}[A-Z]{1,2})\b")
NAMED_TERM = re.compile(r"Appendix ([A-Z])(?: definition of| defin\w+ of)?\s*['‘\"“]([^'’\"”]{3,80})['’\"”]", re.I)
QUOTE = "['‘\"“]"; UNQUOTE = "['’\"”]"
DEFINITION = [
 re.compile(r"Appendix [A-Z]:\s*([A-Za-z0-9][A-Za-z0-9\- ]{2,80}?)(?=\s+(?:and|or|in|is|as|under|of|to|for|with|but)\b|\s*[.,;:()'’\"”]|\s+\d|$)"),
 re.compile(QUOTE + r"([^'’\"”]{3,80})" + UNQUOTE + r"\s+(?:definition|defined term)", re.I),
 re.compile(r"(?:definitions?|meanings?) of (?:the terms? |the )?" + QUOTE + r"?([A-Za-z][A-Za-z0-9\- ]{2,80}?)" + UNQUOTE
            + r"?(?=\s*(?:[(),.;:]|$|\s(?:in|under|is|as|and|or|shows|says|covers|includes|does|would|which|that)\b))", re.I),
 re.compile(r"defined terms? " + QUOTE + r"([^'’\"”]{3,80})" + UNQUOTE, re.I),
 re.compile(r"((?:[A-Za-z0-9\-]+ ){1,5}?)definition\b", re.I),
]
TERM_STOP = {"the","a","an","ifrs","ias","9","7","standard's","standard","appendix","its","this","that","of"}
META_FACT = re.compile(r"\b(?:the )?(?:reference|memo|assessment|answer|author)\b[^.]{0,40}\b(?:gives|lists|states|describes|mentions|says|notes|"
                       r"provides|sets out|presents|offers|refers|contains|includes|discusses|explains)\b", re.I)
```

`_norm_term` (L181-194):
- lower case, hyphens become spaces, "'s " is removed;
- singularises words longer than 3 letters (sses/xes/ches/shes drop 2; ies becomes y; a trailing s is dropped unless "ss");
- drops leading TERM_STOP words.

`define` tries the whole phrase first, then shorter word endings, against the `Appendix X: term` labels.

**Finder (L99-135):**
- **By meaning:** `POST {rag_url}/search/paragraphs` with `{"text", "k": 8, "filenames": [f"{title}.pdf" for each library source]}`, `timeout=60`.
  - On any error, `semantic=False` for the rest of the run (words only).
  - Hits are mapped back to library paragraphs by filename and `para_ref`.
- **By words:** `lib.search(text, k=8)`.
- Meaning hits come first. The list is de-duplicated by (source, paragraph) and **capped at 14**.

**Library tiers (library.py):**
- Read from `wiki.sources`: `distinct on (slug) ... order by slug, length(text) desc`, so the longest text per slug is used.
- Paragraphs come from `LABEL_LINE = ^\[([^\]\n]+)\][ \t]*`. Repeated labels are concatenated.
- Tier, by `meta.parser`: "ifrs" is standard (Part A); "ifrs_accompanying" is supporting (Parts B and C); anything else is "other". "Other" is excluded from BM25.
- The document name is built from the IFRS/IAS/IFRIC/SIC number plus "Part X", taken from `BB\d{4}-([ABC])` in `meta.title`.

**BM25:**
- k1 = 1.5, b = 0.75.
- idf = `log(1 + (n - df + 0.5)/(df + 0.5))`.
- avg = mean document length in terms.
- The document text is label + " " + text. Page markers `p\d+` are skipped.
- Query terms are a **set** (no query term frequency). Only score > 0 counts.
- `search(k=8, per_tier=2)`: the top 8, then topped up so each of standard and supporting has at least 2.

**Tokenising:**
- `WORD=[a-z0-9]+(?:[.\-][a-z0-9]+)*`, lowercased.
- ABBREV is expanded: ecl/ecls = expected credit losses, sicr, eir, pd, lgd, ead, fvoci, fvtpl, oci, poci, sppi, dpd; "12-month" maps to "12-month" (no-op).
- Stopwords: `a an and are as at be been by can for from has have if in into is it its may must not of on or shall should such than that the their them then there these this those to under was were when where which while who will with would also any each other only same so some its entity entities`.
- Tokens with length ≤ 1 are dropped.
- Stem: words containing digits are left alone. Otherwise the first matching suffix of `("ingly","edly","ings","ing","ed","ly","es","s","e")` is stripped if ≥ 4 characters remain.

`Library.find(part, source)`: an exact label match, or the label with trailing `(a)`-style sub-paragraphs removed. It is restricted to the named slug if one is given.

---

### 8.6 Every metric: exact definitions (`run.py`, `checks.py`, `context.py`, `metrics.py`)

All per-answer metrics are stored as `{"value", "status": "measured"}` or `{"value": None, "status": "not measured", "reason"}` (`metrics.py` L26-31). Nothing is ever stored as 0 or as an estimate.

**Similarity:**
- An integer 0–10 per order from the judge. Per run: the mean of 2 orders (`_avg`, 2 decimals).
- Topic: mean ± sd over runs. Summary: mean ± sd of topic means.

**Coverage (`run.coverage` L40-45):**
- `100 * Σ WEIGHT[grade] / #points`, with WEIGHT full 1.0, partial 0.5, missing 0.0. Ungraded ids count as missing.
- Rounded to 1 decimal, computed per order, then averaged over the 2 orders.
- **Standard-only coverage:** the same over points with kind "standard". None if there are none.
- **Standard + Supporting coverage** (`coverage_std_supp`): kinds ("standard", "supporting"), and only when `config.sources == "all"`, otherwise None (L187-189).

**Wins:**
- A run winner is a system only when both orders pick it, otherwise "tie".
- `wins_by_run` counts over all graded runs. Per topic: `aggregate.wins`.

**Key point hit rate:** the mean over runs of `point_weight` (or WEIGHT of the order-1 grade, for older runs) (L287-292).

**Completeness (checks):**
- WEIGHT answered 1, partly 0.5, not_answered 0.
- `100*mean` over questions that have a verdict (1 decimal).
- Questions come from `questions_of`: lines matching `\s*Q\d+[.):]` (L70-72). They are renumbered Q1.. with the prefix removed by `Q_PREFIX=^Q\d+[.):]\s*`.

**Exact match:**
- `100 * #stated / #facts with a verdict`. "Contradicted" counts as not stated.
- Not measured when the topic has no facts ("...has no exact-match facts" if the list was made, else "no exact-match fact list for this topic yet").
- **Standard-only exact match:** the same over facts with `kind=="standard"`. Not measured if the facts have no tags, or none is Standard.
- Facts come from the **current** `bench.rubrics.facts` row, not the run's snapshot (`run_checks` L340-349). The check is redone when VERSION, fact version or approval changes (`_todo`).

**Citation accuracy:**
- Extraction regexes (verbatim):
```
WIKI_CITE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?\|([^\]]+)\]\]")   # [[source-slug|5.5.1]]
WIKI_LINK = re.compile(r"\[\[([^\]|]+)\]\]")                            # [[page]]
BRACKET = re.compile(r"(?<!\[)\[([^\[\]\n]{1,60})\](?!\])")              # [5.5.4], [B5.5.43], [Appendix A: ...]
STANDARD_NAME = re.compile(r"\b(?:IFRS|IAS|IFRIC|SIC)\s*\d+\b")
Q_PREFIX = re.compile(r"^Q\d+[.):]\s*")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z*\[(])")
APPENDIX = re.compile(r"^\s*App(?:endix)?\.?\s*([A-Z])\s*[:.\-–]\s*", re.I)
```
- **Extraction (L148-167):**
  - The answer is split per line, then per sentence.
  - Kinds: "source" (`[[slug|label]]`), "page" (`[[page]]`), and "bare" (`[label]` containing a digit or an Appendix prefix, `_is_clause`).
  - The statement is the sentence with citations removed, whitespace normalised, and " *-•" stripped.
  - Duplicates by (kind, source, label, statement) are removed.
- **Label parts (`_parts`):**
  - Standard names and "paragraph(s)/para(s)/para." are removed.
  - An appendix label becomes "Appendix X: term".
  - Otherwise the label is split on `, ; and &` and on dashes (a range becomes its two ends), keeping parts that contain a digit.
- **Resolution (L170-199):**
  - "page" → not_checkable ("points to a whole page, not a paragraph").
  - No parts → not_checkable ("no paragraph number in the citation").
  - For each part, `lib.find(part, source or None)`. If the named source lacks the paragraph but another source has it, it is a wrong_source.
  - If only wrong_source and no texts → **not_supported** ("names a source that does not hold ...").
  - No texts → not_checkable ("... is not in the source texts available").
  - Otherwise `to_check`, with each paragraph text truncated to `MAX_PARAGRAPH = 3000` characters.
  - Bare citations are searched in all sources and can match several.
  - The Library used for checks is every `wiki.sources` document (`Library(conn)`, no tier filter).
- `MAX_CITATIONS = 40`: the to_check items beyond 40 become not_checkable ("over the 40 citations checked per answer").
- **Score:** `100 * Σ w / #scored`, with supported 1, partly 0.5, not_supported 0, over citations whose status is supported, partly or not_supported. Pre-settled not_supported counts. not_checkable is counted but not scored.
- Not measured: "the answer has no citations", or "none of its N citation(s) could be checked against a paragraph".
- Counts recorded: citations, checked, not_checkable, supported, partly, not_supported, facts_contradicted.

**CHECK_SCHEMA (verbatim):**
```python
{"type": "object","properties": {
  "questions": {"type": "array", "items": {"type": "object", "properties": {
      "id": {"type": "string"}, "status": {"type": "string", "enum": ["answered", "partly", "not_answered"]},
      "note": {"type": "string"}}, "required": ["id", "status", "note"], "additionalProperties": False}},
  "facts": {"type": "array", "items": {"type": "object", "properties": {
      "id": {"type": "string"}, "status": {"type": "string", "enum": ["stated", "contradicted", "not_stated"]},
      "note": {"type": "string"}}, "required": ["id", "status", "note"], "additionalProperties": False}},
  "citations": {"type": "array", "items": {"type": "object", "properties": {
      "id": {"type": "string"}, "status": {"type": "string", "enum": ["supported", "partly", "not_supported"]},
      "note": {"type": "string"}}, "required": ["id", "status", "note"], "additionalProperties": False}}},
 "required": ["questions", "facts", "citations"], "additionalProperties": False}
```

**CHECK_SYSTEM (verbatim):**
```
You check one answer to a set of IFRS questions. You are not told which system wrote it.
Return one entry for every item listed, using its id, with a short note.
1. Questions (Q1, Q2, ...): does the answer address the question? answered = a direct, substantive answer to all of it;
   partly = only part of it, or only vaguely; not_answered = missing, or the answer says it cannot answer.
   Judge whether it is addressed, not whether it is correct.
2. Facts (F1, F2, ...): does the answer state the fact? stated = the same content (wording may differ, but numbers,
   periods, thresholds and yes/no answers must match exactly); contradicted = it states something incompatible;
   not_stated = it does not say it.
3. Citations (C1, C2, ...): each gives a statement from the answer and the text of the paragraph(s) it cites.
   supported = the cited text says what the statement claims, or directly backs it; partly = it backs only part of the
   statement; not_supported = it does not back it. Use only the cited text, not your own knowledge.
```

**Check user template (`_check_user` L233-241):**
- `<questions>\nQ{i}: ...\n</questions>`, then `<facts>\n{id}: {fact}\n</facts>`, then `<citations>`.
- Each citation entry is `"{Cn}: statement: {statement}\n  cites: {label}\n  [{paragraph}] ({source title}): {text}"`, with entries separated by blank lines, or "(none)".
- Then `<answer>...</answer>`.
- Empty lists render as "(none)".
- `VERSION="checks-2"`.
- The model is `checks_model`. Batching is used only if `use_batch` and the backend is api (L361). The checks batch is not resumable (a new batch each time).

**Faithfulness and context recall (context.py, Full mode only; `VERSION="context-2"`, `MAX_CLAIMS=40`, `WEIGHT` present 1 / partly 0.5 / absent 0):**
- **Context:**
  - RAG: `"[{para_ref or '?'}] {content}"` for each item in `read`.
  - Wiki: the `read` items without `saved` (saved answers are excluded), sent to `POST {wiki_url}/wikis/{w}/read-text` with `{"read": pages, "sources": sources}`, `timeout=120`. Each page is wrapped as `<page slug=".." version="..">text</page>`.
  - Not measured if `read` is None ("the run was made before what each answer read was recorded"), if any page text is None ("a page version the answer read is no longer in the wiki"), or if rebuilding fails.
  - The note "some page text differs from what was read" is recorded when a hash does not match, but the answer is still measured.
- **Faithfulness:** `100 * #backed / #claims`, using the first 40 claims. Not measured if there are no claims.
- **Context recall:** `100 * mean(WEIGHT)` over key points with a verdict.
- **Standard-only context recall:** the same over kind=="standard".
- Key points come from the run's `rec["key_points"]`.

**SCHEMA (verbatim):**
```python
{"type": "object","properties": {
  "claims": {"type": "array", "items": {"type": "object", "properties": {
      "claim": {"type": "string"}, "status": {"type": "string", "enum": ["backed", "not_backed"]},
      "note": {"type": "string"}}, "required": ["claim", "status", "note"], "additionalProperties": False}},
  "key_points": {"type": "array", "items": {"type": "object", "properties": {
      "id": {"type": "string"}, "status": {"type": "string", "enum": ["present", "partly", "absent"]},
      "note": {"type": "string"}}, "required": ["id", "status", "note"], "additionalProperties": False}}},
 "required": ["claims", "key_points"], "additionalProperties": False}
```

**SYSTEM (verbatim, with MAX_CLAIMS rendered as 40):**
```
You check one answer against the text it was given to answer from (its context). You are not told which
system wrote it. Use only the context, never your own knowledge.
1. Faithfulness: split the answer into its factual claims (statements of substance; skip headings, restatements of the
   question, and statements that the material does not cover something), at most 40. Mark each:
   backed = the context states it or directly implies it; not_backed = the context does not say it, even if it is true.
2. Context recall: for each key point (K1, K2, ...), does the context contain it? present = with its substance;
   partly = only part of it; absent = not there. This is about the context, not the answer.
Give a short note for each.
```

**Context user template:**
```
f"<questions>\n" + "\n".join(questions) + f"\n</questions>\n\n<key_points>\n{kp}\n</key_points>\n\n"
f"<context>\n{context or '(nothing was read)'}\n</context>\n\n<answer>\n{answer}\n</answer>"
```
Here `kp` is `"{id}: {point}"` per line, without tags.

**Latency:** `latency_s` per answer is wall-clock time including retries (systems.py). It is lower-is-better.

**Cost per query (`metrics.cost_usd` L34-50):**
- Σ over `usage` entries, skipping `step=="embed"`: `input_tokens/1e6*price.input + (output_tokens + thinking_tokens)/1e6*price.output`. Rounded to 5 decimals.
- Not measured if usage is None, or if any model has no price or no input_tokens.
- It covers **only the systems under test's calls**. Judge, check and context costs are not included.
- prices.json (USD per 1M tokens, "Checked 2026-10-16"):

  | model | input | output |
  |---|---|---|
  | gemini-2.5-flash | 0.30 | 2.50 |
  | claude-opus-5-5 | 4.00 | 20.00 |
  | claude-sonnet-5-5 | 2.00 | 10.00 |
  | claude-haiku-5-5 | 0.10 | 0.50 |

  `batch_discount` is 0.5. It is not used in `bench/`, only by `UI/server/app/bench.py` for estimates.

**Quick vs Full:**
- Quick: answers, grading, answer checks, latency and cost.
- Full: also faithfulness, context recall and Standard-only context recall. Full needs an approved rubric (`run.py` L361-367).
- In Quick mode the summary reports the context metrics as not measured ("Quick mode: faithfulness and context recall run only in Full mode") (`metrics.summarise` L89-91).

**All "not measured" reasons in the code:**
- latency: "not recorded".
- cost: usage not recorded, or a missing price or token count.
- completeness: "no questions found in the topic" / "the judge returned no verdicts".
- exact match: no facts made yet, the reference has none, no tags, no Standard-tagged facts, or no verdicts.
- citations: no citations, or none checkable.
- faithfulness: no claims; read not recorded; page version gone; rebuild failed.
- context recall: no key points; no verdicts; none tagged Standard.
- summary: "the answer checks have not been run on this run's answers".
- `run.main` L405-411: a failed checks or context call leaves those metrics not measured.

`metrics.summarise` gives the mean, sd and n per system over all answers. `cost_usd` uses 4 digits and everything else 2. `not_measured_in` is a count of distinct reasons, not of answers. `VERSION="kept-1"`.

---

### 8.7 Confidence intervals on the gaps (`gaps.py`)

- `LOWER_IS_BETTER = {"latency_s","cost_usd"}`.
- `JUDGED = ("similarity","coverage","coverage_standard","coverage_std_supp")`.
- `RESAMPLES = 10_000`.

**Per-topic values (`_topic_values`):**
- JUDGED values come from graded runs only.
- Measured per-answer metrics come from all runs.
- Each system's mean over its repetitions gives one diff per topic, **wiki − rag**, used only when both systems have a value.

**Wins:** for each graded run with a winner, the wiki score is +1 for a wiki win, −1 for a RAG win, 0 for a tie, and the RAG score is always 0. The topic diff is therefore the mean wiki score.

**Interval and verdict:**
- `rng = random.Random(f"{seed}-{k}")` (seed is config.seed, default 42).
- Each resample takes `choices(diffs, k=len(diffs))` and records its mean; the means are sorted.
- `lo = means[int(0.025*10000)] = means[250]`; `hi = means[int(0.975*10000)-1] = means[9749]`.
- Leader: if lo > 0, wiki (or rag if lower is better). If hi < 0, rag (or wiki if lower is better). Otherwise None.
- Verdict: "Wiki better", "RAG better" or "no clear difference". Fewer than 2 topics gives `ci: None`, "too few topics for an interval".
- Output per metric: `{diff (4 dp), n_topics, better: "lower"|"higher", ci: [lo, hi], leader, verdict}`.

---

### 8.8 Summary and the stored results JSON

**aggregate (`run.py` L266-301):**
- Per topic with graded runs, `rec.aggregate` holds:
  - `{rag|wiki: {similarity, coverage, coverage_standard, coverage_std_supp: {mean, sd, n}}}`;
  - `wins {rag, wiki, tie}`;
  - `key_point_hit_rate {Kid: {rag, wiki}}`.
- `_mean_sd` uses the sample stdev and gives sd = 0.0 for n = 1.
- `summary`:
  - `topics_scored`;
  - `by_system {name: {4 judged metrics: mean_sd over topic means}}`;
  - `wins_by_run`;
  - `by_section_similarity {section: {rag, wiki}}` (the mean of the topic similarity means);
  - `gaps`.

**Shape:**
```
results = {
  config: {started, git_commit (RENDER_GIT_COMMIT[:7] or git rev-parse --short), judge_model, judge_effort,
           judge_backend ("Anthropic API" | "Claude Code on a Claude subscription (claude -p)"),
           answer_checks {model, version}, context_checks {model, version}|null, runs, seed, topics_selected,
           expected_judgements (= topics*runs), question_format, rag_collection, wiki_slug, sources, use_saved_answers,
           mode, grading (text), capture: "read+usage v1", systems {rag{url,collection,documents[{filename,chunks}]}, wiki{url,wiki{...}}},
           query_set, reference (file name), reference_sha256, rubric_used {n: rubric-info}, finished},
  topics: {"<n>": {number, code, title, section, question, reference_label, reference, key_points[{id,point,kind}],
           key_points_usage, facts, rubric {built_in, saved_at, version, approved, facts_approved},
           runs: {"<r>": before grading {answers{rag,wiki}, judgement:false}
                         after: {blind_labels, systems{rag|wiki: {answer, sources, saved_answers_read?, read?, usage?, latency_s,
                                 grades, grades_by_order, point_weight, similarity, coverage, coverage_standard, coverage_std_supp,
                                 contradictions, metrics{latency_s,cost_usd,completeness,exact_match,exact_match_standard,
                                 citation_accuracy,[faithfulness,context_recall,context_recall_standard]}, checks{...}, context_checks{...}}},
                                 winner, winners_by_order, rationale, point_notes, orders{"1","2"}, orders_graded, judge_model,
                                 judge_usage{input_tokens,output_tokens}, judge_batch, judge_backend, judgement:true}},
           aggregate {...}}},
  grading_batch? {id, custom_ids}   (only while a batch is pending),
  metrics: {version:"kept-1", mode, by_system{name:{metric:{mean,sd,n,status,...}}}},
  errors: {topic_number: "Type: msg"},
  summary: {topics_scored, by_system, wins_by_run, by_section_similarity, gaps}
}
```
Sources: `run.py` L98-101, 137, 194-202, 371-389, 397, 413-415; `metrics.compute` L105; `checks.score` L307-309; `context.score` L97-99.

**Imported runs:** the status comes from `config.finished`, without the inputs, so they cannot be resumed (`import_results.py`).

---

### 8.9 Named evaluation frameworks

**None is used.**
- requirements.txt lists only anthropic, httpx, pydantic-settings, python-docx and psycopg.
- Every import in bench/*.py is stdlib, those packages, or a local module.
- A repo-wide grep (excluding .venv) for ragas, deepeval, trulens, RGB, langchain and llama_index finds nothing except `font.color.rgb` in `UI/server/app/rubric_export.py`, which is python-docx colour code.
- The .venv has no such packages.
- "Faithfulness" and "context recall" share names with RAGAS-style metrics but are written from scratch as single Claude calls (`context.py`).

---

## 9. UI

The Workbench is an Angular single-page app served by a FastAPI "backend for frontend" (BFF) that also proxies the RAG and Wiki APIs and hosts the benchmark endpoints.

### 9.1 UI server: serving, auth and proxy

#### Entry point and port
- `UI/server/run.py:6-11`: argparse `--host` (default `127.0.0.1`) and `--port` (default `8080`), then `uvicorn.run("app.main:app", ...)`.
- `UI/server/app/main.py:21`: `FastAPI(title="Workbench BFF", version="0.1.0", lifespan=lifespan)`. The lifespan calls `get_settings()` at startup and `proxy.close()` at shutdown (`main.py:14-18`).
- Middleware is `auth.AuthMiddleware` (`main.py:22`). Routers are added in this order: auth, then `/api/status` and `/healthz` (defined inline), then bulk, bench, ask, and the generic proxy last. A comment says "specific /api routers before the generic /api/{service}/... proxy" (`main.py:60-64`).
- In the container, uvicorn runs on `${PORT:-10000}` with `--proxy-headers --forwarded-allow-ips='*'` (`UI/Dockerfile:22-24`).
- Python dependencies (`UI/server/requirements.txt`): fastapi==0.142.4, httpx==0.28.1, pydantic-settings==2.15.0, python-multipart==0.0.32, uvicorn[standard]==0.54.0, psycopg[binary]==3.3.6, python-docx==1.2.0.

#### Serving the Angular build
- `main.py:76-89` `spa()` is a catch-all `GET /{path:path}`:
  - Paths starting with `api/` or `view` return 404.
  - Otherwise the file is resolved under `settings.web_dist`. It is served only if it is a file inside dist; this is a path-traversal guard via `dist.resolve() in file.parents`.
  - Any other path falls back to `index.html` with `Cache-Control: no-cache`. A comment says this is so the browser always gets the current build's hashed file names.
  - If `index.html` is missing, the server returns 404 "UI not built. Run `npm run build` in UI/web, or use `npm start` (dev server on :4200)."
  - Static files get no explicit cache header (plain `FileResponse`). The build uses `outputHashing: "all"` (`UI/web/angular.json:72`).
- `main.py:67-73` `wiki_viewer()`: `GET /view` and `GET /view/{path}` proxy to `{WIKI_URL}/view/{path}` with the query params and **no API key header**. Body, status and content-type are returned as received. The docstring says this is "so it works through the tunnel too".

#### `GET /api/status` (`main.py:26-51`)
- Runs five checks concurrently, each with a 5 s timeout and the `X-API-Key` header: RAG `/health`, RAG `/documents`, RAG `/collections`, Wiki `/health`, Wiki `/wikis`.
- Returns:
  - `rag: {ok, url, documents[], collections[]}`
  - `wiki: {ok, url, wikis[]}`
  - `benchmark: {ok: db_ok() and bench_python_path().exists(), runs: len(list_runs()), latest: runs[0] or None}`
- An exception in a check returns `{"ok": False, "error": <ExceptionTypeName>}`.

#### `GET /healthz` (`main.py:54-57`)
- Returns `{"status":"ok"}`. It is open (not under `/api`) and is the Render health check.

#### Auth (`UI/server/app/auth.py`)
- Enabled only when `UI_PASSWORD` is non-empty (`auth.py:24-25`).
- Cookie name is `COOKIE = "wb_session"` (`auth.py:19`). `MAX_AGE = 7 * 24 * 3600` = 604800 s, i.e. 7 days (`auth.py:20`).
- Signing key: `sha256(f"wb:{ui_password}:{session_secret}")` (`auth.py:28-31`). A comment says changing UI_PASSWORD logs everyone out.
- Token format is `"{expires}.{hmac_sha256_hex(key, str(expires))}"` (`auth.py:34-36`). Validation checks the digits, rejects expired tokens and uses `hmac.compare_digest` against a re-signed token (`auth.py:39-45`).
- `OPEN_PATHS = ("/api/auth/",)` (`auth.py:21`).
- Protected paths: `path.startswith("/api/")` and not under `/api/auth/`, OR `path.startswith("/view")`. Unauthenticated requests get `401 {"detail":"Login required"}` (`auth.py:75-81`).
- Not protected: the SPA static files, `/healthz`, and FastAPI's default `/docs` and `/openapi.json`. [UNVERIFIED that /docs is reachable: FastAPI registers it by default and the middleware only guards /api and /view. Note that the proxy, SPA and viewer routes use `include_in_schema=False`.]
- Endpoints (prefix `/api/auth`):
  - `GET /session` returns `{auth_required, authenticated}` (`auth.py:52-54`).
  - `POST /login` takes `{password}`.
    - Without a password set it returns `{ok:true}`.
    - The password is compared with `secrets.compare_digest`. A wrong password sleeps 1.5 s, then returns 401 "Wrong password".
    - The cookie is set with max_age=MAX_AGE, httponly, samesite="lax", and `secure` when `x-forwarded-proto` (or the URL scheme) is https (`auth.py:57-66`).
  - `POST /logout` deletes the cookie (`auth.py:69-72`).

#### Proxy (`UI/server/app/proxy.py`)
- Shared client: `httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10))`, i.e. 600 s read/write and 10 s connect (`proxy.py:15-19`).
- `target("rag")` → (`rag_url`, `rag_api_key`); `target("wiki")` → (`wiki_url`, `wiki_api_key`); anything else → 404 "Unknown service" (`proxy.py:27-33`).
- Route: `/api/{service}/{path:path}`, methods GET/POST/PUT/PATCH/DELETE (`proxy.py:36`).
  - Sends `X-API-Key` and forwards only the `content-type` and `accept` headers from the browser. It forwards the query params and raw body (`proxy.py:38-46`).
  - Streams with `send(stream=True)`. On `ConnectError` it returns 502 "{service} API is not reachable at {base}" (`proxy.py:47-50`).
  - The response streams back unchanged (`aiter_raw`). Only `PASS_HEADERS = ("content-type","content-disposition","cache-control")` are passed back (`proxy.py:12, 51-57`). This works for JSON, SSE and file downloads.
- The browser never sees the API keys (module docstring, `proxy.py:1`).

### 9.2 UI-server endpoints

#### Bulk (`UI/server/app/bulk.py`, prefix `/api/bulk`)
Runs are held in memory (`_runs: dict`, `bulk.py:13`). A restart loses them.

- **`POST /api/bulk`** (202). Multipart: optional `file`, required `collection`, `topics` (default `""`), `revise` (default True) (`bulk.py:33-54`).
  - With no file it uses `DEFAULT_QUERY_SET`. If that file is missing: 400 "No default query set on this server: upload a query-set file".
  - Topics are parsed from `'1,3,5-7'`.
  - The run id is `uuid4().hex[:12]`.
  - It creates the background task `_execute`, which POSTs `{RAG_URL}/collections/{collection}/bulk?revise=..&topics=..` with the multipart file, the X-API-Key header and `timeout=3600` (`bulk.py:17-30`).
  - The run is marked `succeeded` with the result JSON, or `failed` with `"{Type}: {e}"`, and `finished` is stamped.
  - Returns `{id}`.
- **`GET /api/bulk`**: every run without its `result`, newest `started` first (`bulk.py:57-59`).
- **`GET /api/bulk/{run_id}`**: the full run. 404 "Bulk run not found (runs are kept in memory until the UI server restarts)" (`bulk.py:62-66`).

#### Ask chats (`UI/server/app/ask.py`, prefix `/api/ask`)
- Storage is Postgres `ask.chats` and `ask.messages`. The tables are created by `Benchmark/migrations/0006_ask_chats.sql`:
  - `ask.chats`: `id uuid default gen_random_uuid()`, `title`, `created_at`, `updated_at`.
  - `ask.messages`: `id bigserial`, `chat_id` FK with on delete cascade, `seq`, `question`, `searched`, `mode` check in (rag, wiki, both), `sources` check in (standard, all), `rag_collection`, `wiki_slug`, `rag jsonb`, `wiki jsonb`, `created_at`, `unique(chat_id, seq)`.
- Each DB call opens a new psycopg connection (autocommit, dict_row) in a thread (`ask.py:27-34`).
- **`GET /chats`**: id, title, created_at, updated_at and `count(m.id) as messages`, ordered by updated_at desc (`ask.py:48-54`).
- **`POST /chats`** (201): body `{title=""}`, truncated to 120 characters. Returns the row (`ask.py:57-59`).
- **`GET /chats/{id}`**: the chat plus `messages` ordered by seq. 404 "Chat not found" (`ask.py:62-66`).
- **`PATCH /chats/{id}`**: rename. The title is stripped and capped at 120 characters (`ask.py:69-72`).
- **`DELETE /chats/{id}`** (204): deletes the chat and its messages only. The docstring says synthesis pages made from it stay in the wiki (`ask.py:75-79`).
- **`POST /chats/{id}/rewrite`**: body `{question (min 1), before_seq?}` (`ask.py:102-118`).
  - Loads the `searched` values of the last N earlier messages, N = `ask_history_questions` (6), before `before_seq` if given.
  - With no earlier questions it returns `{searched: q, rewritten: false, earlier: []}`.
  - Otherwise it calls Gemini `v1beta/models/{gemini_model}:generateContent` with the header `x-goog-api-key` (`ask.py:87-99`): system prompt `REWRITE_SYSTEM` (`ask.py:20-23`), JSON schema `{question}`, `temperature 0`, `timeout=60`.
  - On error it returns the question unchanged with `error: "Could not rewrite the follow-up: ..."`.
  - Returns `{searched, rewritten: out != q, earlier}`.
  - Only the questions are used, never the answers (module docstring `ask.py:1-3`).
- **`POST /chats/{id}/messages`** (201): `MessageIn{question, searched, mode, sources, rag_collection?, wiki_slug?, rag?: Side, wiki?: Side, seq?}`, where `Side = {answer, sources[], pages[], ms?, error}` (`ask.py:121-160`).
  - Stores the rag/wiki JSON only if the mode includes that side.
  - With `seq`: UPDATEs that message (asked again) and resets `created_at=now()`. 404 "Message not found".
  - Otherwise: INSERTs with `seq = max+1`.
  - A chat without a title gets `" ".join(question.split())[:80]`. `updated_at` is bumped.
- Note: the answers themselves are produced in the browser via the proxy. The server only rewrites and stores them.

#### Benchmark (`UI/server/app/bench.py`, prefix `/api/bench`)
- Constants:
  - `STALE = timedelta(minutes=2)`. Comment: bench.run heartbeats every 30 s (`bench.py:25`).
  - `MAX_UPLOAD = 20*1024*1024` (`bench.py:26`).
  - `DONE_SQL` counts runs whose `judgement` is true across `results.topics[*].runs[*]` (`bench.py:29-30`).
- Subprocesses go in `_procs: dict[str, Popen]` (`bench.py:24`).
  - `_spawn` runs `[bench_python, "-m", *(args or ["bench.run","--run-id",id])]` with `cwd=bench_dir`.
  - Its env is `os.environ` plus `PYTHONIOENCODING=utf-8`, `DATABASE_URL`, `RAG_URL`, `RAG_API_KEY`, `WIKI_URL` and `WIKI_API_KEY` (`bench.py:217-224`).
  - The `_procs` key is the run id, `rubric-{sha}`, `suggest-{sha}` or `facts-{sha}`.
  - `_ensure_idle()`: if ANY tracked process is alive, 409 "A benchmark run or rubric rebuild is already in progress" (`bench.py:212-214`). So only one benchmark/rubric/suggest/facts job runs per server process.
- `_status(row)` (`bench.py:125-133`):
  - A live local process means "running".
  - A DB status of running/queued means "interrupted" if the local process died, or if `now - updated_at > 2 min`. Otherwise "running" (it may be running elsewhere, e.g. the CLI).
  - Otherwise the DB status.
- `_progress` returns `{done, expected: config.expected_judgements, status, errors}` (`bench.py:136-137`).

**Memo-label masking** (`bench.py:43-114`)
- `_ref_cache` with `REF_TTL = timedelta(minutes=15)`. A comment says it is "cleared on rename, new ticks and new runs" (`bench.py:45-46`).
- `_labels()` first inserts into `bench.references` any memo SHA-256 (`encode(sha256(reference),'hex')` over `bench.runs`) not yet labelled. The label is `'Reference memo ' || (count + row_number() over (order by first_seen))`. It then returns sha → {label, tag_sources} (`bench.py:53-68`).
- `_masks()` collects every `reference_name` the memo was uploaded or saved under (in bench.runs and bench.rubrics), with and without `.docx`, keeping only names of 4 or more characters. The pairs are sorted longest-first and map to that memo's label, or "Reference memo" if none (`bench.py:71-89`).
- `_run_shas()` maps run id → memo SHA, cached (`bench.py:92-100`).
- `_mask(obj, pairs)` recursively replaces every name with its label in strings, dicts and lists (`bench.py:103-114`).
- Masking is applied to:
  - `config` and `errors` in the runs list (`bench.py:151, 159`)
  - `config`, `errors` and `summary` in run detail (`bench.py:195-197`)
  - the last 15 log lines and errors in run status (`bench.py:209`)
- Rubrics, topics and the export show the label, never the file name (`bench.py:425, 450, 256`).
- [UNVERIFIED] `get_run` does not mask `results.topics` (`bench.py:195` masks only config/errors/summary). The topics carry `reference_label` and the reference text (Benchmark/bench/run.py:100). Whether those strings could contain a memo file name is not checked by this code.

**Endpoints**
- **`GET /runs`** (`bench.py:140-162`). Per run:
  - `id`, `started` and `finished` (from config), `runs`, `judge_model`
  - `topics` = count of `config.topics_selected`, or the topics spec, or "all"
  - `query_set` name, `reference` (label), `reference_sha256`, `rag_collection`, `wiki`, `sources`, `use_saved`, `mode`, `use_batch`
  - `summary`, `progress`
  - `rubric` (from `_rubric_label`): label `v{n}` or `v{a}–v{b}`, title "X of Y topics approved when the run used them", or "—" / "Run made before rubric versions were recorded" (`bench.py:165-173`)
  - `judge` (from `_judge_label`): `"{judge_model} · subscription|API"`. A missing backend defaults to "Anthropic API" (`bench.py:176-179`)
  - Ordered by created_at desc.
- **`GET /runs/{id}`** (`bench.py:189-202`): the whole `results` JSON (with masked config/errors/summary) plus `reference_label`, `progress`, and `compared: {rag_collection, wiki, sources, use_saved}` from the run row.
- **`GET /runs/{id}/status`** (`bench.py:205-209`): progress plus the masked last 15 log lines.
- **`GET /topics`** (`bench.py:238-257`):
  - Takes the most recent run that has both a query_set and a reference.
  - Writes them to a temp dir and runs a subprocess with `bench.data.load` (timeout 120 s) to list `{number, code, title, section}`.
  - Returns `{topics, query_set, reference: label}`. With no inputs: `{topics: [], query_set: null}`.
  - A subprocess failure returns 500 "Could not read the query set: …".
- **`GET /judge`** (`bench.py:286-290`): `{backend: "api"|"claude-code", label: "Anthropic API" | "Claude subscription (Claude Code)", batch_available: backend=="api"}`.
  - `_judge_backend()` reads the env var `JUDGE_BACKEND`, else the `JUDGE_BACKEND=` line in `Benchmark/.env`. "claude-code" gives claude-code; anything else gives "api" (`bench.py:272-283`).
- **`GET /estimate?topics&runs=2&mode=quick&use_batch=true&collection&wiki`** (`bench.py:296-409`):
  - Prices come from `Benchmark/bench/prices.json` (`bench.py:229-230`). The topics come from `/topics`.
  - It looks at the last 20 runs that have results and gathers four pools of recorded usage:
    - answer costs, via `_answer_cost`, which skips `embed` steps and returns None if a model price or the tokens are missing (`bench.py:260-269`). These are split into "same collection/wiki" and "other".
    - judge usage, excluding batch gradings
    - key-point usage
    - answer-check usage, excluding batch and claude-code checks
  - Line items:
    - RAG answers and Wiki answers: `n*runs`, mean of same, else other.
    - "Grading, both orders": `n*runs*2`, with `jm = prices["claude-opus-5-5"]` and `batch_discount` when batching. On the subscription it is 0 with the basis `SUBSCRIPTION` ("on your Claude subscription: no API charge, counts toward the plan's usage limits", `bench.py:293`).
    - "Key points for topics without a saved rubric" (missing rubric topics), or "Key points" 0 with "the saved rubric is reused".
    - "Answer checks: completeness, exact match, citation accuracy (Claude Sonnet 5.5, one call per answer)": `n*runs*2`.
    - Full mode adds "Faithfulness + context recall, RAG/Wiki answers": `n*runs`, with `prices["claude-sonnet-5-5"]`. Input is taken as the mean answer-call context tokens; output as half a recorded grading's output.
  - Items with no basis get `total_usd: null` and a basis such as "no answer with recorded tokens yet: cannot estimate until a run has recorded some". Nothing is guessed (docstring).
  - Returns `{topics, runs, mode, use_batch, items, judge_backend, total_usd (rounded 2), complete, not_estimated[], note}`.
- **`GET /rubrics`** (`bench.py:412-430`): per reference SHA:
  - topics, key_points total, `standard` count, `approved` (count reviewed_at), `facts_approved`, `facts_made`, built (min created_at), updated (max)
  - plus `reference_name` (label), `rebuilding`, `making_facts`, `suggesting`
- **`GET /rubrics/{sha}`** (`bench.py:441-452`):
  - Every topic row: topic_number, topic_title, key_points, facts, version, reviewed_at, facts_reviewed_at, created_at, suggestions, tag_sources.
  - Plus reference_name/label and the memo's `tag_sources`.
  - Plus `documents` (from `_documents()`, which reads `wiki.sources` straight from the DB). Names are built by regex `(IFRS|IAS|IFRIC|SIC)\s*(\d+)` plus ` Part A/B/C` from `BB\d{4}-([ABC])` in the PDF title. Tier is `supporting` if parser==`ifrs_accompanying`, `standard` if `ifrs`, else `other` (`bench.py:460-475`).
  - Plus `tags`, `making_facts`, `suggesting`. 404 if there is no rubric.
- **`PUT /references/{sha}`** (`bench.py:483-502`): body `{label? (1–80 chars), tag_sources?: slug[]}`.
  - 404 "Unknown reference memo".
  - `tag_sources` must be non-empty and known: 422 "Tick at least one existing source document" or "Unknown document(s): …".
  - A label already used by another memo gives 409.
  - Saves to `bench.references` (tag_sources sorted), clears the cache, and returns the label row.
- **`POST /rubrics/{sha}/suggest`** (202): body `{topics: "" }`. Spawns `bench.suggest <sha> [topics]` (`bench.py:509-516`).
- **`POST /rubrics/{sha}/facts`** (202): 409 if every topic already has a fact list. Spawns `bench.checks facts <sha>` (`bench.py:519-525`).
- **`GET /rubrics/{sha}/export.docx?topic=0&tag=&unreviewed=false&suggestions=false`** (`bench.py:528-546`):
  - Filters topics and points as the screen does.
  - `ticked` = the names of the saved tag_sources, or all documents.
  - Calls `rubric_export.build`.
  - Filename `"Rubric - {label}{' - suggestions'}.docx"` (label, not file name), sent as an RFC 5987 `filename*` header.
- **`PUT /rubrics/{sha}/topics/{n}`** (`bench.py:549-621`): `TopicReview{key_points: KeyPoint[] (min 1), facts?: Fact[], approve_points, approve_facts, decisions: {"point:K1"|"merge:0"|"facts": accepted|rejected}}`.
  - KeyPoint: `id` 1–12 characters, `point`, `kind`, `ref?`. Fact is the same with `kind?`.
  - Tags must be in `TAGS = ("standard","supporting","beyond_standard")` (422). Ids must be unique (422).
  - Decisions are written into `suggestions[...].status`.
  - Acting on suggestions copies `suggestions.documents` into `tag_sources`.
  - `version = version + 1` if the points, facts or tag_sources changed.
  - `reviewed_at`/`facts_reviewed_at` are set to now() on approve, or nulled when the content changed without approval.
  - Upserts `bench.rubric_versions` (note "reviewed").
- **`POST /rubrics/{sha}/rebuild`** (202): spawns `bench.rubric rebuild <sha>` (`bench.py:624-630`).
- **`POST /runs`** (202), multipart (`bench.py:691-730`):
  - Fields: `reference` (.docx, optional), `query_set` (.txt, optional), `topics` (""), `runs` (2, ge 1, le 10), `collection` (required), `wiki` (required), `sources` (standard|all, required), `use_saved` (True), `mode` (quick|full, default quick), `use_batch` (True).
  - Flow:
    1. `_ensure_idle`.
    2. `use_batch` is forced false unless the backend is api.
    3. `_ensure_collection` checks the RAG collection exists and has documents (15 s timeout). Errors: 400 "No RAG collection…" or "…has no documents".
    4. `_ensure_wiki` returns 400 "No wiki with slug" when the wiki does not exist.
    5. `_read` checks the extension and size: 400 "empty or larger than 20 MB".
    6. Files not uploaded are reused from the last run. If either is still missing: 400 "Upload the reference assessment (.docx) and the query set (.txt) for the first run".
    7. Full mode calls `_ensure_approved`: every chosen topic needs approved key points, a non-null facts list and approved facts. Otherwise 400 with guidance (`bench.py:677-688`).
  - The run id is `YYYYMMDD-HHMMSS`. The row is inserted into bench.runs together with the file bytes, the cache is cleared, and the run is spawned.
- **`POST /runs/{id}/resume`** (202): 400 if the run has no stored inputs (imported runs). 409 if it is still running. Re-spawns the same run id (`bench.py:733-742`).
- **`DELETE /runs/{id}`** (204): 409 if running. Otherwise it deletes the row (`bench.py:745-750`).

#### Rubric Word export (`UI/server/app/rubric_export.py`)
- `TAG_LABEL`: Standard (Part A), Supporting (Part B/C), Beyond standard (`:15`).
- Calibri 10 pt. Landscape 29.7×21 cm when suggestions are included. Margins 2 cm (`:138-144`).
- Header: "Rubric review [with suggested changes]", the reference label, the SHA-256 fingerprint, the export time, "N of M topics' key points approved · K fact lists approved", the documents ticked, and the filters (`:145-162`).
- Per topic:
  - The version and "tags checked against" line.
  - A key-points table: ID / Key point / Tag, widths 1.3/12.2/3.5 cm.
  - With suggestions, a 6-column table: ID, Key point, Current tag, Suggested tag (with "(same)", "CHECK", second look, [status]), Paragraph (document), Reason.
  - The exact-match facts as bullets.
  - With suggestions: the suggested merges and the suggested hard-fact list, including the dropped items (`:164-220`).
- A backing paragraph is never shown for Beyond standard (`_ref`, `:38-40`).

---

### 9.3 Angular app: routes, navigation and every page

#### Versions (`UI/web/package.json`; installed versions from `package-lock.json`, lockfileVersion 3)

| Package | Range | Installed |
|---|---|---|
| @angular/core, common, compiler, forms, platform-browser, router, compiler-cli | ^22.2.0 | 22.2.1 |
| @angular/material, @angular/cdk | ^22.2.2 | 22.2.2 |
| @angular/build, @angular/cli | ^22.2.2 | 22.2.2 |
| typescript | ~6.0.2 | 6.0.3 |
| rxjs | ~7.8.0 | 7.8.2 |
| tslib | ^2.3.0 | 2.8.1 |
| marked | ^18.1.0 | 18.1.0 |
| dompurify | ^3.4.16 | 3.4.16 |
| cytoscape | ^3.34.3 | 3.34.3 |
| prettier | ^3.8.1 | (dev) |

- `packageManager: npm@11.19.0`. No `engines` field in package.json. @angular/core requires node `^22.22.3 || ^24.15.0 || >=26.0.0` (lockfile, core entry). The Docker build uses `node:24-slim`.
- **Zoneless.** zone.js is not a dependency; it appears only as an optional peer of @angular/core in the lockfile. `app.config.ts` has no `provideZoneChangeDetection`, so the app runs zoneless, the Angular default in recent versions. State is held in signals throughout.
- Bootstrap is `bootstrapApplication(App, appConfig)` (`src/main.ts`). Components are standalone.
- Providers (`app.config.ts`):
  - `provideBrowserGlobalErrorListeners()`
  - `provideHttpClient(withFetch(), withInterceptors([authInterceptor]))`
  - `provideRouter(routes, withComponentInputBinding(), withRouterConfig({paramsInheritanceStrategy:'always'}), withNavigationErrorHandler(...))`. The error handler reloads `location.assign(e.url)` on "dynamically imported module|Loading chunk|Importing a module script failed", so a stale tab loads the new build.
- Build (`angular.json`):
  - builder `@angular/build:application`, browser `src/main.ts`, scss, assets from `public/`
  - production budgets: initial warning 1.5MB / error 3MB; anyComponentStyle 4kB / 8kB; outputHashing all
  - development: no optimisation, source maps
  - serve uses `proxyConfig: proxy.conf.json`
- `proxy.conf.json`: `/api` and `/view` → `http://127.0.0.1:8080` (secure false, changeOrigin).
- `tsconfig.json`: ES2022, module preserve, strictInjectionParameters, strictInputAccessModifiers. `tsconfig.spec.json` references `vitest/globals`, but vitest is not in devDependencies and there are no `*.spec.ts` files. So no tests exist.
- `.vscode`: extension `angular.ng-template`. Launch configs "ng serve" (localhost:4200) and "ng test" (9876/debug.html). Tasks for npm start and test.
- `index.html`: title "IFRS Workbench". Loads Roboto and Material Symbols Outlined from Google Fonts. Body class `mat-typography`.
- `styles.scss`: `mat.theme` with azure primary, blue tertiary, Roboto, density -1, color-scheme light dark. Shared classes: page, card, cards, pill (ok/warn/bad), simple table, .md (markdown, cite chips, missing wiki links), .diff.

#### Shell and navigation (`app.ts`)
- If `auth.authenticated() === false`, it shows `<app-login>`. Otherwise it shows a sidenav (220 px), an end-side "over" drawer `<app-citation-panel>` (width `min(560px, 92vw)`) opened while `CitationService.target()` is set, and the router outlet.
- Nav items (`app.ts:48-55`): Home `/` (home), Ask (side by side) `/ask` (forum), RAG documents `/documents` (description), Bulk requirements `/bulk` (playlist_add_check), Wiki `/wiki` (menu_book), Benchmark `/benchmark` (leaderboard).

#### Routes (`app.routes.ts`), all lazily loaded

| Path | Component | Title |
|---|---|---|
| `''` | pages/home `Home` | Workbench |
| `ask` | pages/ask `Ask` | Ask |
| `documents` | `Documents` | RAG documents |
| `bulk` | `Bulk` | Bulk requirements |
| `wiki` | wiki/wiki-select `WikiSelect` | Wiki |
| `wiki/:w` | wiki/wiki-layout `WikiLayout`, with children: `''`→redirect `pages`; `pages` WikiPages; `pages/:slug` WikiPage; `sources` WikiSources; `jobs` WikiJobs; `changesets` WikiChangesets; `changesets/:id` WikiChangeset; `lint` WikiLint; `graph` WikiGraph; `settings` WikiSettings | – |
| `benchmark` | benchmark/runs `BenchRuns` | Benchmark |
| `benchmark/rubric` | `BenchRubric` | Rubric review |
| `benchmark/compare` | `BenchCompare` (query params a, b bound as inputs) | – |
| `benchmark/:id` | `BenchRun` | – |
| `benchmark/:id/topic/:n` | `BenchTopic` | – |
| `**` | redirect `''` | |

#### Core services
- `core/api.ts`:
  - `Api` wraps HttpClient with Promises (get, text, post, put, patch, delete, upload). `upload` sends multipart `file` plus extra fields.
  - `openFile(url)` opens the tab first, then sets it to the returned signed `{url}`, so popup blockers allow it.
  - RAG helpers: ragCollections, ragDocuments, ragChunks(`para_ref`, `collection`). Wiki helpers: wikis, wiki, pages, page, job.
  - `toParams` skips undefined, null and ''.
  - `errMsg` extracts `detail` (string, `.message` with source/document_id, or a validation array).
- `core/auth.ts`:
  - `AuthService.authenticated` signal (null = checking). It calls `GET /api/auth/session` on construction; if the server is unreachable it assumes authenticated.
  - `login` POSTs `/api/auth/login`. `logout` POSTs `/api/auth/logout`. Note: no logout button exists in the UI.
  - `authInterceptor`: any 401 dispatches the `wb-unauthorized` window event, which shows the login screen.
- `core/collections.ts`: `RagCollections`, the RAG collection list plus the current one. It is remembered in `localStorage` key `rag-collection` (wrapped in try/catch) and shared by Documents, Ask, Bulk and the citation panel. `refresh()` keeps the current one if it still exists, else picks the first.
- `core/sse.ts` `postSse(url, body, signal)`:
  - A fetch POST with `Accept: text/event-stream`. A 401 triggers the unauthorized event. A non-ok response throws `detail`.
  - Reads with `TextDecoderStream`, normalises CRLF, splits on blank lines, and parses `event:` and `data:` lines.
  - Yields `{event, data}` (default event "message").

#### Pages

**Home** (`pages/home.ts`)
- Calls `GET /api/status` once.
- Cards:
  1. **RAG**. Green or red dot from `rag.ok`. The stat is the sum of `documents[].chunks` from RAG `GET /documents`, plus "chunks in {documents.length} document(s), {collections.length} collection(s)". Links to Documents and Bulk run.
  2. **Wiki**. Dot from `wiki.ok`. The stat is the sum of `wikis[].pages` from Wiki `GET /wikis`, plus "pages in N wiki(s)". There is one button per wiki, or "Create a wiki".
  3. **Benchmark**. Dot from `benchmark.ok` (DB reachable and bench python exists). Shows `latest.summary.by_system.rag.similarity.mean` vs `...wiki.similarity.mean`, "RAG vs Wiki similarity /10 (latest of {runs} runs)". `latest` is the newest run by created_at; if it has no summary yet (e.g. still running), the card shows "No completed runs yet." even when older finished runs exist.
  4. **Ask**: link only.
- A "Service down: RAG (url) / Wiki (url)… Start it with its run.py." message appears when either is down.

**Ask** (`pages/ask.ts`)
- Left column: chats.
  - `GET /api/ask/chats`, shown with title, `updated_at`, message count.
  - New chat.
  - Rename inline: `PATCH`.
  - Delete with inline confirm, "Delete this chat? Synthesis pages made from it stay in the wiki.": `DELETE`.
  - `/ask?chat=<id>` reopens a chat. The id is kept in the URL with `replaceUrl`.
- Controls:
  - Mode toggle: RAG only / Wiki only / Both. Default `both`.
  - Collection select (if not wiki-only), using RagCollections.
  - Wiki select (if not rag-only). The default is the first wiki.
  - Sources toggle: Standard only / All. Default `all`.
  - Opening a chat restores the last message's mode, sources, wiki and collection.
- Ask flow (`ask()`, `ask.ts:376-402`):
  1. Create a chat if there is none: `POST /api/ask/chats`.
  2. `POST /api/ask/chats/{id}/rewrite {question}`.
  3. Append the message.
  4. `run()` streams in parallel, with body `{question: searched, sources}`:
     - RAG `POST /api/rag/collections/{c}/query/stream`: `token` events are appended (JSON-parsed); the `citations` event becomes the sources list.
     - Wiki `POST /api/wiki/wikis/{w}/query/stream`: `token` events, and the `pages` event becomes the pages list.
     - Each pane records its `ms`.
  5. Save with `POST /api/ask/chats/{id}/messages`, then reload the chats.
- Composer: Ctrl/Cmd+Enter submits. A Stop button aborts both streams; the pane error becomes "Stopped".
- "Searched for" is shown for each message. Edit, then "Search again", re-runs `askAgain` with `seq` and replaces the message's answers. Note: `askAgain` does not call `/rewrite`; it uses the edited text verbatim.
- A rewrite error is shown as a warning note on the message.
- RAG pane: rendered markdown with clickable `[para]` citations. Source chips (`para_ref ?? chunk_id`, snippet as the title) open the drawer.
- Wiki pane: markdown with `[[links]]` (titles from the pages read, cites off). "Pages read" chips are dimmed if not cited and dashed for saved answers, prefixed "Saved answer:".
- **Create synthesis** (`ask.ts:449-517`):
  - Enabled only when the chat has wiki answers that are finished, error-free and saved.
  - It uses the latest message's wiki; answers from other wikis are counted as "from another wiki left out".
  - Each answer is sent as `{searched, answer, sources, date}`.
  - `POST /api/wiki/wikis/{w}/synthesis/draft {chat_id, chat_title, answers}` returns a draft with slug, title, summary, content_md, exists/version and tags.
  - The draft card has Title and Summary fields, an Edit/Preview toggle and a textarea.
  - The citation problems list comes from `POST /api/wiki/wikis/{w}/synthesis/check {content_md, answers}`. There is a "Check again" button.
  - Save re-checks the text if it was edited. If there are problems, the first press only sets `confirm` and the button reads "Save anyway (N problem(s))". It then POSTs `/api/wiki/wikis/{w}/synthesis {slug,title,summary,tags,content_md,answers}`.
  - The result shows "Saved as <slug>" and, if `needs_checking`, a pill "needs checking: N citation problem(s)" (not read by Ask or the benchmark until saved clean).
  - Nothing is saved before Save.

**RAG documents** (`pages/documents.ts`)
- Collection select, showing "name (slug) · N doc(s)".
- New / Rename / Delete:
  - Create: `POST /api/rag/collections {name, slug}`. The slug is auto-made from the name with `slugify`, capped at 63 characters.
  - Rename: `PATCH /api/rag/collections/{c}`.
  - Delete: `DELETE /api/rag/collections/{c}`, after typing the slug to confirm.
- Ingest: file drop accepting `.pdf,.txt,.md`, then `POST /api/rag/collections/{c}/documents` (multipart `file`). The result shows filename, collection, parser, chunks, `by_source_type` pills and warnings.
- Document table: File, Parser, Chunks, Added. "View original" (if `has_file`) opens `GET /api/rag/documents/{id}/file`, which returns a signed URL. Delete with confirm: `DELETE /api/rag/documents/{id}`.

**Bulk requirements** (`pages/bulk.ts`)
- File drop accepting `.txt,.md` (optional; the label names the default query set). Collection select. Topics (default `'1'`). "Self-check revision pass" checkbox (default true).
- `POST /api/bulk`: multipart with the file, or a FormData of fields.
- Polls `GET /api/bulk/{id}` every 4000 ms while running. On load it opens the newest run from `GET /api/bulk`.
- Results accordion per topic: word_count / ~word_guide, an issues pill or "checks pass", the issue lines, "Copy markdown" (CDK Clipboard), the rendered `answer_markdown` (cites off), and "Cited paragraphs" chips that open the drawer.
- "Earlier runs (this session)" lists the in-memory runs.

**Wiki select** (`wiki/wiki-select.ts`)
- Cards per wiki: name, description, page and source counts.
- Create: `POST /api/wiki/wikis {slug, name, description}`, slug auto-made from the name. Then it navigates to `/wiki/{slug}/sources`.

**Wiki layout** (`wiki/wiki-layout.ts`)
- Header shows the wiki name (from `GET /api/wiki/wikis/{w}`) and a "Public viewer ↗" link to `/view/{w}` in a new tab.
- Tabs: Pages, Sources & ingest, Jobs, Changesets, Lint, Graph, Schema & export.

**Pages** (`wiki/pages.ts`)
- `GET /api/wiki/wikis/{w}/pages`. Text filter over title, slug and summary.
- Grouped by `TYPES = overview, topic, concept, entity, comparison, synthesis, source`. Note: a page of any other type is not shown.
- Pills for "saved answer" and "needs checking" (tooltip: why and paragraphs). Shows v{version} and updated time.

**Page view** (`wiki/page.ts`)
- Loads `GET .../pages/{slug}`, the pages list (to mark missing links) and `GET .../pages/{slug}/versions`.
- Header: type and tag pills, version, updated time.
- Saved-answer note.
- Needs-checking flags:
  - `citation_problems` lists the problems.
  - A `needs_checking` changed-paragraphs flag has "Mark as checked", which calls `DELETE .../pages/{slug}/needs-checking`.
- Markdown with `[[links]]` that navigate.
- Side cards: "Linked from" (backlinks), "Sources" (with kind), "History".
- Clicking a version calls `GET .../versions/{v}` and shows a client-side LCS unified diff from that version to current (`unifiedDiff`, `page.ts:146-162`). "Revert to v{n}" calls `POST .../pages/{slug}/revert/{v}`.
- A 404 shows "Page “slug” does not exist yet (lint with fix can create it)."

**Sources & ingest** (`wiki/sources.ts`)
- Mode toggle: "Review changes first" (`review`, default) / "Apply automatically" (`auto`). It is sent as the query `mode`.
- Tabs:
  - File (`.pdf,.docx,.md,.txt`): `POST .../sources` multipart.
  - URL: `POST .../sources/url {url}`.
  - Text: `POST .../sources/text {title, text}`. Text needs at least 20 characters.
- The result shows "Started ingest of <title> (N sections, mode)" with a link to Jobs, plus any warnings.
- Sources table (`GET .../sources`): title linking to its page, uri, kind, chars, added. View original: `GET .../sources/{slug}/file`. Delete raw source (pages are kept): `DELETE .../sources/{slug}`.

**Jobs** (`wiki/jobs.ts`)
- Polls `GET .../wikis/{w}/jobs` every 3000 ms while any job is running or queued.
- Columns: kind and params, status pill, and progress. Progress shows the stage, sections/pages/batches, failed sections, skipped pages, corrected citations, flagged citations, saved answers needing a check, and paragraphs not written up.
- "Show" on a succeeded job loads `GET /api/wiki/jobs/{id}` and displays:
  - a link to the pending changeset (review N change(s)), or the applied count and conflicts
  - page pills
  - the raw JSON result

**Changesets** (`wiki/changesets.ts`)
- Toggle Pending (default) / All. Calls `GET .../changesets?status=`.
- Table columns: summary, kind, ops, status, created.

**Changeset** (`wiki/changeset.ts`)
- `GET .../changesets/{id}`. Each op is an expansion panel:
  - create ops show the rendered markdown
  - other ops show `<app-diff>` of `o.diff`
  - a "stale: page now v{current}" pill when `base_version !== current_version`
- Buttons: Discard (`POST .../discard`) and Apply (`POST .../apply?force=false`).
- The outcome shows the applied count, conflicts and the removed source.
- Note: `apply(force)` exists, but the UI only ever passes `false`. Force-apply is not reachable from the UI.

**Lint** (`wiki/lint.ts`)
- Buttons:
  - "Structural check (instant)": `POST .../lint {}`.
  - "+ LLM health check": `{llm:true, fix:false, mode}`.
  - "LLM check + fix": `{llm:true, fix:true, mode}`.
- Mode toggle: "Fixes need review" (review, default) / "Apply fixes" (auto).
- The job result is polled with `GET /api/wiki/jobs/{id}` every 3000 ms.
- Summary cards: broken links, orphan pages, thin pages, unsourced pages, missing summary/tags, possible duplicates. Each has a detail list.
- LLM section: contradictions, stale claims, missing pages (the first 40 shown), questions, sources to find.
- Fix result: status and a link to its changeset.

**Graph** (`wiki/graph.ts`)
- `GET .../graph`, drawn with cytoscape.
- Colour by type (overview #1565c0, topic #6a1b9a, concept #2e7d32, entity #ef6c00, comparison #00838f, synthesis #ad1457, source #5d4037, missing #9e9e9e).
- Node size `10 + sqrt(inbound)*5`. Red ring (#d32f2f) marks orphans. Missing pages are translucent round-rectangles.
- Concentric layout by inbound links: levelWidth 3, minNodeSpacing 28, spacingFactor 1.1. Zoom 0.2–2. wheelSensitivity 0.3.
- "Show missing pages" checkbox. Tapping a node navigates to the page.

**Schema & export** (`wiki/settings.ts`)
- Schema: `GET .../schema` (text), shown as markdown. Edit in a textarea and save with `PUT .../schema {schema_md}`; the message says it "applies to future ingests, queries and lint runs".
- Export links: `/api/wiki/wikis/{w}/export.zip`, `index.md` and `log.md`. They are plain hrefs, so the cookie authenticates them.
- Delete wiki: type the slug, then `DELETE /api/wiki/wikis/{w}`, then navigate to `/wiki`.

**Benchmark runs** (`benchmark/runs.ts`)
- New run card:
  - Two file drops: "Reference assessment (.docx)" and "Query set (.txt)". Empty means reuse the last run's file.
  - RAG collection select (`GET /api/rag/collections`) "vs" Wiki select (`GET /api/wiki/wikis`). The defaults are the first of each.
  - Sources toggle (default `all`). "Use saved answers" checkbox (default true).
  - Mode Quick/Full (default quick). The tooltip says Full adds faithfulness and context recall, one Claude Sonnet 5.5 call per answer.
  - Judge: `GET /api/bench/judge`. If `batch_available===false` it shows "Judge: {label}" (subscription tooltip) and forces `useBatch=false`. Otherwise it shows the "Batch grading (half price)" checkbox (default true).
  - Topics text (default `'2'`). "Choose" opens the topic picker. Runs number input, min 1 max 10, default 2.
- Topic picker: `GET /api/bench/topics`. Checkboxes grouped by consecutive `section`, with All/None buttons. "Use these" compresses the choice to ranges like `1-3,5`; all topics gives an empty string.
- **Start…** calls `GET /api/bench/estimate?topics&runs&mode&use_batch&collection&wiki`.
  - It shows "Estimated cost: $X[ + items that cannot be estimated yet]", "topics × runs · mode · batch", and an item table (count ×, unit `1.4-4`, total `1.2-2` or "not estimated", basis) with the note.
  - **Start run** (the confirm step) POSTs the `/api/bench/runs` FormData. Cancel dismisses.
- Live progress: polls `GET /api/bench/runs/{id}/status` every 3000 ms (the first poll after 1500 ms). It shows a determinate bar `done/expected` ("? " while unknown) and the log tail (pre). On load it reattaches to any run whose status is `running`.
- Rubric card: polls `GET /api/bench/rubrics` every 5000 ms while any rubric is rebuilding.
  - Columns: Reference memo label with the SHA first 12 characters, topics, key points (N standard), reviewed (X of N key point lists, Y fact lists), built and updated.
  - "Review" links to `/benchmark/rubric?ref=<sha>`.
  - "Rebuild" asks to confirm (the text warns later runs are not directly comparable), then `POST /api/bench/rubrics/{sha}/rebuild`.
- Runs table columns:
  - select checkbox (keeps the last 2 ticked)
  - Run id with start time
  - Compared (collection vs wiki)
  - Sources pill, Saved answers On/Off/—
  - Topics × runs, Mode
  - Rubric label with "approved/topics" (tooltip from title), Judge label
  - RAG sim / cov %, Wiki sim / cov % (from `summary.by_system.*.similarity.mean` and `coverage.mean`)
  - Wins rag / wiki / tie (from `summary.wins_by_run`)
  - Status pill: finished ok; running warn; failed or interrupted bad
  - Actions: Resume (for interrupted, failed or queued) calls `POST .../resume`; Delete (when not running) asks `confirm()` then `DELETE`.
- "Compare selected" when exactly two runs are ticked: sorts the ids and navigates to `/benchmark/compare?a=&b=`.
- Note: the empty-state row uses `colspan="10"` but the table has 14 columns (cosmetic).

**Run page** (`benchmark/run.ts`)
- Calls `GET /api/bench/runs/{id}`.
- Header: compared collection vs wiki; Sources and Saved answers pills ("the same for both systems").
- Config line: judge model (effort, backend), runs per topic, RAG chunks (sum of `config.systems.rag.documents[].chunks`), Wiki pages, git commit.
- Rubric line (`rubricLabel`):
  - "built in this run (before rubrics were saved)", or
  - "saved rubric for {reference_label}, built in …", followed by either "· versions … · X of Y topics approved" or "· recorded before rubric review".
- **Scorecard**. Tests in `gapOrder` (`run.ts:164-165`), with these labels:

| Key | Label |
|---|---|
| similarity | Similarity (0–10) |
| coverage | Coverage |
| coverage_standard | Standard-only coverage |
| coverage_std_supp | Standard + Supporting coverage |
| wins | Wins (gap: share of answers) |
| completeness | Completeness |
| exact_match | Exact match |
| exact_match_standard | Standard-only exact match |
| citation_accuracy | Citation accuracy |
| faithfulness | Faithfulness |
| context_recall | Context recall |
| context_recall_standard | Standard-only context recall |
| latency_s | Latency (s, lower is better) |
| cost_usd | Cost per query (lower is better) |

  - Columns: RAG, Wiki, Wiki − RAG (`summary.gaps[k].diff`), 95% confidence interval (`gaps[k].ci`), Result (the `verdict` pill coloured by `leader`).
  - `score()` (`run.ts:174-189`) shows "Not run yet" with one of these reasons:
    - "the run has not finished" when there is no summary
    - "this run was made before this test was added"
    - "this run used Standard only (Part A), so Supporting points were not in play" for coverage_std_supp under standard sources
    - "no graded answers"
    - the metric's own `reason` or "not measured" when `status !== 'measured'`
  - Data sources:
    - The judged tests (similarity, the coverages) come from `summary.by_system[sys][k].mean`. The tooltip is `n` topic(s).
    - Wins come from `summary.wins_by_run`.
    - The rest come from `metrics.by_system[sys][k]` with `status`, `mean`, `n` and `not_measured_in`.
  - Formats: cost `$x.4f`, latency `x.1 s`, others `x.1%`. Gap formats: similarity ±x.2f, wins pts = ×100, others "pts".
- Summary cards per system: similarity mean /10 (± sd), Coverage %, Standard-only coverage %, Wins. "By section (similarity)" bars from `summary.by_section_similarity` (width = value × 10%). `short()` shortens two section names.
- Topic table:
  - Sortable by #, Gap (abs desc), RAG, Wiki.
  - Columns: # / Topic (code · section; links to `topic/{n}`) / Points with S/Sup/B counts / RAG sim / RAG cov / Wiki sim / Wiki cov / Gap / Wins r/w/t / Saved answers read (wiki).
  - Note: the topic-table Gap is `rag − wiki` (`run.ts:151`), the opposite sign of the scorecard's "Wiki − RAG".

**Topic page** (`benchmark/topic.ts`)
- Same GET as the run page; it picks `topics[n]`.
- Two cards: "Question asked" and "Human reference ({t.reference_label})" with the reference text.
- "Key points × grades" grid: per key point, the id, tag pill and text, plus `ref` (not for beyond_standard). Columns RAG r1..rN and Wiki r1..rN, using only runs with `judgement`. Cells are ✅ full, ⚠️ partial, ❌ missing (the default when absent). The tooltip is `point_notes[pid]`. A total row gives Similarity /10.
- Run toggle, then a verdict card: winner, blind labels A/B, rationale.
- Per system:
  - similarity/10 and coverage % pills, latency s
  - "Contradicts reference" list
  - the answer markdown (cites on for RAG only)
  - sources; saved answers read (wiki)
- "Answer checks" details:
  - pills for completeness, exact_match, exact_match_standard, citation_accuracy, using `metrics[k].value%` or "not measured"
  - Questions list
  - Exact-match facts, with the rubric facts version and whether it was approved
  - Citations (checked / not checkable counts)
  - "Checked by {model} (Claude subscription)"
- "Against what it read" details (context_checks): faithfulness, context recall and standard-only context recall pills, claims, key points in what it read, the model.

**Compare page** (`benchmark/compare.ts`)
- Calls `GET /api/bench/runs/{a}` and `{b}`.
- Shows A and B: collection vs wiki and the Sources of each. A "Different sources" warning appears if they differ.
- Rows are the topics where both runs have an `aggregate`: RAG A/B/Δ, Wiki A/B/Δ (Δ = B − A, mean similarity).
- Total cards: mean of the per-topic means, rounded to 2 decimals.
- "No topics in common." when the set is empty.

**Rubric review** (`benchmark/rubric.ts`), one page per topic
- Init: `GET /api/bench/rubrics`. The memo comes from `?ref=` or the first. Then `GET /api/bench/rubrics/{sha}`. A loading bar shows while it loads.
- Memo select if there is more than one; otherwise the label is shown.
- **Settings** card (toggle):
  - Rename the label (max 80): `PUT /api/bench/references/{sha} {label}`. The tooltip says the file name is never shown.
  - "Suggest changes": `POST .../suggest {topics:''}`. While it runs, the pill reads "Suggesting changes… X of N" and the rubric is re-fetched every 5000 ms. Topics with unsaved edits are not replaced.
  - "Make fact lists (N)" when facts are missing: `POST .../facts`. Polls every 4000 ms.
  - "Export": `export.docx?suggestions=false`. "Export with suggestions" (only if any suggestions exist): `suggestions=true`. Note: the UI never sends the server-supported `topic`, `tag` or `unreviewed` filters.
  - "Documents for the tag check" checkboxes over `documents`. The default is all ticked when `tag_sources` is null. "Save choice" calls `PUT /api/bench/references/{sha} {tag_sources}`; there is also Undo.
- Left list ("Approved: X of N" with a progress bar): one row per topic with a status icon, number, title, and a blue badge counting pending suggestions.
  - Status (`status()`, `rubric.ts` L86+330 to L92+330):
    - `progress` if anything is dirty or any decision is pending
    - `approved` if `reviewed_at` and facts are non-null and `facts_reviewed_at` is set
    - otherwise `progress` if partly approved or any suggestion already decided
    - otherwise `review`
  - Sticky sidebar at ≥1200 px. Below that it caps at 260 px height (this was the fix for narrow windows).
- Main panel for the current topic:
  - Title, status pill, `v{version}` (the tooltip lists the documents the tags were checked against), prev/next arrows.
  - Filter chips: All N, "Suggestions N" (pending tag changes), Standard/Supporting/Beyond with counts.
  - **Accept all suggestions (N)** (`acceptAll`): merges first, then all open point suggestions (tag and paragraph), then the fact list.
  - Merge suggestion cards: "Merge K1, K2 into one point", tag, reason tooltip, Accept/Reject. Accepting replaces the points with one point under the first id at the first position and marks the merged ids' own tag suggestions rejected.
  - Key point rows:
    - id, text, tag pill, `ref` (hidden for beyond_standard)
    - the pencil enters an editor: textarea, tag select, delete, Done
    - a changed row gets an orange border, a "Tag X → Y · Wording edited / Merged from … / New point" note and Undo
    - a paragraph-only change shows a minor note "(not saved yet)"
    - a pending tag suggestion shows "Suggested <tag> paragraph · document", a "Check" pill when `!found`, a reason tooltip (and second look), Accept/Reject
  - Facts section:
    - "Suggested hard-fact list (N)" card: "Use this list" / "Keep current"
    - an editable facts list; "Add fact" creates `F{next}`
    - empty states: "No fact list yet." or "No facts: exact match is not measured for this topic."
  - **Save bar**, sticky at the bottom:
    - "Unsaved:" counts by kind: tag changes, merges, wording edits, new points, points deleted, paragraphs added, "fact list replaced/emptied/facts edited", suggestions rejected
    - or "Not yet approved (key points approved, facts not)"
    - **Discard** resets to the saved state
    - **Approve topic** calls `PUT /api/bench/rubrics/{sha}/topics/{n}` with key_points (trimmed), facts (empty ones filtered out), `approve_points:true`, `approve_facts: facts!==null`, and the decisions. It then jumps to the next topic not yet approved, wrapping around.
  - An approved topic shows "Approved {date} · version N".
  - Tooltip texts live in `INFO` (`rubric.ts:31-56`).

#### Shared components
- **Markdown** (`shared/markdown.ts`, `app-md`):
  - Pipeline: `marked.parse(src, {gfm:true, async:false})`, then `DOMPurify.sanitize`, then `bypassSecurityTrustHtml` so the `data-*` attributes survive.
  - Before parsing, `[[target|label]]` (`WIKI_LINK` regex, `:9`) becomes `<a class="wl [missing]" data-wiki=slug>`, held in a placeholder made from the private-use char U+E000. The link text is the label, else the known title (`titles` map), else the humanised slug.
  - RAG citations (`CITE` regex, `:11`) match `[5.5.3]`, `[B5.5.17]`, `[5.5.15 (a)(i)]`, `[Appendix A: …]` and `[C123]`, with prefixes B|C|BC|BCZ|IE|IG. They exclude markdown links `[x](`. They become `<a class="cite" data-cite=ref>`, and the ref drops any "(…)" suffix. This can be turned off with `cites=false`.
  - `> [!kind]` blockquotes become `blockquote.callout` with a bold "kind:".
  - Clicks: `data-cite` calls `CitationService.openRag(ref)`. `data-wiki` (when the `wiki` input is set) either opens the drawer (`wikiLinks='drawer'`, default) or navigates to `/wiki/{w}/pages/{slug}` (`'navigate'`).
  - `slugify` lowercases, turns non-alphanumerics into `-`, trims and caps at 80 characters (fallback 'page').
- **Citation drawer** (`shared/citations.ts`, `citation-service.ts`):
  - RAG target: `GET /api/rag/chunks?para_ref&collection=<current>`. A 404 retries without a collection. Each chunk shows source_type, page, heading, part, content and filename.
  - Wiki target: `GET /api/wiki/wikis/{w}/pages/{slug}`. Shows type and version, the summary, the markdown (cites off) and an "Open page" button.
  - 404 messages: `No indexed paragraph "ref".` and `This page does not exist yet.`
- **Diff** (`shared/diff.ts`): renders a unified diff. It skips the ---/+++ lines and classes the others as hunk/add/del. Empty input shows "No textual changes."
- **Polling** (`shared/poll.ts`): `poller(fn, ms=3000)` uses a setTimeout chain until `fn` returns false. An exception counts as keep going. It stops on component destroy via DestroyRef. Note: the rubric page uses raw `setInterval` (4000 ms and 5000 ms) with no destroy cleanup.
- **File drop** (`shared/file-drop.ts`): a click-or-drag label around a hidden input. Single file. Inputs `accept` and `label` (default "Drop a file here or click to choose"), output `picked`, `reset()`.
- **Login** (`shared/login.ts`): a card with "Enter the password you were given." and a password field. Sign in calls `AuthService.login`, which shows "Wrong password" or "Login failed (status)".

---

## 10. Running and deployment

### 10.1 Required services

- **Postgres with the `vector` extension.** Locally this is the Supabase CLI stack defined in `Rag/supabase/config.toml` (Postgres 17, database on port 54322, API on 54321). It is started with `npx supabase start` in `Rag/`, which needs Docker (`README.md` Quick start).
- **A Google Gemini API key** for the RAG and Wiki (`GEMINI_API_KEY`), and optionally for the UI server's Ask rewrite.
- **For the benchmark judge,** either an Anthropic API key (`ANTHROPIC_API_KEY`) or the Claude Code CLI with `CLAUDE_CODE_OAUTH_TOKEN`, with `JUDGE_BACKEND=claude-code` (`Benchmark/bench/config.py`, `Benchmark/.env.example`).
- **Supabase Storage (optional),** used to keep original uploads (`SUPABASE_SECRET_KEY`).

### 10.2 Local start (from `README.md` "Quick start" and "Every time")

| Step | Command (run in the folder shown) | Notes |
|---|---|---|
| Database | `npx supabase start` (`Rag/`) | applies `Rag/supabase/migrations/*.sql` via the Supabase CLI |
| RAG schema (hosted, or after the CLI) | `python -m app.migrate` (`Rag/`) | tracking table `public.rag_schema_migrations` (`Rag/app/migrate.py`) |
| Wiki schema | `python -m app.migrate` (`Wiki/`) | tracking table `wiki.schema_migrations` (`Wiki/app/migrate.py`) |
| Benchmark and Ask schema | `python -m bench.migrate` (`Benchmark/`) | applies `Benchmark/migrations/0001…0011` (`Benchmark/bench/migrate.py`, §4.3) |
| RAG API | `python run.py` (`Rag/`), port 8000 | `Rag/run.py`; on Windows it sets a selector event loop for psycopg async |
| Wiki API | `python run.py` (`Wiki/`), port 8001 | `Wiki/run.py`, likewise |
| UI server | `python run.py` (`UI/server/`), port 8080 | `UI/server/run.py`; serves `UI/web/dist/web/browser` (`UI/server/app/config.py:web_dist`) |
| UI build | `npm install`, then `npm run build` (`UI/web/`) | Angular CLI; `npm start` runs the dev server on 4200 and proxies `/api` and `/view` to 8080 (`UI/web/proxy.conf.json`) |
| Benchmark from the command line | `python -m bench.run [--topics 1,2,5-7] [--runs N] [--run-id ID]` (`Benchmark/`) | §8.1; the UI normally spawns it instead |

Each service reads its own `.env` from its working directory. The `.env.example` files are the templates (§3). There are no seed scripts: corpora are built by uploading documents through the UI or the APIs.

There is **no automated test suite.** No Python tests exist, and no `*.spec.ts` files exist even though `UI/web/tsconfig.spec.json` is present (§12.5).

### 10.3 Build artefacts and ignore rules

- `.dockerignore` excludes from images: `.git`, `Docs/`, every `.venv`, every `.env`, `__pycache__`, `node_modules`, `results`, `.angular`, `UI/web/dist` and `Rag/supabase/.temp`.
- Per-service `.gitignore` files exclude environment files and build output: `Rag/.gitignore`, `Rag/supabase/.gitignore`, `Wiki/.gitignore`, `Benchmark/.gitignore`, `UI/server/.gitignore` and `UI/web/.gitignore`.
- The root `.gitignore` excludes `Docs/`, which holds client material and copyrighted standards.

### 10.4 Deployment (Render, Docker, CI)

#### render.yaml (in full)
- Header comment: Render Blueprint, with the Workbench UI public and the RAG and Wiki APIs private. The database is Supabase Cloud. `sync: false` secrets are asked for when the Blueprint is first created.
- **workbench**: `type: web`, `runtime: docker`, `dockerfilePath: ./UI/Dockerfile`, `dockerContext: .`, `region: frankfurt`, `plan: 0.5c-512mb`, `healthCheckPath: /healthz`, `preDeployCommand: python -m bench.migrate`.
  - Env vars:
    - `RAG_URL` fromService rag (pserv) property `hostport`
    - `RAG_API_KEY` fromService rag envVarKey `API_KEY`
    - `WIKI_URL` and `WIKI_API_KEY`, the same from wiki
    - `DATABASE_URL`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` (comment: Ask follow-up rewrite), `UI_PASSWORD`: all `sync: false` (secret, entered manually)
    - `SESSION_SECRET` with `generateValue: true`
    - `fromGroup: workbench-shared`
- **rag**: `type: pserv`, docker, `./Rag/Dockerfile`, context `.`, frankfurt, `0.5c-512mb`, `preDeployCommand: python -m app.migrate`.
  - Env: `API_KEY` generateValue; `DATABASE_URL`, `GEMINI_API_KEY` and `SUPABASE_SECRET_KEY` (optional, Storage for "View original") all sync false; group workbench-shared.
- **wiki**: identical to rag, with `./Wiki/Dockerfile`.
- **envVarGroups** `workbench-shared`: `DB_POOL_MAX: "4"`. Comment: the 3 services share the Supabase pooler's client limit.
- No health check is set on the pservs. No `disks` are declared, so nothing persists on disk; bulk runs are in memory.
- Not set in render.yaml: `JUDGE_BACKEND`. `Benchmark/.env` is excluded from the image by `.dockerignore`, so the deployed judge resolves to "api" (`bench.py:272-283`).

#### UI/Dockerfile
- Stage `web`: `node:24-slim`. `npm ci` from package.json and the lockfile, then `npm run build` (production by default).
- Runtime: `python:3.12-slim`.
  - Env: `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, `BENCH_DIR=/app/Benchmark`, `PYTHONPATH=/app/Benchmark`, `WEB_DIST=/app/UI/web/dist/web/browser`.
  - Installs UI and Benchmark requirements, copies `Benchmark/` and `UI/server/`, and copies the built dist.
  - WORKDIR `/app/UI/server`, EXPOSE 10000.
  - CMD: uvicorn on `${PORT:-10000}` with proxy headers.
  - A comment says benchmark runs are spawned with this same interpreter (no venv in the image).
- `Rag/Dockerfile` and `Wiki/Dockerfile`: `python:3.12-slim`, pip install, copy, EXPOSE 10000, uvicorn `${PORT:-10000}`. Migrations run via the pre-deploy command.
- `.dockerignore`: `.git`, `Docs/`, `**/.venv`, `**/.env`, `**/__pycache__`, `**/node_modules`, `**/results`, `**/.angular`, `UI/web/dist`, `Rag/supabase/.temp`. Because `Docs/` is excluded, the deployed image has no `DEFAULT_QUERY_SET`; bulk then needs an upload (DEPLOY.md troubleshooting row).
- Root `.gitignore` has only `Docs/`. Its comment: client material and copyrighted standards are kept local.

#### DEPLOY.md steps
1. **Supabase**:
   - Create the project in Central EU (Frankfurt).
   - Copy the **Session pooler** URI (port 5432) and append `?sslmode=require`.
   - The direct connection is IPv6-only, which Render cannot reach. The transaction pooler on 6543 breaks psycopg prepared statements.
   - The `vector` extension is created by the migrations.
2. **Render**:
   - Use New → Blueprint on the repo.
   - Enter the secrets: workbench `DATABASE_URL`, `ANTHROPIC_API_KEY` and `UI_PASSWORD`; rag and wiki `DATABASE_URL`, `GEMINI_API_KEY` and the optional `SUPABASE_SECRET_KEY`.
   - API keys, the private addresses, SESSION_SECRET and DB_POOL_MAX are wired automatically.
   - Apply. The first deploy takes about 5–10 min.
   - Note: the workbench `GEMINI_API_KEY` is in render.yaml but missing from DEPLOY.md's secrets table.
3. **First use**:
   - Log in.
   - Check that Home shows all three services healthy.
   - Create a RAG collection and upload the IFRS 9 PDF.
   - Create a wiki and ingest the same PDF in auto mode.
   - Start a Benchmark run, uploading the .docx and .txt.
- Costs: about $7/month per service on the Starter plan (0.5c-512mb). Private services cannot use the free plan. The Supabase free tier pauses after a week without activity. A full run is "about 100 Opus calls".
- Operations:
  - Every push to main redeploys (auto-deploy). Migrations run as the pre-deploy command.
  - A redeploy kills a running benchmark; about 2 min later it shows as interrupted and can be resumed.
  - Bulk runs are lost on redeploy.
  - `/view` is reachable only through the workbench, behind the login.
  - If a large ingest runs out of memory, raise the plan to `1c-2g`.
- Troubleshooting table: DEPLOY.md:82-93. Local image builds: `docker build -f {Rag,Wiki,UI}/Dockerfile`. `RAG_URL=rag:10000` and `WIKI_URL=wiki:10000` on one Docker network. Local Supabase from a container is at `host.docker.internal:54322`.

#### Local run (READMEs)
- Ports: RAG 8000, Wiki 8001, UI server 8080, Angular dev server 4200 (README.md:9-14; UI/README.md:14-30). Supabase DB on 54322.
- UI/README.md:16-30:
  - Server: venv, `pip install -r requirements.txt`, copy `.env.example` to `.env`, `python run.py`.
  - Web: `npm install`, then `npm run build` (served on :8080) or `npm start` (:4200, proxies to :8080).
- README.md:77: always start with `run.py`, not uvicorn directly, because Windows needs a selector event loop. [UNVERIFIED for the UI server: `UI/server/run.py` sets no event-loop policy; that line applies to the Rag and Wiki run.py.]
- Sharing via a Cloudflare quick tunnel: `cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8080`. Cloudflare cuts single requests after about 100 s (UI/README.md:49-62; README.md:345-359).
- UI/web/README.md is the stock Angular CLI 22.2.2 README (`ng serve`, `ng build`, `ng test` with Vitest, `ng e2e` with no framework).

#### CI
- There is none: no `.github/` directory, and no other CI config is tracked (`git ls-files` shows no workflow or pipeline files). Render auto-deploy on push to main is the only automation (DEPLOY.md:72). No test suite exists (no spec files).

---

## 11. Implemented vs not implemented

This is a candid list of what the design, schema, documentation or interface allows or suggests but the current code does not do, does only partly, or never populates. Each item cites the code that shows it.

### 11.1 Wiki: the LLM-wiki idea (`Wiki/llm-wiki.md`) against the code

| Design element | Status in code | Evidence |
|---|---|---|
| Raw sources immutable; LLM-owned wiki; schema document | **Implemented** | `wiki.sources` (text and sha256, no update endpoint); `wiki.pages`; `wikis.schema_md`, `PUT /schema` |
| Ingest touches many pages, updates index and log | **Implemented**, with a hard cap of 17 pages per ingest including the source page | `ops/ingest.py`, `config.max_pages_per_ingest` |
| `index.md` and `log.md` files | **Generated on request** from the database; not stored files | `store.render_index`, `render_log` |
| Query: search, answer with citations, file good answers back | **Implemented.** Filing back exists as the Ask screen's "Create synthesis" and as `save=true` on `POST /query`. The streaming endpoint ignores `save` | `ops/query.py:save_answer`, `ops/synthesis.py`, `routers/ops.py` |
| Lint: contradictions, stale claims, orphans, missing pages and links, data gaps | **Partly.** Structural checks plus an LLM check that *reports* contradictions and stale claims. The fix step only creates missing pages and adds links; contradictions and stale claims are never fixed. Web search for data gaps is not implemented | `ops/lint.py` (§6.7) |
| Contradiction flagging | **Convention only.** No table or flag exists; it relies on the model writing `> [!warning] Contradiction:` callouts as the schema asks. The viewer renders them | `schema_default.md`, `routers/view.py` |
| Version history | **Implemented in the database** (`wiki.page_versions`), not git; revert is supported | `store.apply_changeset`, `routers/pages.py` revert |
| Human review of changes | **Implemented** as changesets (`mode=review`). Conflicting operations are skipped, never merged. "Force apply" exists in the API (`apply_changeset(force=True)`) but the UI always sends `force=false` | `store.py`, `UI/web/src/app/pages/wiki/changeset.ts` |
| Search tooling with re-ranking | **Not implemented.** Hybrid full-text + vector with RRF in SQL; no re-ranker. The query instead has the model pick pages from the compact index | `wiki.search_pages`, `ops/query.py` |
| Images and attachments, Marp, charts | **Not implemented**; text only | `sources/extract.py` |
| Discussing takeaways with the user during ingest | **Not implemented**; ingest is a background job | `jobs.py`, `ops/ingest.py` |

### 11.2 Wiki: schema and data the code allows but rarely or never uses

- **Page types.** All seven are allowed (`store.PAGE_TYPES`).
  - `overview`, `source` and section `topic` pages are created by code on every ingest.
  - `concept`, `entity` and `comparison` exist only if the planner model chooses them (enums in `prompts.py`). Lint's "new page" can also create them.
  - Nothing forces `entity` or `comparison` pages, so whether they exist depends entirely on model output [UNVERIFIED: the counts per type in the live wikis are data, not code].
- **`changesets.kind`** comment lists `ingest | query | lint`. The code also writes `edit` (manual page edits and deletes, `routers/pages.py`).
- **`wiki.log.kind`** comment lists `delete`, but page deletes are logged as `apply` through `commit` [from `store.commit`; no separate delete log is written].
- **`page_flags.kind`** comment lists only `needs_checking`. The code also writes `citation_problems` (`saved.set_citation_problems`).
- **Database constraints.** No CHECK constraints anywhere enforce the allowed values of `type`, `kind` or `status` columns (all migrations).
- **The planner's `action` field** (`create` or `update`) is overwritten by code: "update" if the slug exists, else "create" (`ops/ingest.py:421`).
- **`EXEMPT_ORPHAN`** in `ops/lint.py` is defined but never used.
- **Synthesis `check`** computes citation corrections but does not apply them. `save` stores the content as submitted, with problems flagged (`ops/synthesis.py`).
- **`mdit-py-plugins`** is pinned but never imported (`Wiki/requirements.txt`).
- **Shared code copied from the RAG but unused in the Wiki:** `text.chunk_plain`, `Chunk.embed_text`, `BINDING_TYPES`, `STANDARD_TYPES`, `NON_BINDING_TYPES` and `ALL_TYPES` (`Wiki/app/sources/*`).

### 11.3 RAG

- **Missing seed file.** `supabase/seed.sql` is referenced by `Rag/supabase/config.toml` but does not exist.
- **`.docx` uploads.** `.docx` has a storage content type but is not an allowed upload type (`Rag/app/routers/documents.py`: `.pdf`, `.txt`, `.md` only).
- **Unrecorded usage.** The streaming endpoint records no token usage and returns no `read` record. Bulk runs return no usage (`Rag/app/llm.py`, `routers/query.py`).
- **Hard-coded fusion.** RRF weights and `rrf_k` are SQL defaults. They cannot be changed through the API or settings (`hybrid_search`).
- **Stale Postman collection.** `Rag/postman/RAG_API.postman_collection.json` still calls the old un-scoped paths `/ingest`, `/query`, `/query/stream` and `/bulk`, which no longer exist.

### 11.4 Benchmark

- **Supporting tag.** The key-point generator only ever tags `standard` or `beyond_standard` (enum in `judge.py:KEY_POINTS_SCHEMA`). `supporting` appears only through manual review or accepted suggestions.
- **Fact tags.** These exist only after suggested hard-fact lists are accepted. Until then, Standard-only exact match is "not measured" (`checks.py:score`).
- **Full-mode tests and older runs.** Faithfulness, context recall and Standard-only context recall run only in Full mode, and only for answers that recorded `read` (stage-1 capture). Older runs show them as "not measured" with the reason (`context.py`, `metrics.py`).
- **Batching.** Message Batches are used only with the API backend. The `claude-code` backend never batches (`run.py`, `config.judge_backend`). Answer-check and context-check batches are not resumable (`checks.py`, `context.py`: `batch_id=None`).
- **Cost per query** covers only the answering model's generation tokens. Embedding tokens are not reported by the services, and judge or check costs are not included (`metrics.py:cost_usd`).
- **README drift.** `Benchmark/README.md`'s cost note (about 26 key-point plus 78 judge calls) predates grading in both orders and the answer checks. Its statement that both systems answer "with the same Gemini model at temperature 0.1" matches the code: RAG 0.1 (`Rag/app/config.py:temperature`) and Wiki 0.1 (`Wiki/app/config.py:temperature`, changed from 0.2 in commit `f5a776b`). The temperature is not set by the Benchmark; each service uses its own setting.

### 11.5 UI

- **Logout.** No logout button exists, although `AuthService.logout()` exists (`UI/web/src/app/core/auth.ts`).
- **Server features the UI does not expose:**
  - rubric export filters (`topic`, `tag`, `unreviewed`; `UI/server/app/bench.py:export_rubric`);
  - Suggest changes for chosen topics (the server accepts `topics`; the UI sends all);
  - force-apply of changesets.
- **Pages tab** shows only the 7 known page types (`UI/web/src/app/pages/wiki/pages.ts`).
- **Gap sign.** The topic table's "Gap" column is RAG − Wiki, while the scorecard shows Wiki − RAG (`UI/web/src/app/pages/benchmark/run.ts`).
- **Tests.** There are no unit or end-to-end tests. `tsconfig.spec.json` expects vitest globals, but vitest is not a dependency.
- **README drift:**
  - `README.md` mentions "Save answer as wiki page" (now "Create synthesis") and "Tick either system off" (now a RAG/Wiki/Both toggle).
  - It says deployment "is not set up yet", but `render.yaml` and `DEPLOY.md` exist.
  - `Wiki/README.md` says deployment was deferred.

## 12. Limitations and assumptions in the code

Per service, as found in the code. Items already listed in §11 are not repeated in full.

### 12.1 RAG API

- There are no TODO, FIXME or NotImplemented markers in `Rag/app`.
- **No CORS** middleware.
- **No `thinking_config`**: the default thinking behaviour of gemini-2.5-flash applies.
- **Stream records no usage.** Bulk results do not include usage.
- RRF constants are fixed at the SQL defaults: `rrf_k=50`, weights `1`/`1`, candidates `match_count*2`. They are not configurable from Python or the API.
- `embed_dim` 768 is hard-wired in the SQL `vector(768)` in both migrations. Changing the setting needs a migration.
- The generic chunk overlap is hard-coded to `50` words. The `chunk_plain` default `max_words=400` is unused because the caller passes 500.
- The IFRS parser depends on specific fonts and coordinates:
  - fonts "Swift" and "HelveticaLTPro-*"
  - `MARGIN_MAX_X=150`, header y<110, footer y>720 (pixel geometry tied to the IFRS Foundation annotated PDF layout)
  - row grouping within 3pt, heading join within 14pt, Appendix A term join within 13pt, range join within 14pt
  - IFRIC box x<175 and size<9; heading size ≥ 9.4; skipped spans size<6
  - `looks_like_ifrs`: ≥ 10 hits in the first 40 pages
  - notes need more than 5 words
- Standard-mode section detection relies on exact heading strings ("appendix a" etc.). In the `intro` and `back_matter` sections, paragraphs get no para_ref.
- `parse_document` treats a whole PDF as one layout, either Standard or accompanying. A combined volume (Part A plus B/C in one PDF) is read as a Standard: its Basis for Conclusions falls under `back_matter`, which is excluded by default, and its IE/IG are not labelled by kind. [Inferred from the code.]
- Chunk `page` is the page where the paragraph starts.
- `.md` is treated as plain text: one "page", no heading metadata, `source_type="general"`.
- Single-document assumptions:
  - The citation key is `para_ref` only. Two documents in one collection that share para_refs (for example two Standards both with a 5.5.3) cannot be told apart in the context or in `_cited` matching. `format_context` does not include the filename.
  - `/search/paragraphs` and `/chunks` work across collections by filename or para_ref.
- `_cited` falls back to returning **all retrieved rows** as citations when the answer has no recognisable key.
- `sources="standard"` combined with non-Part A `source_types` gives an empty include list, so there are zero results.
- Bulk runs synchronously in one request, with no per-request timeout, no cap on the number of topics, and concurrency 3. A topic failure is captured per topic. `json.loads` of the model output can raise, which gives that topic an error entry.
- Bulk retrieval includes accompanying types (IE/IG/BC/DO) by default, while BULK_SYSTEM says the passages are "the binding text of the Standard".
- Embedding happens before the DB transaction, so a failed ingest wastes the embed calls. The storage upload happens after commit, so the DB keeps the document if the upload fails.
- Retry covers only Gemini `APIError` codes 429/5xx; database errors propagate.
- `supabase/seed.sql` is referenced in config.toml but missing.
- `httpx` is not pinned in requirements.txt.
- README:18 says schema changes need `npx supabase db reset` (wipes data) locally; hosted deploys use `app.migrate`.
- `collections` has RLS enabled with no policies, which denies Data API access. `documents` and `chunks` have no RLS, so they are exposed through the Supabase REST API with the default grants [UNVERIFIED; it depends on hosted grants and `auto_expose_new_tables`].

### 12.2 Wiki API: storage, extraction, jobs, viewer

**Concurrency and jobs**
- Single instance: in-process jobs, locks lost on restart, and restarted jobs are failed, not resumed (`jobs.py:1-4,32-39`; README:86).
- No job-level retry or timeout. The per-wiki lock serialises all jobs on a wiki.

**Changesets**
- Conflicts are skipped, not merged or rebased (README:87; `store.py:176-182`).
- `force=true` overwrites.
- Embeddings for a changeset are computed before the conflict check, so skipped ops still cost embedding calls (`store.py:163-167`).
- On update, `tags` cannot be cleared to empty (`o.tags or page["tags"]`, `store.py:197`).

**Hard-coded numbers**
- The embedding dimension 768 is fixed in the SQL (`vector(768)` in the table and the function). Changing `EMBED_DIM` needs a migration (`config.py:15`).
- RRF k = 50; candidate pool = `4*k` per list; snippet 400 characters (SQL).
- `compact_index` 60,000 characters; `render_log` 500 rows; job list 50; changeset list 100; source text preview 2000 characters; saved-flag detail lists capped at 50.
- Retry schedule 2/4/8/16s with 5 attempts; JSON retries 3; URL fetch timeout 30s; storage timeout 120s; signed URL 1h.

**IFRS parser**
- Tied to IFRS Foundation PDF typography: fonts "Swift" and "HelveticaLTPro*", margin x < 150, header y < 110, footer y > 720, heading size ≥ 9.4 (`pdf_ifrs.py:1-9,30-31,44-50`).
- Part A is detected only after a heading starting "International Financial Reporting Standard" (`pdf_ifrs.py:85-86`). [Inference, UNVERIFIED by test] An IAS ("International Accounting Standard") PDF would never enter the `standard` section, and would fall back to accompanying or page-by-page text.
- IG question headings only for letters A–G (`IG_HEADING_RE`).
- `chunk_max_words` is not passed to the parser; its 500 is hard-coded (`extract.py:75`).
- Part A extraction drops editorial notes, intro, Appendix C and back matter (`extract.py:78`).
- A PDF is either a Standard or an accompanying document. A single PDF bundling Part A with Parts B/C is read as "standard", and only standard, appendix_a and appendix_b chunks are kept. [Inference from `parse_document` returning early and `_section_for_heading` mapping BC headings to back_matter.]

**Other extraction**
- DOCX tables lose their position: they are appended at the end (`extract.py:109-111`).
- Upload size is checked only after the whole file is read into memory (`routers/sources.py:50-52`).
- Duplicate detection is on the exact extracted text's sha256. A changed parser could let the same file be re-ingested [inference].
- Originals are stored only for file uploads, and storage failures are silently ignored (`storage.py:88-90`).

**Security and visibility**
- One shared API key.
- The `/view` HTML viewer and `/docs` are public, exposing every wiki's pages, log and schema without auth (`main.py:28`; `view.py`).

**Viewer quirks**
- A page whose slug is `log` or `schema` cannot be viewed at `/view/{w}/{slug}`, because the fixed routes take precedence (`view.py:71-85`).
- The viewer header links to `overview`, assuming such a page exists (`templates/base.html:38`).

**Unused code and stale docs**
- Unused in Wiki/app: `text.chunk_plain`, `Chunk.embed_text`, `BINDING_TYPES`, `STANDARD_TYPES`, `NON_BINDING_TYPES`, `ALL_TYPES` (shared with Rag).
- Flag kind `citation_problems` is not documented in the migration comment.
- Log kind `delete` appears in the schema comment, but page deletes log as `apply` via commit [UNVERIFIED for ops/].
- README is stale: "Deployment (Dockerfile, hosted Supabase) has been deferred" (README:88), yet a Dockerfile and render.yaml references exist. Its endpoint table omits `/read-text`, `/graph`, `/sources/{slug}/file` and `/pages/{slug}/needs-checking`.
- No TODO, FIXME or NotImplemented markers in these files. There are also no tests in `Wiki/`.

**Gemini usage gaps**
- Embedding token use is not recorded (`input_tokens: None`), and streamed answers record no usage (`llm.py:73-74,107-113`).

### 12.3 Wiki API: ingest, query, lint, synthesis

**Caps and numbers:**
- Pages per ingest: 17 including the source page. Plan prompt: 16. Items after the sort: 16.
- Words: about 3000 per source section, 4000 per writing part, 12000 for a page when the schema has no sections (4000 for overview and source pages), 2000 of background.
- A writing part's tail under 1000 words is folded into the previous part.
- Routing: batches of 120, then 40, with the first 60 words of each paragraph shown. Also-record picking: batches of 120, with the first 200 words.
- Brief embedding input: 8000 characters. Query embedding input in `relevant`: 8000 characters.
- Plan: 40 names, `k=3` searches each, 40 candidate lines.
- Notes failure splitting: depth 2.
- Fill passes and also-record passes: 2 attempts each.
- Compact index: 60,000 characters.
- Query: search `top_k` 8 (only the top 5 used), the model picks up to 8, at most 13 pages read, at most 2 saved answers.
- Lint: batches of 12 pages; thin pages under 40 words; fix caps of 17 new pages and 17 link edits.
- Retries: 5 API attempts and 3 JSON attempts.
- Labels kept in citation reports: 50.
- Log title: question cut to 200 characters. change_note: question cut to 150 characters.

**IFRS-specific logic:**
- `ONE_TOP_PAGE` names `ifrs-9`.
- `also_prompt` refers to "the Standard leaves to the entity".
- `route_prompt` gives the B-paragraph rule ("B6.x goes with chapter 6").
- `_group_key` and `REF_PAT` assume IFRS-style numbering.
- `EXAMPLE_LABEL` and the examples section.
- `_placeholder` assumes the IFRS stub wording "not included in this edition".
- `standard_only` relies on `meta.parser='ifrs'` (Part A).
- citecheck's `STANDARD_NAME` covers IFRS, IAS, IFRIC and SIC.
- Synthesis `FRAMEWORK_RE` expects slugs like `ifrs-9-…`.
- The example citation in `also_record_prompt` is `5.5.15`.
- Section pages depend on the wiki schema using `### NN. Name` headings and the `ADDITIVE` marker.

**Single-source assumptions:**
- Routing, gap checks and "Not yet covered" look only at the paragraphs of the source being ingested.
- When a later source has paragraphs for a section, the section page is rewritten from the existing body plus the new paragraphs.
  - In multi-part mode the prompt keeps only existing content "that relates to this part's source paragraphs", so content from earlier sources may be dropped (inference from the prompt).
  - The old "Not yet covered" line stays in `cur_body`, and the model is never told to remove it [UNVERIFIED whether it survives].
- A section page that already exists and gets nothing from the new source is left untouched.
- An ADDITIVE section that is also routed paragraphs combines both behaviours.

**Designed but not implemented, or dead:**
- `EXEMPT_ORPHAN` is never used.
- Lint never fixes contradictions or stale claims.
- Synthesis `check` computes corrections but does not apply them, and `save` stores the content as submitted.
- The streaming endpoint ignores `save` and returns no `read` record or `usage`.
- The planner's `action` field is ignored.
- The model's `change_note` from `save_answer` is ignored.
- Contradiction flagging depends entirely on the model following the schema's callout.
- No grep hits for TODO, FIXME or XXX in the scoped files.

**Other observations:**
- With 16 or more schema sections, the overview is cut by the page cap.
- `_select` stops at the first group that does not fit, so smaller groups ranked lower are never added.
- The brief parser stops at any `##`-prefixed line, including `###` sub-headings.
- Saved answers in review mode are only pending. Synthesis save always applies.
- In review mode, `page_sources` links are created only when the changeset is applied.
- The ingest commit's `saved_answers_to_check` comes only in auto mode, because `apply_changeset` runs only then.
- Only one server process is supported (`jobs.py:3`).

### 12.4 Benchmark

- **No TODO/FIXME/XXX/NotImplemented** markers in Benchmark/bench or migrations (grep).
- **Stale README:**
  - The cost section (L71) says "Roughly 26 key-point calls plus 78 judge calls". Grading is now done in both orders, so there are 2 calls per pair, plus check and context calls.
  - README Method step 5 does not mention both-order grading.
  - Runs default: see section 2 (2 vs 3).
- **Effort:** `judge_effort` ("high") is applied to the Sonnet checks and context calls too. There is no separate effort setting.
- **Hard-coded caps and values:**
  - max_tokens 16000.
  - System HTTP timeout 300 s, 3 attempts, 5/10 s backoff.
  - read-text timeout 120 s; /search/paragraphs timeout 60 s.
  - MAX_CITATIONS 40; MAX_PARAGRAPH 3000 characters; MAX_CLAIMS 40.
  - Hard facts "At most 10" (in the prompt only, not enforced).
  - BM25 k = 8, per_tier = 2; Finder cap 14.
  - LOG_LINES 300; heartbeat 30 s; batch poll 30 s and timeout 6 h; CLI judge timeout 900 s; DB connect_timeout 15 s (migrate).
  - Similarity is an integer 0–10.
- **Latency includes retry backoff** (systems.py L31-45).
- **Cost excludes:** embedding calls (no token count), judge, checks and context costs, and any batch discount.
- **Facts drift:** the checks use the current rubric facts. The grading and context recall use the key points snapshot stored in the run. A run's exact match can therefore change after a backfill.
- **Rubric tags:** the key point generator only tags standard or beyond_standard. "supporting" relies on manual review or accepted suggestions. Fact `kind` exists only after suggestions are accepted; otherwise Standard-only exact match is not measured.
- **Reference parsing** assumes Heading 2/3 styles, table 0 as the summary, one table per topic in order, and only the first row with 2 cells. Pairing is positional with a 0.6 fuzzy title check.
- **Wiki slug** is not URL-quoted (`systems.py` L38); the RAG collection is.
- **Checks and context batches** are not resumable (always `batch_id=None`, `on_submit` a no-op). The checks backfill never batches (`use_batch=False`, `checks.py` L408).
- **`checks.backfill`** calls `facts_for_reference` first, which can make new fact lists through judge calls.
- **Citation resolution** matches the slug and label exactly against `wiki.sources` paragraph labels. Citations to documents no wiki holds are not checkable, and a whole-page `[[page]]` link is not checkable. A bare `[x]` must contain a digit or an Appendix prefix.
- **Semantic search** silently falls back to words only on the first error and stays off for the whole suggest run (`suggest.py` L116-118). This is recorded in `search`.
- **The claude-code backend** has no max_tokens or refusal fallback. Usage counts cache tokens as input.
- **The server-side fallback** (`fallbacks="default"`, beta "server-side-fallback-2026-07-01") is on normal API calls only, including checks, context, key points, facts and suggestions, since they all use `_json_call`. Batch requests do not carry it.
- **Older runs:** `use_saved=null` is treated as True. `rag_collection` was backfilled to 'ifrs9' and `sources` to 'all' (migrations 0002, 0003).
- **0006 `ask.*` tables** belong to the UI Ask screen and are not used by bench/*.py.
- Both systems default to temperature 0.1 (§3.5); the Benchmark itself sets none. Rubric approval, tag edits, accepting suggestions and `tag_sources` writes are done by the UI (`UI/server/app/bench.py`, §9.2).

### 12.5 UI
- **No tests**: `tsconfig.spec.json` expects vitest globals, but vitest is not installed and there are no spec files. No Python tests exist for UI/server.
- **No logout button**: `AuthService.logout()` exists (`core/auth.ts:31-34`), but no UI calls it.
- **Force-apply of changesets** is not reachable: `apply(force)` is always called with `false` (`wiki/changeset.ts:26, 89`). README.md:374 mentions "apply with force".
- **Rubric export filters** (`topic`, `tag`, `unreviewed`) exist on the server (`bench.py:529`) but are not exposed in the UI (`rubric.ts` exportUrl sends only `suggestions`).
- **Suggest for chosen topics**: the server accepts `topics`; the UI always sends `''` (all topics).
- **Single job at a time**: `_ensure_idle` blocks any concurrent benchmark, rebuild, suggest or facts job per process (`bench.py:212-214`). The bulk runner and the bench subprocess state are per process and in memory (`bulk.py:13`, `bench.py:24`).
- **Hard-coded values**:
  - The estimate's model price keys are `claude-opus-5-5` and `claude-sonnet-5-5` (`bench.py:336, 387`), and its item labels name "Claude Opus 5.5" and "Claude Sonnet 5.5".
  - The Gemini rewrite endpoint is `v1beta` (`ask.py:92`).
  - Timeouts: proxy 600/10 s; status checks 5 s; bulk 3600 s; Gemini 60 s; ensure collection/wiki 15 s; topics subprocess 120 s.
  - Login delay 1.5 s. Cookie 7 days. Label TTL 15 min. Stale threshold 2 min. Upload cap 20 MB. Runs between 1 and 10.
  - Default topics: '2' on Benchmark, '1' on Bulk. Poll intervals: 3000, 4000 and 5000 ms.
  - The run page's `short()` hard-codes two IFRS 9 section names (`run.ts:227`).
- **Stale documentation**:
  - README.md:296 says "Tick either system off". The code uses a RAG only/Wiki only/Both toggle.
  - README.md:321 mentions "Save answer as wiki page". The code has "Create synthesis".
  - README.md:405 says "deployment … is not set up yet", but render.yaml and DEPLOY.md exist.
  - The UI/README.md screens table lists "Ask" twice (lines 36 and 40).
- **Inconsistencies and bugs**:
  - Topic-table Gap is `rag − wiki` but the scorecard is Wiki − RAG (`run.ts:151` vs `:31`).
  - The runs-table empty row uses `colspan=10` for 14 columns (`runs.ts:169`).
  - The Pages tab drops any page whose type is outside the 7 hard-coded TYPES (`wiki/pages.ts:10, 51-53`).
  - The rubric page's setInterval timers are not cleared on destroy (`rubric.ts` L365+330, L395+330).
  - The Home benchmark card uses only the newest run, even if it is unfinished (`main.py:50`, `home.ts:35`).
- **Security and data notes**:
  - There is a single shared password with full access (UI/README.md:65; README.md:357).
  - FastAPI `/docs` and `/openapi.json` are probably not behind the login [UNVERIFIED, see §1].
  - The `/view` proxy sends no API key to the Wiki viewer (`main.py:72`). The Wiki API's viewer is public by design (README.md:225).
  - The UI server reads `wiki.sources` directly from the shared DB (`bench.py:460-475`), which couples it to the Wiki schema.
  - Memo masking covers config, errors, summary, log, labels and export, but not `results.topics` [UNVERIFIED impact, see §2].
- `.env.example` omits `GEMINI_API_KEY` even though the Ask rewrite needs it. Without the key, follow-ups are sent as typed, with the warning "Could not rewrite the follow-up: GEMINI_API_KEY is not set for the Workbench server" (`ask.py:89-90, 116-117`).

### 12.6 Cross-cutting assumptions that would not generalise as written

1. **IFRS Foundation PDF typography.** Paragraph detection in both the RAG and the Wiki depends on:
   - the fonts "Swift" and "HelveticaLTPro-*";
   - a margin at x < 150 and header/footer bands at y < 110 or y > 720;
   - a heading size of at least 9.4 pt;
   - the heading text "International Financial Reporting Standard" (`Rag/app/ingest/pdf_ifrs.py`, `Wiki/app/sources/pdf_ifrs.py`).

   Other publishers' PDFs, or an IAS ("International Accounting Standard") PDF, fall back to page-by-page text without paragraph numbers [inferred from `_section_for_heading`; not tested].
2. **One layout per PDF.** A PDF is treated as either a Standard (Part A) or an accompanying document (Parts B/C). A single volume containing both is read as a Standard, and its accompanying material is dropped or mislabelled (`parse_document` in both services).
3. **Paragraph labels identify text across documents.** RAG citations are the bare `para_ref`, and the context given to the model has no document name (`Rag/app/retrieval.py:format_context`). Two documents in one collection that share paragraph numbers cannot be told apart. The benchmark's citation check and rubric library look labels up across all wiki sources (`Benchmark/bench/library.py`).
4. **The Wiki's section logic needs a particular schema shape:** `### NN. Name` headings and the word `ADDITIVE`. Several prompts and regexes are IFRS-specific, including:
   - `ONE_TOP_PAGE` naming `ifrs-9`;
   - B-paragraph routing;
   - `EXAMPLE_LABEL`;
   - the "not included in this edition" placeholder;
   - the synthesis `FRAMEWORK_RE` (`Wiki/app/prompts.py`, `Wiki/app/ops/*.py`, §12.3).
5. **The benchmark's IFRS 9 framing.** Judge prompts call the judge "an IFRS 9 expert" (`judge.py`). The reference `.docx` must follow a fixed layout: Heading 2/3 styles, table 0 as the summary, and one table per topic paired by position with a 0.6 fuzzy title check (`Benchmark/bench/data.py`). The run page hard-codes two IFRS 9 section names (`UI/web/src/app/pages/benchmark/run.ts:short`).
6. **One instance per service.** The Wiki's jobs and locks, the UI's bulk runs and benchmark processes, and the memo-label cache all live in process memory. Multiple instances would not coordinate, and a restart fails or interrupts running work (`Wiki/app/jobs.py`, `UI/server/app/bulk.py`, `UI/server/app/bench.py`). The UI allows one benchmark-type job at a time per process (`bench.py:_ensure_idle`).
7. **One shared database and shared keys.**
   - All services share one Postgres; the UI server reads `wiki.sources` directly (`UI/server/app/bench.py:_documents`), coupling it to the Wiki schema.
   - Each API has a single shared key, and the UI has a single shared password with no user accounts (`*/auth.py`).
   - The Wiki's `/view` HTML viewer and FastAPI's `/docs` are not behind any key (`Wiki/app/main.py`).
8. **Fixed embedding dimension.** 768 is hard-coded in SQL. Changing the embedding model's dimension needs migrations in both the RAG and the Wiki.
9. **Everything is built in memory:**
   - uploads are read fully before size checks (`Wiki/app/routers/sources.py`; the RAG has no size limit);
   - Obsidian export ZIPs and Word exports;
   - synchronous bulk runs with no timeout in the RAG API (`Rag/app/routers/bulk.py`).
10. **Gemini-only systems under test.** Both systems use the same Gemini chat model and temperature (0.1) by default (§3.5). Only Claude is used as the judge. The cost table `Benchmark/bench/prices.json` covers only the models named there.

## Coverage audit

### A. File coverage against the reconnaissance checklist

All 186 tracked files were checked against the body of this document (§1–§12) by path. 164 are cited there by path or file name. The remaining 22 are covered here, with what each contains and why it adds nothing further:

| File | Content | Coverage |
|---|---|---|
| `Benchmark/bench/__init__.py`, `Rag/app/__init__.py`, `Rag/app/ingest/__init__.py`, `Rag/app/routers/__init__.py`, `UI/server/app/__init__.py`, `Wiki/app/__init__.py`, `Wiki/app/ops/__init__.py`, `Wiki/app/routers/__init__.py`, `Wiki/app/sources/__init__.py`, `Wiki/app/wiki/__init__.py` | empty package markers (0 bytes, `wc -c`) | nothing to document |
| `Rag/app/routers/collections.py` | the collection CRUD routes: `GET/POST /collections`, `PATCH/DELETE /collections/{c}`, slug pattern `^[a-z0-9][a-z0-9-]{1,62}$`, `collection_dep` (404 `Collection '<c>' not found`) | behaviour documented in §5.6 and §5.7 (endpoint table) without naming the file; named here |
| `Wiki/app/templates/doc.html` | Jinja template extending `base.html` that wraps a rendered body in `<article>`. Used by the viewer's Log and Schema pages (`Wiki/app/routers/view.py:75,82`) | viewer documented in §6.15 |
| `README.md` (root) | the user guide: parts, quick start, configuration, per-service usage, benchmark notes, troubleshooting | cited in §10.2 and §11.4–§11.5 (stale statements listed) |
| `Rag/README.md` | RAG setup (`npx supabase start`, venv, `.env`), collections, Swagger at `/docs`, Postman import, `npx supabase db reset` for schema changes | setup in §10.2; Postman staleness in §11.3 |
| `.gitignore` (root) | `Docs/` only, with a comment that client material and copyrighted standards stay local | §0 and §10.3 |
| `UI/web/.editorconfig` | UTF-8, 2-space indent, final newline, single quotes for `.ts`, no line limit for `.md` | editor settings only |
| `UI/web/.prettierrc` | `printWidth: 100`, `singleQuote: true`, Angular parser for `*.html` | formatter settings only |
| `UI/web/tsconfig.app.json` | extends `tsconfig.json`; includes `src/**/*.ts`, excludes `src/**/*.spec.ts`; `types: []` | build configuration (Angular CLI) |
| `UI/web/.vscode/extensions.json`, `launch.json`, `tasks.json` | recommends `angular.ng-template`; Chrome launch configs "ng serve" and "ng test"; npm tasks `start` and `test` | IDE settings only; `ng test` has no tests to run (§11.5) |
| `UI/web/public/favicon.ico` | Windows icon resource, 3 sizes | static asset |

Result: **every tracked file is reflected** in the document or in this table. Untracked files (`.DS_Store`, `Benchmark_Overview.html`, see §0) and git-ignored files (`.env`, `Docs/`, build output) are out of scope by design. `.env` values were never read into this document.

### B. Re-verification of numbers in §6, §8 and §11

After writing, 58 numbers and claims from §6 (Wiki pipeline), §8 (Evaluation) and §11 (Implemented vs not implemented) were re-checked against the code at the pinned commit by an automated pattern search over the cited files. **All 58 were confirmed.** Four needed a manual look because the default is written with a type annotation; their exact lines are given.

| Check | File | Result |
|---|---|---|
| §6 PAGE_TYPES (7 types) | `Wiki/app/wiki/store.py` | confirmed |
| §6 max_pages_per_ingest = 17 | `Wiki/app/config.py` | confirmed |
| §6 plan cap = max_pages_per_ingest - 1 (16) | `Wiki/app/ops/ingest.py` | confirmed |
| §6 section_words = 3000 | `Wiki/app/config.py` | confirmed |
| §6 page_source_words = 12000 | `Wiki/app/config.py` | confirmed |
| §6 page_part_words = 4000 | `Wiki/app/config.py` | confirmed |
| §6 page_background_words = 2000 | `Wiki/app/config.py` | confirmed |
| §6 route_batch = 120 | `Wiki/app/config.py` | confirmed |
| §6 route retry batch 40 | `Wiki/app/ops/ingest.py` | confirmed |
| §6 query_top_k = 8 | `Wiki/app/config.py` | confirmed |
| §6 query_max_pages = 8 | `Wiki/app/config.py` | confirmed |
| §6 top 5 search hits always read | `Wiki/app/ops/query.py` | confirmed |
| §6 at most 2 saved answers | `Wiki/app/ops/query.py` | confirmed |
| §6 compact index 60000 chars | `Wiki/app/wiki/store.py` | confirmed manually: `Wiki/app/wiki/store.py:312` `compact_index(..., limit_chars: int = 60000, ...)` |
| §6 render_log 500 | `Wiki/app/wiki/store.py` | confirmed manually: `Wiki/app/wiki/store.py:326` `render_log(wiki, limit: int = 500)` |
| §6 lint_batch_pages = 12 | `Wiki/app/config.py` | confirmed |
| §6 job_workers = 2 | `Wiki/app/config.py` | confirmed |
| §6 llm_concurrency = 4 | `Wiki/app/config.py` | confirmed |
| §6 Wiki temperature 0.1 (`temperature: float = 0.1`, line 17) | `Wiki/app/config.py` | confirmed |
| §6 chunk_max_words 500 | `Wiki/app/config.py` | confirmed |
| §6 max_upload_mb 50 | `Wiki/app/config.py` | confirmed |
| §6 search RRF k 50, candidates *4 | `Wiki/migrations/0001_init.sql` | confirmed |
| §6 snippet 400 chars | `Wiki/migrations/0001_init.sql` | confirmed |
| §6 retries 5, codes, 2**i*2 | `Wiki/app/llm.py` | confirmed manually: `Wiki/app/llm.py:15,23,30` `RETRYABLE = {429, 500, 502, 503, 504}`, `_retry(fn, attempts: int = 5)`, `delay = 2 ** i * 2` |
| §6 JSON retries 3 | `Wiki/app/llm.py` | confirmed manually: `Wiki/app/llm.py:116` `generate_json(..., attempts: int = 3)` |
| §6 EXAMPLE_LABEL | `Wiki/app/ops/ingest.py` | confirmed |
| §8 runs default 2 | `Benchmark/bench/config.py` | confirmed |
| §8 seed 42 | `Benchmark/bench/config.py` | confirmed |
| §8 concurrency 4 | `Benchmark/bench/config.py` | confirmed |
| §8 judge model claude-opus-5-5 | `Benchmark/bench/config.py` | confirmed |
| §8 judge effort high | `Benchmark/bench/config.py` | confirmed |
| §8 checks model sonnet | `Benchmark/bench/config.py` | confirmed |
| §8 context model sonnet | `Benchmark/bench/config.py` | confirmed |
| §8 judge timeout 900 | `Benchmark/bench/config.py` | confirmed |
| §8 max_tokens 16000 | `Benchmark/bench/judge.py` | confirmed |
| §8 WEIGHT full 1 partial .5 missing 0 | `Benchmark/bench/run.py` | confirmed |
| §8 shuffle seed f'{seed}-{topic}-{rep}' | `Benchmark/bench/run.py` | confirmed |
| §8 std+supp only when sources == all | `Benchmark/bench/run.py` | confirmed |
| §8 bootstrap 10,000 resamples | `Benchmark/bench/gaps.py` | confirmed |
| §8 CI percentiles 2.5/97.5 | `Benchmark/bench/gaps.py` | confirmed |
| §8 LOWER_IS_BETTER latency, cost | `Benchmark/bench/gaps.py` | confirmed |
| §8 JUDGED incl. coverage_std_supp | `Benchmark/bench/gaps.py` | confirmed |
| §8 MAX_CITATIONS 40 | `Benchmark/bench/checks.py` | confirmed |
| §8 MAX_PARAGRAPH 3000 | `Benchmark/bench/checks.py` | confirmed |
| §8 MAX_CLAIMS 40 | `Benchmark/bench/context.py` | confirmed |
| §8 context recall weights | `Benchmark/bench/context.py` | confirmed |
| §8 checks VERSION checks-2 | `Benchmark/bench/checks.py` | confirmed |
| §8 context VERSION context-2 | `Benchmark/bench/context.py` | confirmed |
| §8 system HTTP timeout 300 | `Benchmark/bench/systems.py` | confirmed |
| §8 backoff 5*(i+1) | `Benchmark/bench/systems.py` | confirmed |
| §8 BM25 k1 1.5, b 0.75 | `Benchmark/bench/library.py` | confirmed |
| §8 Finder cap 14 | `Benchmark/bench/suggest.py` | confirmed |
| §8 key point kinds enum (standard, beyond_standard) | `Benchmark/bench/judge.py` | confirmed |
| §11 EXEMPT_ORPHAN defined | `Wiki/app/ops/lint.py` | confirmed |
| §11 RAG upload types pdf/txt/md | `Rag/app/routers/documents.py` | confirmed |
| §11 RAG temperature 0.1 | `Rag/app/config.py` | confirmed |
| §11 planner action overwritten | `Wiki/app/ops/ingest.py` | confirmed |
| §11 seed.sql referenced | `Rag/supabase/config.toml` | confirmed |

The other numbers in §6, §8 and §11 come from the per-file reading behind each section, which cites file and line. They were not each re-run through the automated check above.

### C. Items marked [UNVERIFIED]

The document has 21 [UNVERIFIED] marks. They fall into four groups:
- behaviour that would need a running system or live data to confirm, such as planner behaviour on HNSW, live counts of page types, or hosted Supabase grants;
- package provenance that is not pinned (`httpx` in the RAG);
- the reach of FastAPI's default `/docs` behind the UI login;
- inferences from prompts or regexes that were not exercised in a test.

Each mark states its reason where it appears.

