# IFRS Workbench UI

One UI for the RAG API, the LLM Wiki API and the Benchmark.

- `web/`: Angular 22 single-page app (Material, signals, standalone components).
- `server/`: a small FastAPI backend-for-frontend (BFF).
  - Holds the API keys, so they never reach the browser.
  - Proxies `/api/rag/*` → RAG and `/api/wiki/*` → Wiki.
  - Runs RAG bulk jobs in the background.
  - Starts and reads Benchmark runs.
  - Serves the built SPA.

## Run
Prerequisites: Supabase running, `Rag/run.py` (port 8000) and `Wiki/run.py` (port 8001) started.

```powershell
# 1. BFF (http://127.0.0.1:8080)
cd UI\server
python -m venv .venv; .venv\Scripts\pip install -r requirements.txt
copy .env.example .env        # RAG_API_KEY / WIKI_API_KEY = API_KEY values from Rag/.env and Wiki/.env
.venv\Scripts\python run.py

# 2a. Use the built app: build once, then open http://127.0.0.1:8080
cd UI\web
npm install
npm run build

# 2b. Or develop with hot reload on http://localhost:4200 (proxies /api to :8080)
npm start
```

## Screens
| Screen | What it does |
|---|---|
| Home | Health and counts for RAG, Wiki and Benchmark |
| Ask | One question to RAG and Wiki at once, both answers streaming side by side. **Sources**: Standard only (Part A) or All (Parts A, B and C), for both. Click a `[5.5.3]` citation to see the source paragraph, or a wiki link to preview the page. A Wiki answer can be saved as a page. |
| RAG documents | Create, rename and delete collections; upload (drag and drop) into the chosen collection or delete documents, with chunk counts |
| Bulk requirements | Runs the query set through RAG `/collections/{c}/bulk` on the chosen collection as a background job, then shows each topic's block, rule-check issues, cited paragraphs and a copy-markdown button |
| Wiki | Create or select a wiki, then use these tabs: Pages (browse, backlinks, sources, version diff and revert); Sources & ingest (file, URL or text; auto or review); Jobs; Changesets (diffs, apply or discard); Lint (structural, LLM, fix); Graph (link map); Schema & export |
| Ask | Chats, saved automatically (list down the side; rename, New chat, Delete; reopen and carry on). Each message asks **RAG only**, **Wiki only** or **Both** (side by side) with its own **Sources** setting. A follow-up is rewritten into a full question from the chat's earlier questions only (at most `ASK_HISTORY_QUESTIONS`, default 6; never the answers), shown as an editable *Searched for*; RAG and the wiki receive only that full question. **Create synthesis** drafts one summary of the chat from its wiki answers only (RAG-only messages are skipped; greyed out without wiki answers), recording the questions, dates and Sources, using only citations from those answers and running the citation check; you edit it, it is checked again, and nothing goes into the wiki until **Save**. Deleting a chat never deletes a synthesis page. Needs `GEMINI_API_KEY` on the Workbench server. |
| Benchmark | List runs and start new ones (RAG collection vs wiki, **Sources** the same for both) with live progress; the saved **Rubric** per reference file, with a Rebuild button; run explorer (summary, by-section chart, topic table sortable by gap); topic drill-down (key points × grades per run, answers side by side, judge's reasoning); compare two runs |

## BFF endpoints
- `GET /api/status`: health and counts.
- `/api/rag/{path}` and `/api/wiki/{path}`: proxies (JSON, multipart, SSE, downloads).
- `POST/GET /api/bulk`, `GET /api/bulk/{id}`: bulk runs. These are kept in memory until the BFF restarts.
- `GET/POST /api/bench/runs`, `GET/DELETE /api/bench/runs/{id}`, `GET /api/bench/runs/{id}/status`, `POST /api/bench/runs/{id}/resume`: benchmark runs, stored in `bench.runs`. POST takes multipart `reference` (.docx) and `query_set` (.txt), both optional after the first run (the last uploaded files are reused), plus `topics`, `runs` and `wiki`. The CLI (`bench.run --run-id`) runs as a subprocess.

## Sharing with a tester (Cloudflare quick tunnel)
1. Set `UI_PASSWORD` (and `SESSION_SECRET`) in `UI/server/.env`, then restart the BFF. With a password set, every `/api` and `/view` request needs a login; the page itself shows a sign-in screen.
2. Build the app (`npm run build` in `UI/web`) and keep Supabase, RAG, Wiki and the BFF running.
3. Start the tunnel; no Cloudflare account is needed:
   ```powershell
   & "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --no-autoupdate --url http://127.0.0.1:8080
   ```
   It prints a `https://<random>.trycloudflare.com` URL. Send that URL and the password to the tester.
4. To stop sharing, close cloudflared (Ctrl+C). The URL changes every time the tunnel starts.

Limits:
- Your machine must stay on with every service running.
- Cloudflare cuts off any single request after about 100 s; streaming answers and background jobs aren't affected.
- Quick tunnels are for testing only. For a stable URL, use a named tunnel on your own domain with Cloudflare Access.

## Notes
- The login is a single shared password: anyone who has it has full access.
- "Public viewer ↗" opens the Wiki API's server-rendered viewer, proxied through the BFF.
