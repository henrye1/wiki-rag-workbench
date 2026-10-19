-- Quick (default): answers, the existing grading and the answer checks; Full: also faithfulness and context recall.
-- use_batch: grading through the Message Batches API (half price), falling back to the normal API.
alter table bench.runs add column if not exists mode text;
alter table bench.runs add column if not exists use_batch boolean;
