-- ============================================================================
-- Raghad Outlet — private analytics (run once in Supabase → SQL Editor; safe to run again)
-- Stores anonymous, aggregate-friendly events only: no names, emails, phone numbers or IP addresses.
-- The website can only ADD events (track) and read a 0–100 ranking score per product (product_scores).
-- Raw events and all counts are readable only through admin_stats(), which needs the private admin key.
-- ============================================================================

create table if not exists public.events (
  id        bigserial primary key,
  at        timestamptz not null default now(),
  visitor   text not null,          -- random id kept in the browser (not a person)
  session   text not null,          -- random id per visit (30 min of inactivity ends it)
  kind      text not null,          -- pageview | product_view | engage | fav | unfav | rec_view | rec_click | search | filter
  handle    text,                   -- product id on the site, when the event is about a product
  route     text,                   -- page of the site (home, dresses-sp, item, …)
  ms        integer,                -- engaged milliseconds (engage events)
  meta      jsonb,                  -- small details: search term, filter, recommendation section/slot, landing, from-page
  device    text,                   -- mobile | tablet | desktop
  source    text,                   -- direct | google | social | other referral source group
  is_new    boolean not null default false   -- first visit of this browser
);
create index if not exists events_at_idx on public.events (at);
create index if not exists events_kind_at_idx on public.events (kind, at);
create index if not exists events_handle_idx on public.events (handle) where handle is not null;
alter table public.events enable row level security;          -- no policies: nobody reads or writes it directly
revoke all on public.events from anon, authenticated;

-- the only way the website writes: up to 40 events per call, each checked and size-limited
create or replace function public.track(p_events jsonb)
returns void language plpgsql security definer set search_path = public as $$
declare e jsonb; n int := 0; k text;
begin
  if jsonb_typeof(p_events) <> 'array' then return; end if;
  for e in select value from jsonb_array_elements(p_events) loop
    n := n + 1; exit when n > 40;
    k := e->>'kind';
    continue when k is null or k not in ('pageview','product_view','engage','fav','unfav','rec_view','rec_click','search','filter');
    continue when coalesce(e->>'visitor','') = '' or coalesce(e->>'session','') = '';
    continue when e ? 'meta' and length((e->'meta')::text) > 600;
    insert into public.events (visitor, session, kind, handle, route, ms, meta, device, source, is_new)
    values (left(e->>'visitor', 40), left(e->>'session', 40), k, left(e->>'handle', 120), left(e->>'route', 80),
            case when (e->>'ms') ~ '^\d{1,9}$' then least((e->>'ms')::int, 600000) else null end,
            case when jsonb_typeof(e->'meta') = 'object' then e->'meta' else null end,
            left(e->>'device', 10), left(e->>'source', 20), coalesce((e->>'isNew')::boolean, false));
  end loop;
end $$;
revoke all on function public.track(jsonb) from public;
grant execute on function public.track(jsonb) to anon, authenticated;

-- public ranking: a 0–100 score per product for sorting, never the counts behind it
create or replace view public.product_scores as
with win as (select now() - interval '30 days' as since),
v as (select handle, count(*) as views, count(distinct session) as uniq
      from public.events, win where kind = 'product_view' and at >= since and handle is not null group by handle),
t as (select handle, sum(ms)::numeric as total_ms, count(*) as n
      from public.events, win where kind = 'engage' and at >= since and handle is not null group by handle),
r as (select handle, count(*) as clicks from public.events, win where kind = 'rec_click' and at >= since and handle is not null group by handle),
f as (select handle, total::numeric as favs from public.fav_totals where total > 0),
allh as (select handle from v union select handle from f union select handle from r),
x as (
  select a.handle,
         coalesce(v.uniq, 0) as uniq, coalesce(v.views, 0) as views,
         coalesce(t.total_ms, 0) as total_ms,
         (coalesce(t.total_ms, 0) + 15000 * 3) / (coalesce(t.n, 0) + 3) as avg_ms,   -- smoothed: a few long visits can't dominate
         coalesce(f.favs, 0) as favs, coalesce(r.clicks, 0) as clicks
  from allh a left join v using (handle) left join t using (handle) left join f using (handle) left join r using (handle)),
p as (
  select handle, favs,
         percent_rank() over (order by uniq) as p_uniq, percent_rank() over (order by views) as p_views,
         percent_rank() over (order by avg_ms) as p_avg, percent_rank() over (order by total_ms) as p_total,
         percent_rank() over (order by favs) as p_favs, percent_rank() over (order by clicks) as p_clicks
  from x)
select handle,
       round((100 * (0.25 * p_uniq + 0.10 * p_views + 0.20 * p_avg + 0.15 * p_total + 0.25 * p_favs + 0.05 * p_clicks))::numeric, 1) as score,
       case when favs > 0 then round((100 * percent_rank() over (partition by favs > 0 order by favs))::numeric, 1) else null end as fav_score
from p;
grant select on public.product_scores to anon, authenticated;

-- favorite counts are private from now on (the site ranks by product_scores instead)
revoke select on public.fav_totals from anon, authenticated;

-- private admin key (only its SHA-256 is stored)
create table if not exists public.admin_keys (key_hash text primary key, note text, created_at timestamptz default now());
alter table public.admin_keys enable row level security;
revoke all on public.admin_keys from anon, authenticated;
-- the statistics open with the site's Admin passcode (a key derived from it); any older separate key is removed
delete from public.admin_keys where note is distinct from 'passcode';
insert into public.admin_keys (key_hash, note) values ('ca4a199e1782c9e60ebcd3739fb15d12bf287f5d138ed12f3a727c80ce346909', 'passcode') on conflict (key_hash) do nothing;

create or replace function public.admin_ok(p_key text) returns boolean language sql security definer set search_path = public stable as $$
  select exists (select 1 from public.admin_keys where key_hash = encode(sha256(convert_to(coalesce(p_key, ''), 'UTF8')), 'hex'));
$$;
revoke all on function public.admin_ok(text) from public, anon, authenticated;

-- everything the dashboard shows — people first (unique anonymous visitors), sessions and page views second
create or replace function public.admin_stats(p_key text, p_from timestamptz, p_to timestamptz)
returns jsonb language plpgsql security definer set search_path = public stable as $$
declare res jsonb; len interval := p_to - p_from;
begin
  if not public.admin_ok(p_key) then raise exception 'not authorized' using errcode = '42501'; end if;
  if len <= interval '0' or len > interval '400 days' then raise exception 'bad period'; end if;

  with ev0 as (
    select e.*,
           coalesce(e.meta->>'b', case when e.handle like 'md-%' then 'md' when e.handle like 'ef-%' then 'ef'
                                       when e.handle like 'rl-%' then 'rl' when e.handle like 'mc-%' then 'mc'
                                       when e.handle is not null then 'sp' end) as brand,
           e.meta->>'c' as cat
    from public.events e),
  ev as (select * from ev0 where at >= p_from and at < p_to),
  pv as (select * from ev0 where at >= p_from - len and at < p_from),
  -- every visitor's sessions (all time) to tell new from returning and measure return gaps
  vs as (select visitor, session, min(at) as t0 from ev0 group by visitor, session),
  vfirst as (select visitor, min(t0) as first_at,
                    (array_agg(t0 order by t0))[2] as second_at, count(*) as sessions_all from vs group by visitor),
  active as (select distinct visitor from ev),
  pactive as (select distinct visitor from pv),
  act as (select a.visitor, f.first_at, f.second_at, f.first_at >= p_from as is_new from active a join vfirst f using (visitor)),
  pact as (select a.visitor, f.first_at >= p_from - len as is_new from pactive a join vfirst f using (visitor)),
  eng as (select visitor, handle, brand, cat, sum(ms) as ms from ev where kind = 'engage' and handle is not null group by 1, 2, 3, 4),
  prod as (
    select h.handle,
           (select count(distinct visitor) from ev x where x.kind = 'product_view' and x.handle = h.handle) as uv,
           (select count(distinct visitor) from eng x where x.handle = h.handle and x.ms >= 10000) as engaged_uv,
           (select coalesce(sum(ms), 0) from eng x where x.handle = h.handle) as total_ms,
           (select count(distinct visitor) from eng x where x.handle = h.handle) as eng_uv,
           (select count(distinct visitor) from ev x where x.kind = 'fav' and x.handle = h.handle) as fav_uv,
           (select count(distinct x.visitor) from ev x join act a using (visitor) where x.kind = 'product_view' and x.handle = h.handle and not a.is_new) as ret_uv,
           (select count(distinct visitor) from pv x where x.kind = 'product_view' and x.handle = h.handle) as prev_uv,
           (select max(brand) from ev x where x.handle = h.handle) as brand,
           (select max(cat) from ev x where x.handle = h.handle) as cat
    from (select distinct handle from ev where handle is not null and kind in ('product_view','engage','fav')) h),
  grp as (select 'b' as dim, brand as k, visitor, kind, ms from ev where brand is not null and kind in ('product_view','engage','fav')
          union all
          select 'c', cat, visitor, kind, ms from ev where cat is not null and kind in ('product_view','engage','fav'))
  select jsonb_build_object(
    'from', p_from, 'to', p_to, 'firstEventAt', (select min(at) from public.events),
    'visitors', (select count(*) from act),
    'newVisitors', (select count(*) from act where is_new),
    'returningVisitors', (select count(*) from act where not is_new),
    'sessions', (select count(distinct session) from ev),
    'pageviews', (select count(*) from ev where kind = 'pageview'),
    'engagedVisitors', (select count(distinct visitor) from eng where ms >= 10000),
    'avgEngagePerVisitorMs', coalesce((select round(sum(ms)::numeric / nullif((select count(*) from act), 0)) from eng), 0),
    'return7', (select count(*) from act where second_at is not null and second_at - first_at <= interval '7 days'),
    'return30', (select count(*) from act where second_at is not null and second_at - first_at <= interval '30 days'),
    'prev', jsonb_build_object('visitors', (select count(*) from pact), 'newVisitors', (select count(*) from pact where is_new),
                               'returningVisitors', (select count(*) from pact where not is_new), 'sessions', (select count(distinct session) from pv)),
    'fixed', jsonb_build_object(
       'today', (select count(distinct visitor) from ev0 where at >= date_trunc('day', now() at time zone 'Asia/Riyadh') at time zone 'Asia/Riyadh'),
       'd7', (select count(distinct visitor) from ev0 where at >= now() - interval '7 days'),
       'd30', (select count(distinct visitor) from ev0 where at >= now() - interval '30 days'),
       'all', (select count(distinct visitor) from ev0)),
    'series', jsonb_build_object(
       'day', coalesce((select jsonb_agg(jsonb_build_object('d', d, 'v', v, 'n', n) order by d) from (
          select (at at time zone 'Asia/Riyadh')::date as d, count(distinct e.visitor) as v,
                 count(distinct e.visitor) filter (where (f.first_at at time zone 'Asia/Riyadh')::date = (e.at at time zone 'Asia/Riyadh')::date) as n
          from ev e join vfirst f using (visitor) group by 1) x), '[]'::jsonb),
       'week', coalesce((select jsonb_agg(jsonb_build_object('d', d, 'v', v) order by d) from (
          select date_trunc('week', at at time zone 'Asia/Riyadh')::date as d, count(distinct visitor) as v from ev group by 1) x), '[]'::jsonb),
       'month', coalesce((select jsonb_agg(jsonb_build_object('d', d, 'v', v) order by d) from (
          select date_trunc('month', at at time zone 'Asia/Riyadh')::date as d, count(distinct visitor) as v from ev group by 1) x), '[]'::jsonb)),
    'products', coalesce((select jsonb_agg(jsonb_build_object('h', handle, 'uv', uv, 'engagedUv', engaged_uv, 'totalMs', total_ms,
          'avgMs', case when eng_uv > 0 then round(total_ms::numeric / eng_uv) else 0 end, 'favUv', fav_uv,
          'retUv', ret_uv, 'prevUv', prev_uv, 'b', brand, 'c', cat) order by uv desc, total_ms desc)
       from (select * from prod order by uv desc, total_ms desc limit 500) p), '[]'::jsonb),
    'groups', coalesce((select jsonb_agg(jsonb_build_object('dim', dim, 'k', k, 'uv', uv, 'engagedUv', euv, 'avgMs', avgms, 'favUv', fuv)) from (
          select dim, k, count(distinct visitor) filter (where kind = 'product_view') as uv,
                 count(distinct visitor) filter (where kind = 'engage' and ms >= 10000) as euv,
                 coalesce(round(sum(ms) filter (where kind = 'engage')::numeric / nullif(count(distinct visitor) filter (where kind = 'engage'), 0)), 0) as avgms,
                 count(distinct visitor) filter (where kind = 'fav') as fuv
          from grp group by dim, k) x), '[]'::jsonb),
    'funnel', (select jsonb_build_object(
        'visitors', count(distinct visitor),
        'home', count(distinct visitor) filter (where kind = 'pageview' and route = 'home'),
        'category', count(distinct visitor) filter (where kind = 'pageview' and route ~ '^(dresses|bags|shoes|winter|all|discounts|recent|popular)'),
        'brand', count(distinct visitor) filter (where kind = 'pageview' and route ~ '^(dresses|bags|shoes|winter)-'),
        'product', count(distinct visitor) filter (where kind = 'product_view'),
        'favorite', count(distinct visitor) filter (where kind = 'fav')) from ev),
    'routes', coalesce((select jsonb_agg(jsonb_build_object('r', route, 'uv', uv) order by uv desc) from (
          select route, count(distinct visitor) as uv from ev where kind = 'pageview' and route is not null group by route order by 2 desc limit 40) x), '[]'::jsonb),
    'recos', coalesce((select jsonb_agg(jsonb_build_object('section', sec, 'h', handle, 'uv', uv) order by uv desc) from (
          select meta->>'section' as sec, handle, count(distinct visitor) as uv from ev where kind = 'rec_click' group by 1, 2 order by 3 desc limit 30) x), '[]'::jsonb),
    'recoTotals', (select jsonb_build_object(
          'lookSeen', count(distinct visitor) filter (where kind = 'rec_view' and meta->>'section' = 'look'),
          'lookClicked', count(distinct visitor) filter (where kind = 'rec_click' and meta->>'section' = 'look'),
          'alikeSeen', count(distinct visitor) filter (where kind = 'rec_view' and meta->>'section' = 'alike'),
          'alikeClicked', count(distinct visitor) filter (where kind = 'rec_click' and meta->>'section' = 'alike')) from ev),
    'sources', coalesce((select jsonb_object_agg(coalesce(source, 'direct'), n) from (
          select source, count(distinct visitor) as n from ev where kind = 'pageview' and meta->>'landing' = '1' group by source) x), '{}'::jsonb),
    'devices', coalesce((select jsonb_object_agg(coalesce(device, 'unknown'), n) from (
          select device, count(distinct visitor) as n from ev where kind = 'pageview' and meta->>'landing' = '1' group by device) x), '{}'::jsonb)
  ) into res;
  return res;
end $$;
revoke all on function public.admin_stats(text, timestamptz, timestamptz) from public;
grant execute on function public.admin_stats(text, timestamptz, timestamptz) to anon, authenticated;
