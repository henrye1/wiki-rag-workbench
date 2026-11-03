-- An ingest whose pages still fail the schema's checks is held for review, not applied. The failures it was held for
-- are kept with its changeset, by page, and become each page's 'check_failures' flag when a reviewer applies it.
alter table wiki.changesets add column if not exists check_failures jsonb;
