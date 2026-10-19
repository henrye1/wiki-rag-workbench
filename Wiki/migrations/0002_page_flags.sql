-- Flags on pages, e.g. a saved answer whose cited paragraphs were written up differently by a later upload
create table if not exists wiki.page_flags (
  page_id uuid not null references wiki.pages(id) on delete cascade,
  kind text not null,                       -- 'needs_checking'
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (page_id, kind)
);
