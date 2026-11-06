# RAG vs Wiki Benchmark

This measures how closely the RAG API (`../Rag`) and the LLM Wiki API (`../Wiki`) answer the topics of a query set, against a human-written reference assessment (a .docx kept in `Docs/`, never committed). Claude is the judge, called through the paid Anthropic API only.

## Systems compared
Every run compares three systems, each asked the identical question text (the topic's title plus its questions Q1..Qn):

| System | Label | What it is |
|---|---|---|
| `rag` | RAG (per topic) | RAG `POST /collections/{c}/query` with `retrieval: "whole"`: one search for the whole topic |
| `rag_q` | RAG (per question) | the same route and answer prompt with `retrieval: "per_question"`: one search for the topic's first line and one per numbered question |
| `wiki` | Wiki | Wiki `POST /wikis/{slug}/query` |

The list and labels live in one place, `bench/systems.py` (the UI server keeps a marked copy). Both RAG columns also search the Standard's editorial text (`RAG_INCLUDE_EDITORIAL`, on), which the wiki keeps too. **Sources** (`standard` = Part A only, `all` = Parts A, B and C) is always the same for every system. **Use saved answers** lets the wiki also read relevant saved answers (synthesis pages filed with Save); it is off by default in the UI.

## Method
1. **Rubric.** Claude breaks each topic's reference answer into atomic key points, once per reference file (identified by its SHA-256), saved in `bench.rubrics` and reused by every run with that file. It also makes a short list of exact-match facts (numbers, periods, thresholds, yes/no answers) per topic. You review both on the **Rubric review** screen: tag each point **Standard** (the Standard's own text, Part A), **Supporting** (documents published with it, Parts B and C) or **Beyond standard** (practice, regulation, opinion), edit, delete, then approve. Every change makes a new version (`bench.rubric_versions`); each run records the version and approval it used.
2. **Answers.** Every system answers every topic once per repetition (`RUNS`, default 2). Answers are saved before grading, so a run whose grading failed is resumed and graded without asking again. Each answer records what it read (RAG: the passages; wiki: each page's version and a hash of its text) and the AI calls behind it with their tokens.
3. **Grading (blind, both orders).** The wiki answer is paired with each RAG column. Each pair is graded twice, A-then-B and B-then-A, with seeded random labels. Claude grades each key point as full, partial or missing for both answers, scores similarity 0–10, lists contradictions with the reference, and picks a winner. The two orders are averaged; a win counts only when both orders agree, otherwise it is a tie. The wiki's main scores are from its pair with RAG (per topic); its scores in the RAG (per question) pair are kept with that pair.
4. **Scores.**
   - coverage % = (full + 0.5 × partial) / key points; standard-only coverage over Standard points; Standard + Supporting coverage (runs reading all sources only)
   - similarity (0–10) and wins
   - latency and cost per query (recorded tokens × `bench/prices.json`)
   - each topic gets the mean ± sd over its repetitions; the run summary averages the topic means
   - every wiki-minus-RAG gap has a 95% confidence interval (topics resampled 10,000 times); an interval crossing zero means no clear difference
5. **Answer checks** (every run, one `CHECKS_MODEL` call per answer, never told which system wrote it):
   - **completeness**: is each question answered, partly answered or not answered
   - **exact match**: share of the topic's exact-match facts the answer states (and Standard-only exact match over the Standard-tagged facts)
   - **citation accuracy** (checks-3): each cited paragraph is looked up in the source texts the wikis keep, and the judge decides whether it supports the statement. Only the citations that end a sentence (or a list part or table cell) count; a citation inside a sentence is a pointer and is not counted, and a line holding only citations is not counted. A citation to a whole page, or to a paragraph not in those texts, is counted but not scored; a wiki citation naming a source that does not hold the paragraph counts as not supported.

A test that cannot be worked out is stored as "not measured" with the reason, never as 0.

## Quick and Full mode
- **Quick**: answers, grading, answer checks, latency and cost.
- **Full**: needs an approved rubric (every chosen topic's key points and fact list; the UI and the runner both refuse otherwise) and adds:
  - **faithfulness**: share of the answer's claims backed by what it read
  - **context recall**: share of key points present in what it read, and standard-only context recall counting only the Standard's own text (context-3); one `CONTEXT_MODEL` call per answer. The wiki's pages are rebuilt from the page versions the answer recorded (`POST /wikis/{w}/read-text`); saved answers it read do not count as backing.
  - **standard-only similarity**: each graded pair judged again, both orders, against only the Standard-tagged key points, on the 0–10 scale, with its own gap and interval.

## Judge
The judge is the Anthropic API (`ANTHROPIC_API_KEY`, or the SDK's own key lookup when unset), `JUDGE_MODEL` at `JUDGE_EFFORT`. With **Batch grading** on (`USE_BATCH`, default on) gradings, answer checks, context checks and standard-only similarity go through the Message Batches API at half price; anything a batch does not return is done with the normal API. Normal calls send a server-side refusal fallback. A batch not finished after `BATCH_TIMEOUT_S` is cancelled and the rest done normally.

## Run
```powershell
cd Benchmark
python -m venv .venv; .venv\Scripts\pip install -r requirements.txt
copy .env.example .env          # set ANTHROPIC_API_KEY, RAG_API_KEY, WIKI_API_KEY
.venv\Scripts\python -m bench.migrate                     # create the bench tables once (Render runs it before each deploy)
# start ../Rag (port 8000) and ../Wiki (port 8001) with their run.py
.venv\Scripts\python -m bench.data                        # check the topic <-> reference mapping
.venv\Scripts\python -m bench.run --topics 2 --runs 1     # a quick check from the command line
```
The UI's Benchmark page is the usual way to start runs; it uploads the inputs and runs `python -m bench.run --run-id <id>`.

## Commands
| Command | What it does |
|---|---|
| `python -m bench.run [--topics 1,2,5-7] [--runs N]` | new run from the CLI, inputs from `QUERY_SET` / `REFERENCE_DOCX` |
| `python -m bench.run --run-id <id>` | run or resume a stored run (the UI uses this) |
| `python -m bench.rubric rebuild <sha256>` | build a rubric's key points again (the UI's Rebuild button); later runs are not directly comparable with earlier ones |
| `python -m bench.checks facts <sha256>` | make the exact-match fact lists a rubric is still missing (the UI's Make fact lists) |
| `python -m bench.suggest <sha256> [topics]` | suggest tags (with the backing paragraph from the source texts), merges and a hard-fact list (the UI's Suggest changes); nothing changes until you accept and approve |
| `python -m bench.context <run-id> ...` | re-score a Full run's faithfulness and context recall from its saved answers and what they read |
| `python -m bench.std_similarity <run-id> ...` | add standard-only similarity to a finished run |
| `python -m bench.data` | check that each topic finds its reference answer |
| `python -m unittest discover tests` | offline tests of the citation rules (no database, no AI call) |

## Settings (`.env`)
| Setting | Default | Use |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | the judge's API key |
| `JUDGE_MODEL`, `JUDGE_EFFORT` | `claude-opus-5-5`, `high` | key points, grading, fact lists, standard-only similarity |
| `CHECKS_MODEL`, `CONTEXT_MODEL` | `claude-sonnet-5-5` | answer checks; faithfulness and context recall |
| `RAG_URL`, `RAG_API_KEY`, `WIKI_URL`, `WIKI_API_KEY` | local ports 8000 / 8001 | the systems under test |
| `DATABASE_URL` | local Supabase | where runs and rubrics are stored |
| `RAG_INCLUDE_EDITORIAL` | on | both RAG columns also search editorial text; recorded per run |
| `USE_BATCH`, `BATCH_POLL_S`, `BATCH_TIMEOUT_S` | on, 30 s, 6 h | Message Batches |
| `RUNS`, `CONCURRENCY`, `SEED` | 2, 4, 42 | repetitions per topic, parallel topics, blind-label seed |
| CLI only: `RAG_COLLECTION`, `WIKI_SLUG`, `SOURCES`, `USE_SAVED`, `MODE`, `QUERY_SET`, `REFERENCE_DOCX` | | what a CLI run compares and its inputs (UI runs choose and upload them) |

## Output: `bench.runs`
One row per run: status, the uploaded inputs, the run log and `results` (JSON):
- `config`: judge model and effort, the systems compared and their labels, each RAG column's retrieval, the collection and wiki, Sources, saved answers, editorial setting, mode, git commit, a snapshot of each system, and the rubric version each topic used.
- `topics[n]`: the question, reference, key points and facts; `runs[r]` with each system's answer, what it read, grades, scores, checks and metrics, the winner and rationale, and each other pair under `pairs`; `aggregate` with the topic's means.
- `summary`: per system means across topics, wins, similarity by section, gaps with intervals, and each other pair under `pairs`.
- `metrics`: the per-answer tests per system. `standard_similarity`: Full runs only.
- `errors`: topics that failed; resume with `--run-id`.
