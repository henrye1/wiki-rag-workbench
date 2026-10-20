-- Reference memos are shown by a neutral label you can rename ("Reference memo 1"), never by their file name. Keyed by
-- the file's SHA-256, so existing rubrics and runs stay linked as they are.
-- tag_sources: the source documents you ticked for the rubric tag check (null = all); used by the next Suggest changes.
create table if not exists bench.references (
  reference_sha256 text primary key,
  label text not null,
  tag_sources jsonb,
  created_at timestamptz not null default now()
);

insert into bench.references (reference_sha256, label, created_at)
select sha, 'Reference memo ' || row_number() over (order by first_seen), first_seen
from (select sha, min(first_seen) as first_seen
      from (select encode(sha256(reference), 'hex') as sha, min(created_at) as first_seen from bench.runs where reference is not null group by 1
            union all
            select reference_sha256, min(created_at) from bench.rubrics group by 1) s
      group by sha) x
on conflict do nothing;

-- The documents a topic's approved tags were checked against, kept with each version
alter table bench.rubrics add column if not exists tag_sources jsonb;
alter table bench.rubric_versions add column if not exists tag_sources jsonb;
