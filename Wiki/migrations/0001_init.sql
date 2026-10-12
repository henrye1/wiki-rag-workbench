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
