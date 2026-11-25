-- ============================================================================
-- Raghad Outlet — Sephora USA snapshots (run once in Supabase → SQL Editor; safe to run again)
-- Sephora blocks automatic servers, so the Claude browser on the owner's computer reads Sephora's public pages
-- and uploads what it read here. The site's updater then builds the Makeup section from these snapshots.
-- Only public Sephora content is stored (offers, campaign pages, sale listings). No personal data.
-- Writing needs the private upload key (only its SHA-256 is stored). Reading is public, like the pages themselves.
-- ============================================================================

create table if not exists public.sephora_snap (
  id     bigserial primary key,
  at     timestamptz not null default now(),
  kind   text not null,            -- content | list | product
  label  text not null,            -- which page (beauty-offers, cyber-week-deals, sale-makeup, P526571 …)
  url    text,
  data   jsonb not null
);
create index if not exists sephora_snap_label_at on public.sephora_snap (kind, label, at desc);
alter table public.sephora_snap enable row level security;
revoke all on public.sephora_snap from anon, authenticated;

create table if not exists public.sephora_keys (key_hash text primary key, note text, created_at timestamptz default now());
alter table public.sephora_keys enable row level security;
revoke all on public.sephora_keys from anon, authenticated;
insert into public.sephora_keys (key_hash, note)
values ('a7652d886399d588d61580fed4ad111d571eadf694188674213b333fdd32a998', 'scheduled Sephora reader') on conflict (key_hash) do nothing;

-- upload one page (needs the private key); old copies of the same page are trimmed after 3 days
create or replace function public.sephora_put(p_key text, p_kind text, p_label text, p_url text, p_data jsonb)
returns jsonb language plpgsql security definer set search_path = public as $$
begin
  if not exists (select 1 from public.sephora_keys where key_hash = encode(sha256(convert_to(coalesce(p_key, ''), 'UTF8')), 'hex'))
    then raise exception 'not authorized' using errcode = '42501'; end if;
  if p_kind not in ('content', 'list', 'product') then raise exception 'bad kind'; end if;
  if length(p_label) > 120 or p_label !~ '^[A-Za-z0-9._-]+$' then raise exception 'bad label'; end if;
  if p_url is null or p_url !~ '^https://www\.sephora\.com/' then raise exception 'not a Sephora page'; end if;
  if pg_column_size(p_data) > 3000000 then raise exception 'too large'; end if;
  insert into public.sephora_snap (kind, label, url, data) values (p_kind, p_label, left(p_url, 400), p_data);
  delete from public.sephora_snap where kind = p_kind and label = p_label and at < now() - interval '3 days'
    and id not in (select id from public.sephora_snap where kind = p_kind and label = p_label order by at desc limit 3);
  return jsonb_build_object('ok', true, 'at', now());
end $$;
revoke all on function public.sephora_put(text, text, text, text, jsonb) from public;
grant execute on function public.sephora_put(text, text, text, text, jsonb) to anon, authenticated;

-- the newest copy of every page (public: it is Sephora's own public content)
create or replace function public.sephora_latest(p_kind text default null)
returns table (kind text, label text, url text, at timestamptz, data jsonb)
language sql security definer set search_path = public stable as $$
  select distinct on (s.kind, s.label) s.kind, s.label, s.url, s.at, s.data
  from public.sephora_snap s where p_kind is null or s.kind = p_kind
  order by s.kind, s.label, s.at desc, s.id desc;
$$;
revoke all on function public.sephora_latest(text) from public;
grant execute on function public.sephora_latest(text) to anon, authenticated;

notify pgrst, 'reload schema';
