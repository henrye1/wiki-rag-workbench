-- Whether the wiki also read saved answers (synthesis pages filed with Save) in a run. Null: older runs, before the setting.
alter table bench.runs add column if not exists use_saved boolean;
