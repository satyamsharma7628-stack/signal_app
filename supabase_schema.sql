-- Run this in the Supabase SQL Editor (Dashboard -> SQL Editor -> New query)
-- Safe to run multiple times (idempotent): creates or upgrades all tables,
-- including the Daily Top 10 & Weekly AI Playbook Newsletter tables.

create table if not exists items (
    url text primary key,
    title text not null,
    source text not null,
    tier integer not null,
    category text not null,
    published_at timestamptz,
    engagement_raw double precision default 0,
    summary text default '',
    is_builder_idea boolean default false,
    stack_tags text[] default '{}',
    dept text[] default '{}',
    dedup_key text default '',
    updated_at timestamptz default now()
);

create table if not exists summary_cache (
    url text primary key,
    summary text not null,
    created_at timestamptz default now()
);

-- User profiles table
create table if not exists user_profiles (
    user_id text primary key,
    email text not null,
    full_name text default '',
    avatar_url text default '',
    preferred_depts text[] default '{}',
    preferred_sources text[] default '{}',
    subscription_tier text default 'free',
    daily_newsletter boolean default false,
    weekly_newsletter boolean default false,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

-- Upgrade existing user_profiles table if it was created in Patch 0
alter table user_profiles add column if not exists daily_newsletter boolean default false;
alter table user_profiles add column if not exists weekly_newsletter boolean default false;

-- User saved items table
create table if not exists user_saved_items (
    user_id text not null,
    item_url text not null,
    title text not null,
    source text default '',
    category text default '',
    summary text default '',
    custom_note text default '',
    dept text[] default '{}',
    stack_tags text[] default '{}',
    saved_at timestamptz default now(),
    updated_at timestamptz default now(),
    primary key (user_id, item_url)
);

-- Caches pre-generated Daily Top 10 and Weekly AI Playbook issues so Gemini
-- only runs ONCE per day/week across all users (keeping AI costs at ₹0).
create table if not exists newsletter_issues (
    issue_key text primary key,
    kind text not null,
    subject text not null,
    html_body text not null,
    items jsonb default '[]'::jsonb,
    created_at timestamptz default now()
);

-- Indexes
create index if not exists idx_items_published_at on items (published_at desc);
create index if not exists idx_items_is_builder_idea on items (is_builder_idea);
create index if not exists idx_items_source on items (source);
create index if not exists idx_items_dept on items using gin(dept);
create index if not exists idx_user_saved_items_user on user_saved_items (user_id, saved_at desc);

-- Explicit table grants for PostgREST
grant select, insert, update, delete on items to anon, authenticated, service_role;
grant select, insert, update, delete on summary_cache to anon, authenticated, service_role;
grant select, insert, update, delete on user_profiles to anon, authenticated, service_role;
grant select, insert, update, delete on user_saved_items to anon, authenticated, service_role;
grant select, insert, update, delete on newsletter_issues to anon, authenticated, service_role;

-- Row Level Security
alter table items enable row level security;
alter table summary_cache enable row level security;
alter table user_profiles enable row level security;
alter table user_saved_items enable row level security;
alter table newsletter_issues enable row level security;

drop policy if exists "service role full access" on items;
drop policy if exists "anon read access" on items;
drop policy if exists "service role full access" on summary_cache;
drop policy if exists "anon read access" on summary_cache;
drop policy if exists "service role full access" on user_profiles;
drop policy if exists "users read own profile" on user_profiles;
drop policy if exists "users update own profile" on user_profiles;
drop policy if exists "service role full access" on user_saved_items;
drop policy if exists "users manage own saved items" on user_saved_items;
drop policy if exists "service role full access" on newsletter_issues;
drop policy if exists "anon read access" on newsletter_issues;

create policy "service role full access" on items
    for all to service_role using (true) with check (true);
create policy "anon read access" on items
    for select to anon, authenticated using (true);

create policy "service role full access" on summary_cache
    for all to service_role using (true) with check (true);
create policy "anon read access" on summary_cache
    for select to anon, authenticated using (true);

create policy "service role full access" on user_profiles
    for all to service_role using (true) with check (true);
create policy "users read own profile" on user_profiles
    for select to authenticated using (auth.uid()::text = user_id);
create policy "users update own profile" on user_profiles
    for all to authenticated using (auth.uid()::text = user_id) with check (auth.uid()::text = user_id);

create policy "service role full access" on user_saved_items
    for all to service_role using (true) with check (true);
create policy "users manage own saved items" on user_saved_items
    for all to authenticated using (auth.uid()::text = user_id) with check (auth.uid()::text = user_id);

create policy "service role full access" on newsletter_issues
    for all to service_role using (true) with check (true);
create policy "anon read access" on newsletter_issues
    for select to anon, authenticated using (true);
