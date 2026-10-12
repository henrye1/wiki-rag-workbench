# Deploying to Render

`render.yaml` is a Render Blueprint for three services, all in the Frankfurt region:

| Service | Type | What it runs | Reachable from |
| --- | --- | --- | --- |
| `workbench` | Web service (public) | Angular UI, BFF and the Benchmark runner (`UI/Dockerfile`) | The internet, behind the shared-password login |
| `rag` | Private service | RAG API (`Rag/Dockerfile`) | `workbench` only |
| `wiki` | Private service | Wiki API (`Wiki/Dockerfile`) | `workbench` only |

The database is a **Supabase Cloud** project. RAG uses the `public` tables, Wiki uses the `wiki` schema, and Benchmark uses the `bench` schema. Migrations run automatically before each deploy.

No data is copied from your machine: upload documents and benchmark files through the UI after deploying.

## 1. Create the database (Supabase)

1. At [supabase.com](https://supabase.com), create a project in **Central EU (Frankfurt)** so it sits close to the Render services. Save the database password.
2. Go to **Connect**, then **Session pooler**, and copy the URI:
   ```
   postgresql://postgres.<project-ref>:<password>@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
   ```
   Append `?sslmode=require`. This is your `DATABASE_URL`.
   - Use the **session** pooler (port 5432). The direct connection is IPv6-only, which Render can't reach. The transaction pooler (port 6543) breaks psycopg's prepared statements.
3. The `vector` extension is created by the migrations. You don't need to enable it by hand.

## 2. Create the Blueprint (Render)

1. Push this repo to GitHub (already done: `henrye1/wiki-rag-workbench`).
2. In Render, go to **New → Blueprint**, pick the repo, and keep the default `render.yaml`.
3. Render asks for the secrets marked `sync: false`:

| Service | Variable | Value |
| --- | --- | --- |
| workbench | `DATABASE_URL` | The Supabase session-pooler URI from step 1 |
| workbench | `ANTHROPIC_API_KEY` | The Claude API key used by the benchmark judge |
| workbench | `UI_PASSWORD` | The shared login password for testers |
| rag, wiki | `DATABASE_URL` | The same URI |
| rag, wiki | `GEMINI_API_KEY` | Your Google AI Studio key |

Everything else is wired automatically:
- The services' `API_KEY`s are generated, and the workbench reads them from `rag` and `wiki`.
- The private addresses (`RAG_URL`, `WIKI_URL`) are filled in from the services.
- `SESSION_SECRET` is generated.
- `DB_POOL_MAX=4` comes from the `workbench-shared` group.

4. Click **Apply**. The first deploy builds three Docker images, which takes about 5 to 10 minutes. The UI image builds Angular inside Docker.

## 3. First use

1. Open `https://workbench-<suffix>.onrender.com` and log in with `UI_PASSWORD`.
2. Check that **Home** shows RAG, Wiki and Benchmark as healthy.
3. **Documents:** upload `13 - IFRS 9 Financial Instruments (Assessment).pdf`.
4. **Wiki:** create a wiki with slug `ifrs9` and ingest the same PDF in auto mode. Follow the job until it finishes.
5. **Benchmark → New run:**
   - Upload the reference assessment (.docx) and the query set (.txt).
   - Set the topics (for example `2`), the runs and the wiki (`ifrs9`), then click Start.
   - Later runs reuse the last uploaded files unless you upload new ones.
   - Results, inputs and the log are stored in `bench.runs`.

## Costs

- **Render:** three services on the `0.5c-512mb` (Starter) plan cost about $7 a month each. Private services can't use the free plan.
- **Supabase:** the free tier is enough. Free projects pause after a week without activity, so upgrade the project or resume it from the dashboard when needed.
- **Usage costs:**
  - Gemini: ingestion and every query.
  - Claude: the judge in benchmark runs. A full run is about 100 Opus calls.

## Operations

- **Redeploys:**
  - Each push to `main` redeploys every service (Render auto-deploy, on by default; turn it off per service if you prefer manual deploys).
  - Migrations run as `preDeployCommand`.
- **Benchmark runs during a redeploy:**
  - Restarting the workbench kills a running benchmark.
  - About 2 minutes later the run shows as **interrupted**. Use **Resume** to continue it; topics already judged are kept.
- **Bulk runs** (RAG) are held in workbench memory, so a redeploy loses them. Re-run if needed.
- **Wiki viewer:** reachable only through the workbench at `/view/...`, behind the login. The Wiki API itself is private.
- **Logs:** the Render dashboard shows each service's logs. Benchmark subprocess output appears in the workbench logs.
- **Memory:** if a large PDF ingest runs out of memory on RAG or Wiki, raise that service's plan to `1c-2g` in `render.yaml` or in the dashboard.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Pre-deploy fails with `could not translate host name` / `Network is unreachable` | You used the direct connection URL. Switch to the session pooler URI. |
| `DATABASE_URL is not a valid connection string` | The value isn't a `postgresql://` URI. Paste only the URI, without the `DATABASE_URL=` prefix. Paste the password as-is (no percent-encoding); quotes, spaces and special characters such as `%` are handled automatically. |
| `prepared statement ... already exists` | You used the transaction pooler (port 6543). Use the session pooler on port 5432. |
| `remaining connection slots are reserved` / pool timeouts | Lower `DB_POOL_MAX` in the `workbench-shared` group, or raise the Supabase pool size. |
| Home shows RAG/Wiki down | Check that the private services are live. `RAG_URL`/`WIKI_URL` must be the `host:port` Render provides; the scheme is added automatically. |
| Benchmark: "Upload the reference assessment…" | The first run needs both files. |
| Benchmark run fails at once | Open the run's log. A mismatch between the topics and the docx headings, or a missing `ANTHROPIC_API_KEY`, are the usual causes. |
| Bulk: "No default query set on this server" | Upload a query-set file. The default lives only in the local `Docs/` folder. |

## Testing the images locally

```bash
docker build -f Rag/Dockerfile -t wb-rag .
docker build -f Wiki/Dockerfile -t wb-wiki .
docker build -f UI/Dockerfile -t wb-ui .
```

Run each image with `PORT`, `DATABASE_URL` and the keys set. From a container, local Supabase is at `host.docker.internal:54322`. Put the containers on one Docker network and set `RAG_URL=rag:10000` and `WIKI_URL=wiki:10000`.
