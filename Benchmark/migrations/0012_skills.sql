-- Skills: named instructions a chat on the Ask screen can use. A chat's chosen skills are added to the answer
-- instruction of both RAG and the wiki (they never change what is searched). Optional: a chat starts with none.
create table if not exists ask.skills (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  description text not null default '',
  instructions text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table ask.chats add column if not exists skill_ids uuid[] not null default '{}';  -- empty = no skills
