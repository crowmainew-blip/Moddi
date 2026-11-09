-- moddi: โปรไฟล์ผู้ใช้ + หน้าผู้แปลสาธารณะ
-- วิธีใช้: Supabase → SQL Editor → New query → วางทั้งไฟล์ → Run (รันซ้ำได้ ไม่พัง)

create table if not exists public.profiles (
  user_id      uuid primary key references auth.users(id) on delete cascade,
  display_name text not null check (char_length(display_name) between 1 and 60),
  avatar_url   text check (avatar_url ~* '^https://'),
  bio          text check (char_length(bio) <= 500),
  page_url     text check (page_url ~* '^https?://'),
  promptpay    text check (promptpay ~ '^([0-9]{10}|[0-9]{13}|[0-9]{15})?$'),
  verified     boolean not null default false,   -- แอดมินเท่านั้นที่ตั้งได้
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
alter table public.profiles enable row level security;

drop policy if exists "ทุกคนดูโปรไฟล์ได้" on public.profiles;
create policy "ทุกคนดูโปรไฟล์ได้" on public.profiles for select using (true);
drop policy if exists "สร้างโปรไฟล์ตัวเอง" on public.profiles;
create policy "สร้างโปรไฟล์ตัวเอง" on public.profiles for insert to authenticated with check (user_id = auth.uid() and not verified);
drop policy if exists "แก้โปรไฟล์ตัวเอง" on public.profiles;
create policy "แก้โปรไฟล์ตัวเอง" on public.profiles for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

-- ผู้ใช้แก้ได้แค่บางช่อง (แก้ verified เองไม่ได้)
revoke insert, update on public.profiles from anon, authenticated;
grant insert (user_id, display_name, avatar_url, bio, page_url, promptpay) on public.profiles to authenticated;
grant update (display_name, avatar_url, bio, page_url, promptpay, updated_at) on public.profiles to authenticated;
grant select on public.profiles to anon, authenticated;

-- สมัครใหม่ = มีโปรไฟล์ให้อัตโนมัติ (ชื่อและรูปจาก Google)
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (user_id, display_name, avatar_url)
  values (new.id,
          left(coalesce(nullif(new.raw_user_meta_data->>'full_name', ''), split_part(new.email, '@', 1), 'ผู้ใช้'), 60),
          nullif(new.raw_user_meta_data->>'avatar_url', ''))
  on conflict (user_id) do nothing;
  return new;
end $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users for each row execute function public.handle_new_user();

-- ผู้ใช้ที่สมัครไว้ก่อนแล้ว
insert into public.profiles (user_id, display_name, avatar_url)
select id, left(coalesce(nullif(raw_user_meta_data->>'full_name', ''), split_part(email, '@', 1), 'ผู้ใช้'), 60), nullif(raw_user_meta_data->>'avatar_url', '')
from auth.users on conflict (user_id) do nothing;

-- อนุมัติคำขอผู้แปล (แก้ status เป็น approved ในตาราง translator_requests) = ได้ป้ายยืนยันอัตโนมัติ
create or replace function public.handle_request_approved() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.status = 'approved' and old.status is distinct from 'approved' then
    update public.profiles set verified = true,
      page_url = coalesce(page_url, new.page_url),
      promptpay = coalesce(nullif(promptpay, ''), nullif(new.promptpay, ''))
    where user_id = new.user_id;
  elsif new.status <> 'approved' and old.status = 'approved' then
    update public.profiles set verified = false where user_id = new.user_id;
  end if;
  return new;
end $$;
drop trigger if exists on_request_status on public.translator_requests;
create trigger on_request_status after update of status on public.translator_requests
  for each row execute function public.handle_request_approved();

-- ฉบับล่าสุดของแต่ละเกม: เพิ่ม user_id ของคนอัพล่าสุด (ไว้ลิงก์ไปหน้าผู้แปล)
create or replace view public.library_latest as
select distinct on (u.game_key) u.game_key, u.title, u.engine, u.kind, u.steam_appid, u.from_lang,
       u.total, u.fast, u.premium, u.human, u.path, u.user_name, u.created_at,
       (select count(distinct x.user_id) from public.library_uploads x where x.game_key = u.game_key and not x.hidden) as contributors,
       (select count(*) from public.library_uploads x where x.game_key = u.game_key and not x.hidden) as versions,
       u.user_id
from public.library_uploads u where not u.hidden
order by u.game_key, u.created_at desc;
grant select on public.library_latest to anon, authenticated;
