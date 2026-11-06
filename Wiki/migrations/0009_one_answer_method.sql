-- One way of choosing the pages an answer reads remains: search_browse (a search shortlist beside the page list, then
-- rounds of reading and following links). The wikis that used the other methods are gone. Why the column stays: a
-- service still running the code before this change reads it; it can be dropped once every service runs this code.
update wiki.wikis set answer_method = 'search_browse' where answer_method <> 'search_browse';
alter table wiki.wikis drop constraint if exists wikis_answer_method_check;
alter table wiki.wikis add constraint wikis_answer_method_check check (answer_method = 'search_browse');
alter table wiki.wikis alter column answer_method set default 'search_browse';
