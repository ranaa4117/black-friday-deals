-- Raghad Outlet: anonymous product-view counts (no customer identity is stored).
-- Run once in Supabase → SQL Editor. Safe to run again.
create table if not exists public.product_views (
  handle  text primary key,
  total   bigint not null default 0,
  last_at timestamptz not null default now()
);
alter table public.product_views enable row level security;   -- no direct reads/writes from the website

create or replace function public.add_view(p_handle text)
returns void language sql security definer set search_path = public as $$
  insert into public.product_views (handle, total, last_at)
  values (left(p_handle, 120), 1, now())
  on conflict (handle) do update set total = product_views.total + 1, last_at = now();
$$;
revoke all on function public.add_view(text) from public;
grant execute on function public.add_view(text) to anon;

create or replace view public.view_totals as
  select handle, total, last_at from public.product_views;
grant select on public.view_totals to anon;
