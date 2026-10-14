-- Saved rubrics: the key points Claude makes from each topic's reference answer, built once per reference file
-- (identified by the file's SHA-256) and reused by every run with that file, so runs are scored against the same checklist
create table if not exists bench.rubrics (
  reference_sha256 text not null,
  topic_number int not null,
  reference_name text,
  topic_title text not null,
  key_points jsonb not null,
  key_points_usage jsonb,
  judge_model text,
  source_run text,  -- the run it was built in or copied from ("rebuild" when rebuilt on purpose)
  created_at timestamptz not null default now(),
  primary key (reference_sha256, topic_number)
);
