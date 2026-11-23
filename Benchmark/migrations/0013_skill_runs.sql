-- Skill runs: a skill can carry questions. Run on the Ask screen asks each one as its own message in a new chat, then
-- writes a summary (the verdict) from the answers, one per side. A skill without questions works as before.
alter table ask.skills add column if not exists questions text[] not null default '{}';  -- in order; empty = no Run
alter table ask.skills add column if not exists summary text not null default '';        -- verdict instruction; empty = the default

-- A run's messages share run_id; its summary is a message of kind 'summary' (never used to rewrite follow-ups).
alter table ask.messages add column if not exists kind text not null default 'question' check (kind in ('question', 'summary'));
alter table ask.messages add column if not exists run_id uuid;
alter table ask.messages add column if not exists skill_id uuid;  -- the skill a run used (no FK: deleting a skill keeps the chat)
create unique index if not exists messages_one_summary_per_run on ask.messages (run_id) where kind = 'summary';
