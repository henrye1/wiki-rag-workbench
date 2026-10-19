-- Saved chats on the Ask screen. Each message records which side(s) were asked, the question as typed, the full
-- question actually searched (follow-ups are rewritten from earlier questions only), the Sources setting and the answers.
create schema if not exists ask;

create table if not exists ask.chats (
  id uuid primary key default gen_random_uuid(),
  title text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists ask.messages (
  id bigserial primary key,
  chat_id uuid not null references ask.chats(id) on delete cascade,
  seq int not null,
  question text not null,                 -- as typed
  searched text not null,                 -- the full question sent to RAG and/or the wiki
  mode text not null check (mode in ('rag', 'wiki', 'both')),
  sources text not null check (sources in ('standard', 'all')),
  rag_collection text,
  wiki_slug text,
  rag jsonb,                              -- {answer, sources, ms, error}
  wiki jsonb,                             -- {answer, pages, ms, error}
  created_at timestamptz not null default now(),
  unique (chat_id, seq)
);
create index if not exists messages_chat on ask.messages (chat_id, seq);
