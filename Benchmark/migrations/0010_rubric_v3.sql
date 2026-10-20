-- Suggested rubric changes (tags with the backing paragraph, list merges, a hard-fact list), stored with each topic until
-- you accept or reject them on the Rubric review screen. Accepting and saving makes a new version; nothing else changes.
alter table bench.rubrics add column if not exists suggestions jsonb;
