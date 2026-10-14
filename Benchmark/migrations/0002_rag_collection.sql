-- Which RAG collection a run compares with its wiki
alter table bench.runs add column if not exists rag_collection text;
-- Runs from before RAG collections searched every RAG document; those all now sit in the "ifrs9" collection
update bench.runs set rag_collection = 'ifrs9'
where rag_collection is null and exists (select 1 from public.collections where slug = 'ifrs9');
