-- How a wiki's answers choose the pages they read:
--   search_pick: a search score's top pages plus the model's picks from the page index, read at once (the first method)
--   browse: the model reads the page list, chooses pages, reads them and follows their links in rounds
-- The wikis that exist when this runs keep search_pick; a wiki created after it browses unless set otherwise.
alter table wiki.wikis add column if not exists answer_method text not null default 'search_pick'
  check (answer_method in ('search_pick', 'browse'));
alter table wiki.wikis alter column answer_method set default 'browse';
