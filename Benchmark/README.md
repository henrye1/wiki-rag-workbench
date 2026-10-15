# RAG vs Wiki Benchmark

This measures how closely the RAG API (`../Rag`) and the LLM Wiki API (`../Wiki`) answer the 26 topics in `Docs/IFRS9_Requirement_Query_Set_BULK_5.txt`. The reference is a human-written IFRS 9 assessment (a .docx kept in `Docs/`; set its path with `REFERENCE_DOCX` in `.env`). Claude (`claude-opus-5-5`) is the judge.

## Method
1. **Inputs.** Each topic's question is its title plus Q1..Qn. The same text goes to RAG `POST /collections/{c}/query` and Wiki `POST /wikis/{slug}/query`, for the RAG collection and wiki chosen for the run (`RAG_COLLECTION` and `WIKI_SLUG` for CLI runs). Both systems answer with the same Gemini model at temperature 0.1.
2. **Reference.** Each topic's reference is the first row of its table in the docx: tables 1–26 map to topics 1–26. `python -m bench.data` checks this mapping.
3. **Rubric.** Claude breaks each reference into atomic key points, once per topic, and tags each one:
   - `standard`: from IFRS 9/7 text
   - `beyond_standard`: practice, ITG or Basel guidance, examples

   Both systems only see the Standard, so they can't be expected to produce `beyond_standard` points.
4. **Judging (blind).** For each run, the two answers are labelled A and B in a seeded random order. Claude grades each key point for each answer as full, partial or missing, then gives:
   - a 0–10 similarity score per answer
   - contradictions with the reference
   - a winner
   - a rationale

   The labels are mapped back to rag and wiki afterwards.
5. **Scores per run.**
   - coverage % = (full + 0.5 × partial) / key points
   - standard-only coverage (the same, over `standard` points only)
   - similarity
   - winner

   Each topic gets the mean ± sd over its runs (default 3). The summary averages the topic means.

## Run
```powershell
cd Benchmark
python -m venv .venv; .venv\Scripts\pip install -r requirements.txt
copy .env.example .env          # set ANTHROPIC_API_KEY, RAG_API_KEY, WIKI_API_KEY
# start ../Rag (port 8000) and ../Wiki (port 8001) with their run.py
.venv\Scripts\python -m bench.data                       # check topic <-> reference mapping
.venv\Scripts\python -m bench.run --topics 2 --runs 1    # quick check
.venv\Scripts\python -m bench.run                        # full: 26 topics x 3 runs
.venv\Scripts\python -m bench.run --run-id <id>        # resume a stored run after an error
```

## Output: `bench.runs` (database)
One row per run: status, the uploaded inputs (query set, reference .docx), the run log, and `results` (JSON):
- `config`: judge model and effort, runs, seed, git commit, and the RAG collection and wiki compared, and a snapshot of each system (the collection's documents and chunk counts; Wiki page and source counts).
- `topics[n]`:
  - the question, reference and `key_points`
  - `runs[r]`: per system, the answer, sources, latency, per-point grades, similarity, coverage and contradictions; plus the winner, rationale and point notes
  - `aggregate`: mean ± sd per metric, win counts, and the hit rate for each key point
- `summary`: per system, similarity, coverage and standard-only coverage (mean ± sd across topics); wins per run; similarity by docx section.
- `errors`: topics that failed. Resume with `--run-id`.

**Saved answers.** "Use saved answers" (on by default; `USE_SAVED=false` for the CLI) lets the wiki also read relevant saved answers (synthesis pages filed with Save) in addition to its normal pages. Each run records the setting (`bench.runs.use_saved`, `config.use_saved_answers`; null for runs before it existed, which read every page), and each wiki answer records `saved_answers_read`, listed per topic on the run page.

**Rubric.** Claude's key points for each topic are built once per reference file (identified by its SHA-256), saved in `bench.rubrics`, and reused by every run with that file, so runs are scored against the same checklist. A different reference file gets its own rubric on its first run. Rebuild a rubric on purpose with the Benchmark page's **Rebuild** button or `python -m bench.rubric rebuild <sha256>` (same judge prompt; it replaces the saved key points, so later runs are not directly comparable with earlier ones). `python -m bench.rubric list` shows the saved rubrics; `python -m bench.rubric seed <run-id>` saves the key points an earlier run built.

Create the table once with `python -m bench.migrate` (Render runs it as a pre-deploy step). `python -m bench.import_results results/<dir>` imports runs saved as `results.json` by older versions.

## Cost
Roughly 26 key-point calls plus 78 judge calls with Claude Opus 5.5 at effort `high`, and 156 Gemini calls to the systems under test. Judge calls send a server-side refusal fallback (`fallbacks: "default"`); IFRS text shouldn't trigger it.
