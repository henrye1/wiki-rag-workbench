-- Exact-match facts: the judge call that made each topic's list (its tokens and model), like the key points.
alter table bench.rubrics add column if not exists facts_usage jsonb;
alter table bench.rubrics add column if not exists facts_model text;
