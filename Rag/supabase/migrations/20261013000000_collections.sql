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
