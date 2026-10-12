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
