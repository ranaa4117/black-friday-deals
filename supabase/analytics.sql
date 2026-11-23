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
insert into public.admin_keys (key_hash, note) values ('ADMIN_KEY_HASH', 'owner') on conflict do nothing;

create or replace function public.admin_ok(p_key text) returns boolean language sql security definer set search_path = public stable as $$
  select exists (select 1 from public.admin_keys where key_hash = encode(sha256(convert_to(coalesce(p_key, ''), 'UTF8')), 'hex'));
$$;
revoke all on function public.admin_ok(text) from public, anon, authenticated;

-- everything the dashboard shows, aggregated, for one period and the period before it
create or replace function public.admin_stats(p_key text, p_from timestamptz, p_to timestamptz)
returns jsonb language plpgsql security definer set search_path = public stable as $$
declare res jsonb; len interval := p_to - p_from;
begin
  if not public.admin_ok(p_key) then raise exception 'not authorized' using errcode = '42501'; end if;
  if len <= interval '0' or len > interval '400 days' then raise exception 'bad period'; end if;

  with ev as (select * from public.events where at >= p_from and at < p_to),
  pv as (select * from public.events where at >= p_from - len and at < p_from),
  sess as (
    select session, min(at) as t0, max(at) as t1,
           count(*) filter (where kind = 'pageview') as pages,
           coalesce(sum(ms) filter (where kind = 'engage'), 0) as eng_ms,
           count(*) filter (where kind in ('product_view','fav','rec_click','search','filter')) as acts,
           bool_or(is_new) as is_new
    from ev group by session),
  psess as (select session, count(*) filter (where kind = 'pageview') as pages from pv group by session),
  prod as (
    select handle,
           count(*) filter (where kind = 'product_view') as views,
           count(distinct session) filter (where kind = 'product_view') as uniq,
           coalesce(sum(ms) filter (where kind = 'engage'), 0) as total_ms,
           count(*) filter (where kind = 'engage') as engs,
           count(*) filter (where kind = 'fav') as favs,
           count(*) filter (where kind = 'rec_click') as rec_clicks
    from ev where handle is not null group by handle),
  pprod as (select handle, count(*) filter (where kind = 'product_view') as views, count(*) filter (where kind = 'fav') as favs,
                   coalesce(sum(ms) filter (where kind = 'engage'), 0) as total_ms
            from pv where handle is not null group by handle)
  select jsonb_build_object(
    'from', p_from, 'to', p_to,
    'visitors', (select count(distinct visitor) from ev),
    'sessions', (select count(*) from sess),
    'pageviews', (select count(*) from ev where kind = 'pageview'),
    'newVisitors', (select count(distinct visitor) from ev where is_new),
    'productViews', (select count(*) from ev where kind = 'product_view'),
    'favAdds', (select count(*) from ev where kind = 'fav'),
    'prev', jsonb_build_object(
      'visitors', (select count(distinct visitor) from pv),
      'sessions', (select count(*) from psess),
      'pageviews', (select count(*) from pv where kind = 'pageview'),
      'newVisitors', (select count(distinct visitor) from pv where is_new),
      'productViews', (select count(*) from pv where kind = 'product_view'),
      'favAdds', (select count(*) from pv where kind = 'fav')),
    'daily', coalesce((select jsonb_agg(jsonb_build_object('d', d, 'visitors', v, 'sessions', s, 'pageviews', p, 'productViews', pr) order by d)
       from (select (at at time zone 'Asia/Riyadh')::date as d, count(distinct visitor) as v, count(distinct session) as s,
                    count(*) filter (where kind = 'pageview') as p, count(*) filter (where kind = 'product_view') as pr
             from ev group by 1) x), '[]'::jsonb),
    'engagement', (select jsonb_build_object(
        'avgSessionMs', coalesce(round(avg(greatest(extract(epoch from (t1 - t0)) * 1000, eng_ms))), 0),
        'avgEngagedMs', coalesce(round(avg(eng_ms)), 0),
        'avgPages', coalesce(round(avg(pages)::numeric, 2), 0),
        'bounceRate', coalesce(round(100.0 * count(*) filter (where pages <= 1 and acts = 0 and eng_ms < 10000) / nullif(count(*), 0), 1), 0),
        'engagementRate', coalesce(round(100.0 * count(*) filter (where pages >= 2 or acts > 0 or eng_ms >= 10000) / nullif(count(*), 0), 1), 0),
        'returningPct', coalesce(round(100.0 * count(*) filter (where not is_new) / nullif(count(*), 0), 1), 0))
      from sess),
    'productAvgMs', coalesce((select round(avg(ms)) from ev where kind = 'engage'), 0),
    'products', coalesce((select jsonb_agg(jsonb_build_object('h', p.handle, 'views', p.views, 'uniq', p.uniq, 'totalMs', p.total_ms,
          'avgMs', case when p.engs > 0 then round(p.total_ms::numeric / p.engs) else 0 end, 'favs', p.favs, 'recClicks', p.rec_clicks,
          'prevViews', coalesce(q.views, 0), 'prevFavs', coalesce(q.favs, 0), 'prevTotalMs', coalesce(q.total_ms, 0)) order by p.views desc)
       from (select * from prod order by views desc, total_ms desc limit 400) p left join pprod q using (handle)), '[]'::jsonb),
    'favTotals', coalesce((select jsonb_agg(jsonb_build_object('h', handle, 'n', total) order by total desc)
       from (select handle, total from public.fav_totals where total > 0 order by total desc limit 300) x), '[]'::jsonb),
    'searches', coalesce((select jsonb_agg(jsonb_build_object('q', q, 'n', n) order by n desc)
       from (select lower(trim(meta->>'q')) as q, count(*) as n from ev where kind = 'search' and coalesce(meta->>'q','') <> '' group by 1 order by 2 desc limit 30) x), '[]'::jsonb),
    'filters', coalesce((select jsonb_agg(jsonb_build_object('f', f, 'n', n) order by n desc)
       from (select (meta->>'type') || ': ' || coalesce(meta->>'value', '') as f, count(*) as n from ev where kind = 'filter' group by 1 order by 2 desc limit 20) x), '[]'::jsonb),
    'routes', coalesce((select jsonb_agg(jsonb_build_object('r', route, 'n', n, 's', s) order by n desc)
       from (select route, count(*) as n, count(distinct session) as s from ev where kind = 'pageview' group by route order by 2 desc limit 60) x), '[]'::jsonb),
    'transitions', coalesce((select jsonb_agg(jsonb_build_object('from', fr, 'to', t, 'n', n) order by n desc)
       from (select meta->>'from' as fr, route as t, count(*) as n from ev where kind = 'pageview' and coalesce(meta->>'from','') <> ''
             and meta->>'from' <> route group by 1, 2 order by 3 desc limit 25) x), '[]'::jsonb),
    'categoryToProduct', coalesce((select jsonb_agg(jsonb_build_object('from', fr, 'h', handle, 'n', n) order by n desc)
       from (select meta->>'from' as fr, handle, count(*) as n from ev where kind = 'product_view' and coalesce(meta->>'from','') not in ('', 'item')
             group by 1, 2 order by 3 desc limit 40) x), '[]'::jsonb),
    'funnel', (select jsonb_build_object(
        'sessions', count(distinct session),
        'home', count(distinct session) filter (where kind = 'pageview' and route = 'home'),
        'category', count(distinct session) filter (where kind = 'pageview' and route ~ '^(dresses|bags|shoes|winter|all|discounts|recent|popular)'),
        'brand', count(distinct session) filter (where kind = 'pageview' and route ~ '^(dresses|bags|shoes|winter)-'),
        'product', count(distinct session) filter (where kind = 'product_view'),
        'engaged', count(distinct session) filter (where kind in ('fav','rec_click') or (kind = 'engage' and ms >= 10000))) from ev),
    'recos', (select jsonb_build_object(
        'look', jsonb_build_object('impressions', count(*) filter (where kind = 'rec_view' and meta->>'section' = 'look'),
                                   'clicks', count(*) filter (where kind = 'rec_click' and meta->>'section' = 'look')),
        'alike', jsonb_build_object('impressions', count(*) filter (where kind = 'rec_view' and meta->>'section' = 'alike'),
                                    'clicks', count(*) filter (where kind = 'rec_click' and meta->>'section' = 'alike'))) from ev),
    'recoSlots', coalesce((select jsonb_agg(jsonb_build_object('section', sec, 'slot', slot, 'n', n) order by n desc)
       from (select meta->>'section' as sec, coalesce(meta->>'slot', meta->>'pos', '') as slot, count(*) as n from ev where kind = 'rec_click' group by 1, 2) x), '[]'::jsonb),
    'recoTop', coalesce((select jsonb_agg(jsonb_build_object('section', sec, 'from', fr, 'h', handle, 'n', n) order by n desc)
       from (select meta->>'section' as sec, meta->>'from' as fr, handle, count(*) as n from ev where kind = 'rec_click' group by 1, 2, 3 order by 4 desc limit 40) x), '[]'::jsonb),
    'devices', coalesce((select jsonb_object_agg(coalesce(device, 'unknown'), n) from (select device, count(distinct session) as n from ev where kind = 'pageview' and meta->>'landing' = '1' group by device) x), '{}'::jsonb),
    'sources', coalesce((select jsonb_object_agg(coalesce(source, 'direct'), n) from (select source, count(distinct session) as n from ev where kind = 'pageview' and meta->>'landing' = '1' group by source) x), '{}'::jsonb),
    'landing', coalesce((select jsonb_agg(jsonb_build_object('r', route, 'n', n) order by n desc)
       from (select route, count(*) as n from ev where kind = 'pageview' and meta->>'landing' = '1' group by route order by 2 desc limit 15) x), '[]'::jsonb),
    'firstEventAt', (select min(at) from public.events)
  ) into res;
  return res;
end $$;
revoke all on function public.admin_stats(text, timestamptz, timestamptz) from public;
grant execute on function public.admin_stats(text, timestamptz, timestamptz) to anon, authenticated;
