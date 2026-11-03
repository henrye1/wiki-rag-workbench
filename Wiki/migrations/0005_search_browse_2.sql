-- A fourth way for answers to choose the pages they read:
--   search_browse_2: search_browse, except that "enough" is judged only after the pages chosen have been read (a
--   round that reads pages is always followed by another), and each round's choices and reasons are kept in the log
alter table wiki.wikis drop constraint if exists wikis_answer_method_check;
alter table wiki.wikis add constraint wikis_answer_method_check
  check (answer_method in ('search_pick', 'browse', 'search_browse', 'search_browse_2'));
