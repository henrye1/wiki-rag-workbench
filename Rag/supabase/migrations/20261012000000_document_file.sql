-- The original uploaded file in Supabase Storage: {bucket, path, content_type, size}, or null when not stored
alter table public.documents add column if not exists file jsonb;
