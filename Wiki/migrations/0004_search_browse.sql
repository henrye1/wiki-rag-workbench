-- A third way for answers to choose the pages they read:
--   search_browse: a search of every page's text (keywords, labels as written, and meaning) gives a shortlist with
--   scores; the model sees it beside the page list, chooses pages, reads them and follows their links in rounds
-- The wikis that exist when this runs keep their method; a wiki created after it uses search_browse unless set otherwise.
alter table wiki.wikis drop constraint if exists wikis_answer_method_check;
alter table wiki.wikis add constraint wikis_answer_method_check
  check (answer_method in ('search_pick', 'browse', 'search_browse'));
alter table wiki.wikis alter column answer_method set default 'search_browse';

-- The shortlist: every page whose text matches the question by its labels and numbers (each term with a digit in it,
-- matched as written), by its words (full-text, OR'ed) or by its meaning (cosine), best chunk per page, the three
-- ranked lists fused with RRF as in search_pages. A label has its own list, weighted label_weight times the others,
-- so that the passage holding a label the question names is not outweighed by pages matching its common words. Each page says how it was found (its best rank in each list) and the passage that matched.
-- Synthesis pages are never listed.
drop function if exists wiki.shortlist_pages(uuid, text, vector, int, int);
drop function if exists wiki.shortlist_pages(uuid, text, vector, int, int, float);
create function wiki.shortlist_pages(
  p_wiki_id uuid,
  query_text text,
  query_embedding vector(768),
  match_count int,
  rrf_k int default 50,
  label_weight float default 3
)
returns table (slug text, title text, type text, score float, label_rank int, keyword_rank int, meaning_rank int, excerpt text)
language sql stable
set search_path = wiki, public, extensions
as $$
with q as (
  select nullif(replace(plainto_tsquery('english', query_text)::text, '&', '|'), '')::tsquery as tsq,
    nullif(replace(plainto_tsquery('english', coalesce((
      select string_agg(rtrim(m[1], '.'), ' ') from regexp_matches(query_text, '([[:alnum:].()-]*[0-9][[:alnum:].()-]*)', 'g') as m
    ), ''))::text, '&', '|'), '')::tsquery as lsq
),
chunks as (
  select c.id, c.page_id, c.content, c.fts, c.embedding
  from wiki.page_chunks c join wiki.pages p on p.id = c.page_id
  where c.wiki_id = p_wiki_id and p.type <> 'synthesis'
),
labels as (
  select c.id, row_number() over (order by ts_rank_cd(c.fts, q.lsq) desc) as rank_ix
  from chunks c, q
  where q.lsq is not null and c.fts @@ q.lsq
  order by rank_ix limit match_count * 4
),
full_text as (
  select c.id, row_number() over (order by ts_rank_cd(c.fts, q.tsq) desc) as rank_ix
  from chunks c, q
  where q.tsq is not null and c.fts @@ q.tsq
  order by rank_ix limit match_count * 4
),
semantic as (
  select c.id, row_number() over (order by c.embedding <=> query_embedding) as rank_ix
  from chunks c
  order by rank_ix limit match_count * 4
),
hits as (
  select id, rank_ix as lb, null::bigint as kw, null::bigint as mn from labels
  union all select id, null, rank_ix, null from full_text
  union all select id, null, null, rank_ix from semantic
),
per_chunk as (
  select id, min(lb) as lb, min(kw) as kw, min(mn) as mn from hits group by id
),
scored as (
  select c.page_id, c.content, h.lb, h.kw, h.mn,
    coalesce(label_weight / (rrf_k + h.lb), 0.0) + coalesce(1.0 / (rrf_k + h.kw), 0.0) + coalesce(1.0 / (rrf_k + h.mn), 0.0) as score
  from per_chunk h join chunks c on c.id = h.id
),
best as (
  select distinct on (page_id) page_id, content, score from scored order by page_id, score desc
),
ranks as (
  select page_id, min(lb)::int as lb, min(kw)::int as kw, min(mn)::int as mn from scored group by page_id
)
select p.slug, p.title, p.type, b.score, r.lb, r.kw, r.mn,
  case when q.lsq is not null and to_tsvector('english', b.content) @@ q.lsq
       then ts_headline('english', b.content, q.lsq, 'MaxWords=45, MinWords=20, MaxFragments=2, FragmentDelimiter=" … "')
       when q.tsq is not null and to_tsvector('english', b.content) @@ q.tsq
       then ts_headline('english', b.content, q.tsq, 'MaxWords=45, MinWords=20, MaxFragments=2, FragmentDelimiter=" … "')
       else left(b.content, 300) end
from best b join ranks r on r.page_id = b.page_id join wiki.pages p on p.id = b.page_id, q
order by b.score desc
limit match_count;
$$;
