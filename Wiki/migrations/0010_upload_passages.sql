-- Each upload keeps its passages, in order, exactly as they were read (the sections the ingest writes from), so an
-- upload can be run again against the current wiki without its original file, and an upload waiting its turn can be
-- put back in the queue after a restart. Sources uploaded before this have none: those need their file again.
alter table wiki.sources add column if not exists sections jsonb;
