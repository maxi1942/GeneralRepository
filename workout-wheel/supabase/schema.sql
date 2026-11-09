-- Workout Wheel — database setup.
-- Paste this whole file into Supabase → SQL Editor → New query → Run.
-- Safe to run more than once.

-- ── Tables ──────────────────────────────────────────────────────────────────
create table if not exists public.profiles (
  id         uuid primary key references auth.users (id) on delete cascade,
  name       text not null check (char_length(name) between 1 and 30),
  created_at timestamptz not null default now()
);

create table if not exists public.workouts (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null default auth.uid() references public.profiles (id) on delete cascade,
  workout_date date not null,                       -- the day you trained
  logged_at    timestamptz not null default now(),  -- when you logged it (backdating is visible)
  activity     text,
  note         text,
  photo_path   text,
  deleted_at   timestamptz                          -- soft delete: stays visible in history
);
create index if not exists workouts_user_date on public.workouts (user_id, workout_date);

create table if not exists public.prizes (
  id         uuid primary key default gen_random_uuid(),
  name       text not null check (char_length(name) between 1 and 60),
  emoji      text not null default '🎁',
  weight     int  not null default 1 check (weight between 1 and 10), -- bigger slice = more likely
  active     boolean not null default true,
  created_by uuid default auth.uid() references public.profiles (id),
  created_at timestamptz not null default now()
);

create table if not exists public.spins (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references public.profiles (id) on delete cascade,
  prize_id    uuid references public.prizes (id),
  prize_name  text not null,      -- copied so history survives prize edits
  prize_emoji text not null default '🎁',
  cost        int  not null,
  spun_at     timestamptz not null default now(),
  used_at     timestamptz         -- null = still to be claimed
);

-- ── Security: only signed-in users (the two of you) can see or change anything.
alter table public.profiles enable row level security;
alter table public.workouts enable row level security;
alter table public.prizes   enable row level security;
alter table public.spins    enable row level security;

drop policy if exists "read profiles"  on public.profiles;
drop policy if exists "own profile"    on public.profiles;
drop policy if exists "update profile" on public.profiles;
create policy "read profiles"  on public.profiles for select to authenticated using (true);
create policy "own profile"    on public.profiles for insert to authenticated with check (id = auth.uid());
create policy "update profile" on public.profiles for update to authenticated using (id = auth.uid());

drop policy if exists "read workouts"  on public.workouts;
drop policy if exists "log own"        on public.workouts;
drop policy if exists "edit own"       on public.workouts;
create policy "read workouts"  on public.workouts for select to authenticated using (true);
create policy "log own"        on public.workouts for insert to authenticated with check (user_id = auth.uid());
create policy "edit own"       on public.workouts for update to authenticated using (user_id = auth.uid());
-- (no delete policy on purpose: deleting = setting deleted_at, so it stays in history)

drop policy if exists "read prizes"   on public.prizes;
drop policy if exists "add prizes"    on public.prizes;
drop policy if exists "edit prizes"   on public.prizes;
create policy "read prizes"   on public.prizes for select to authenticated using (true);
create policy "add prizes"    on public.prizes for insert to authenticated with check (true);
create policy "edit prizes"   on public.prizes for update to authenticated using (true);

drop policy if exists "read spins"    on public.spins;
drop policy if exists "own spins"     on public.spins;
drop policy if exists "use prizes"    on public.spins;
create policy "read spins"    on public.spins for select to authenticated using (true);
create policy "own spins"     on public.spins for insert to authenticated with check (user_id = auth.uid());
create policy "use prizes"    on public.spins for update to authenticated using (true); -- either of you can mark a prize used

-- ── Photo storage (private bucket) ──────────────────────────────────────────
insert into storage.buckets (id, name, public)
values ('workout-photos', 'workout-photos', false)
on conflict (id) do nothing;

drop policy if exists "read photos"   on storage.objects;
drop policy if exists "upload photos" on storage.objects;
create policy "read photos" on storage.objects for select to authenticated
  using (bucket_id = 'workout-photos');
create policy "upload photos" on storage.objects for insert to authenticated
  with check (bucket_id = 'workout-photos' and (storage.foldername(name))[1] = auth.uid()::text);

-- ── A few starter prizes (edit or archive them in the app) ──────────────────
insert into public.prizes (name, emoji, weight)
select * from (values
  ('Breakfast in bed', '🥐', 2),
  ('Massage (30 min)', '💆', 2),
  ('Pick the movie', '🎬', 3),
  ('Skip a chore', '🧹', 3),
  ('Dinner out – your choice', '🍝', 1)
) as v(name, emoji, weight)
where not exists (select 1 from public.prizes);
