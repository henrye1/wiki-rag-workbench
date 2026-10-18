-- Rubric review: you approve (or change) each topic's key points and its exact-match facts. Every change makes a new
-- version, kept in bench.rubric_versions; each run records the version of each topic's rubric it used.
-- Key point tags: standard (the Standard, Part A), supporting (documents published with it, Parts B and C),
-- beyond_standard (practice, regulation, opinion).
alter table bench.rubrics add column if not exists version int not null default 1;
alter table bench.rubrics add column if not exists reviewed_at timestamptz;        -- key points approved
alter table bench.rubrics add column if not exists facts jsonb;                    -- exact-match facts [{id, fact}]
alter table bench.rubrics add column if not exists facts_reviewed_at timestamptz;  -- facts approved

create table if not exists bench.rubric_versions (
  reference_sha256 text not null,
  topic_number int not null,
  version int not null,
  key_points jsonb not null,
  facts jsonb,
  reviewed_at timestamptz,
  facts_reviewed_at timestamptz,
  note text,
  created_at timestamptz not null default now(),
  primary key (reference_sha256, topic_number, version)
);

insert into bench.rubric_versions (reference_sha256, topic_number, version, key_points, facts, note, created_at)
select reference_sha256, topic_number, version, key_points, facts, 'as built', created_at from bench.rubrics
on conflict do nothing;
