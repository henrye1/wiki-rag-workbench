-- The paragraphs of a source whose write-up a page holds: what an upload routed to the page (or, once a page is split,
-- what each piece took of them). The page checks read it, so a paragraph cited on a page only in passing is checked on
-- its own page. A changeset carries it per op, by source slug, until it is applied. Null: not recorded (a page written
-- before this was kept, or one that cites the source without holding any of its write-ups).
alter table wiki.page_sources add column if not exists held text[];
alter table wiki.changeset_ops add column if not exists holds jsonb;
