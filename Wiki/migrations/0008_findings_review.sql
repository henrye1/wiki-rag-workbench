-- The review step with a named actor (schema: Contradictions and updates; Workflow: Answer and check). A client
-- statement checked against the wiki is recorded as a finding: the statement, its verdict (one of the schema's
-- Client-statement verdicts), the clauses and quotes it rests on, and what the checks of it found. It is closed only by
-- a named reviewer, whose name, decision and note are recorded with it; it never changes a page.
create table if not exists wiki.findings (
  id uuid primary key default gen_random_uuid(),
  wiki_id uuid not null references wiki.wikis(id) on delete cascade,
  statement text not null,
  verdict text not null,
  clauses jsonb not null default '[]'::jsonb,       -- [{"citation": "[[source-...|<clause>]]", "quote": "..."}]
  reasoning text not null default '',
  check_failures jsonb not null default '[]'::jsonb, -- what the checks of the verdict still found
  sources text not null default 'all',
  pages_read jsonb not null default '[]'::jsonb,
  status text not null default 'open' check (status in ('open', 'closed')),
  reviewer text,
  decision text,
  note text,
  reviewed_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists findings_wiki on wiki.findings (wiki_id, created_at desc);

-- A changeset applied or discarded by a named reviewer: who, and when. A held upload (one with check failures) is
-- applied only by a named reviewer. Null: applied or discarded without one (before this, or an upload that passed).
alter table wiki.changesets add column if not exists reviewer text;
alter table wiki.changesets add column if not exists reviewed_at timestamptz;
