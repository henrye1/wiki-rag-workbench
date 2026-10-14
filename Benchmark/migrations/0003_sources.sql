-- Which sources both systems may use in a run: 'standard' (Part A only) or 'all' (Parts A, B and C)
alter table bench.runs add column if not exists sources text;
-- Runs from before the switch had no restriction
update bench.runs set sources = 'all' where sources is null;
