# RAG API

FastAPI + Gemini + local Supabase (pgvector). Hybrid search (vector + full-text, RRF). Built for IFRS standards: the PDF parser splits by IFRS paragraph number (5.5.3, B5.5.17, Appendix A terms) and keeps editorial text ([Refer], [Note], IFRIC boxes) apart from the binding text.

## Setup
Needs Docker Desktop + Supabase CLI (`npx supabase`).

```powershell
cd Rag
npx supabase init          # once; keep existing supabase/migrations
npx supabase start         # applies supabase/migrations, prints DB URL
python -m venv .venv; .venv\Scripts\pip install -r requirements.txt
copy .env.example .env     # set API_KEY, GEMINI_API_KEY
.venv\Scripts\python run.py   # not uvicorn directly: Windows needs a selector event loop for psycopg async
```
Documents live in **collections** (like wikis): create one first (`POST /collections`, or the UI's RAG documents page); every upload and question names its collection. Swagger: http://127.0.0.1:8000/docs. Postman: import `postman/RAG_API.postman_collection.json`, set collection vars `apiKey` and `collection`. All endpoints except `/health` need header `X-API-Key`.

Schema change: edit migration, then `npx supabase db reset` (wipes data). `EMBED_DIM` must match `vector(768)`.

## Endpoints
| Method | Path | Notes |
|---|---|---|
| GET / POST | `/collections` | list (document and chunk counts) / create `{slug, name, description?}` |
| PATCH / DELETE | `/collections/{c}` | rename `{name?, slug?, description?}` / delete with its documents, chunks and stored files (a stored file another document still points to is kept) |
| POST | `/collections/{c}/documents` | multipart `file` (.pdf/.txt/.md) into collection `c`. IFRS PDFs auto-detected; others chunked generically. 409 if already in that collection. |
| GET | `/collections/{c}/documents` | the collection's documents w/ chunk counts (`GET /documents`: all collections) |
| DELETE | `/documents/{id}` | removes doc + chunks, and its stored file unless another document points to it |
| GET | `/chunks?para_ref=5.5.3&collection=c` | look up a paragraph by reference (`collection` optional); editorial notes are left out |
| POST | `/collections/{c}/query` | `{question, include_editorial?, sources?, retrieval?}` → `{answer, citations[]}`, searching only collection `c`; `TOP_K` passages (a setting); `sources`: `all` (default) or `standard` (Part A types only); `retrieval`: `whole` (default) or `per_question` (one search per numbered question, as the bulk run does) |
| POST | `/collections/{c}/query/stream` | same body; SSE events `token` (JSON string), `citations`, `done` |
| POST | `/collections/{c}/bulk` | multipart `file` = query-set (`TOPIC n of N:` blocks); `?topics=1&topics=3` to subset, `?revise=false` to skip the self-check revision pass. JSON per topic: prose, source list, not addressed, word count, rendered markdown, citations, `draft_issues`/`issues` (rule checks) |

Source types: `standard`, `appendix_a`, `appendix_b`, `general` (binding/default) · `example`, `implementation_guidance`, `basis_for_conclusions`, `dissenting_opinion` (Parts B and C, recognised by their IE / IG / BC… / DO numbering; searched by default, labelled by kind) · `note`, `intro`, `appendix_c`, `back_matter` (excluded unless `include_editorial`). An upload whose layout is not recognised is chunked page by page and returns `warnings`.

## Examples
```powershell
$h = @{ "X-API-Key" = "change-me" }
curl.exe -H "X-API-Key: change-me" -F "file=@../Docs/13 - IFRS 9 Financial Instruments (Assessment).pdf" http://127.0.0.1:8000/collections/ifrs9/documents
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/collections/ifrs9/query -Headers $h -ContentType application/json -Body '{"question":"When is the loss allowance measured at lifetime expected credit losses?"}'
curl.exe -N -H "X-API-Key: change-me" -H "Content-Type: application/json" -d '{\"question\":\"Define credit loss\"}' http://127.0.0.1:8000/collections/ifrs9/query/stream
curl.exe -H "X-API-Key: change-me" -F "file=@../Docs/IFRS9_Requirement_Query_Set_BULK_5.txt" "http://127.0.0.1:8000/collections/ifrs9/bulk?topics=1" -o topic1.json
```

## Layout
```
run.py                 launcher (Windows-safe event loop)
app/main.py            app, API-key auth, lifespan (DB pool)
app/config.py          settings from .env
app/llm.py             Gemini embed/generate/stream + retry
app/retrieval.py       hybrid_search call, context formatting, citations
app/prompts.py         system prompts + bulk JSON schema
app/bulk.py            query-set parser + per-topic retrieval/generation
app/ingest/pdf_ifrs.py layout-aware IFRS PDF parser
app/ingest/text.py     generic chunker (`CHUNK_MAX_WORDS` windows, 50-word overlap)
app/files.py           removes a deleted document's stored file unless another document holds it
app/ingest/pipeline.py parse → embed → insert
supabase/migrations/   tables, indexes, hybrid_search()
postman/               Postman collection
```
