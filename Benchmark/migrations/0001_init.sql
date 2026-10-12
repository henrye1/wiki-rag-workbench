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
