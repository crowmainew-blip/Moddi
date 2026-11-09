-- moddi: ฐานข้อมูลสำหรับล็อกอิน Google และคำขอยืนยันตัวตนผู้แปล
-- วิธีใช้: Supabase → SQL Editor → วางทั้งไฟล์ → Run

create table if not exists public.translator_requests (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references auth.users(id) on delete cascade,
  page_name   text not null check (char_length(page_name) between 1 and 120),
  page_url    text not null check (page_url ~* '^https?://'),
  games       text check (char_length(games) <= 4000),
  promptpay   text check (promptpay ~ '^([0-9]{10}|[0-9]{13}|[0-9]{15})?$'),
  status      text not null default 'pending' check (status in ('pending','approved','rejected')),
  created_at  timestamptz not null default now()
);

alter table public.translator_requests enable row level security;

-- ผู้ใช้เห็นได้แค่คำขอของตัวเอง
create policy "read own requests" on public.translator_requests
  for select using (auth.uid() = user_id);

-- ผู้ใช้ส่งคำขอได้เฉพาะในชื่อตัวเอง และตั้งสถานะเองไม่ได้ (ต้องเป็น pending)
create policy "insert own pending request" on public.translator_requests
  for insert with check (auth.uid() = user_id and status = 'pending');

-- ไม่มี policy update/delete สำหรับผู้ใช้: แอดมินอนุมัติผ่านหน้า Table Editor ของ Supabase

-- ================================================================
-- คลังชุมชน: ทุกคนที่ล็อกอินอัพงานแปล (แปลค้างไว้ก็ได้) เข้าคลังได้
-- ทุกการอัพเก็บเป็นแถวใหม่ (ประวัติครบ ย้อนเวอร์ชันได้โดยลบแถวที่เสีย)
-- แอปรวมกับฉบับล่าสุดก่อนอัพเสมอ งานของคนก่อนหน้าจึงไม่หาย

create table if not exists public.library_uploads (
  id          bigint generated always as identity primary key,
  user_id     uuid not null references auth.users(id) on delete cascade,
  user_name   text check (char_length(user_name) <= 120),
  game_key    text not null check (game_key ~ '^[a-z0-9ก-๙-]{1,80}$'),
  title       text not null check (char_length(title) between 1 and 200),
  engine      text check (char_length(engine) <= 60),
  kind        text not null check (kind in ('rpgmaker','unity')),
  steam_appid text check (steam_appid ~ '^[0-9]{1,10}$'),
  from_lang   text check (char_length(from_lang) <= 8),
  total       int not null check (total >= 0),
  fast        int not null default 0,
  premium     int not null default 0,
  human       int not null default 0,
  lines_added int not null default 0,
  path        text not null,
  hidden      boolean not null default false,   -- แอดมินซ่อนเวอร์ชันที่เสียได้
  created_at  timestamptz not null default now()
);
create index if not exists library_uploads_key on public.library_uploads (game_key, created_at desc);
alter table public.library_uploads enable row level security;

create policy "ทุกคนอ่านคลังได้" on public.library_uploads for select using (not hidden);
create policy "อัพได้ในชื่อตัวเอง" on public.library_uploads for insert to authenticated
  with check (user_id = auth.uid() and path like auth.uid()::text || '/%' and not hidden);

-- ฉบับล่าสุดของแต่ละเกม + จำนวนคนช่วย + จำนวนครั้งที่อัพ
create or replace view public.library_latest as
select distinct on (u.game_key) u.game_key, u.title, u.engine, u.kind, u.steam_appid, u.from_lang,
       u.total, u.fast, u.premium, u.human, u.path, u.user_name, u.created_at,
       (select count(distinct x.user_id) from public.library_uploads x where x.game_key = u.game_key and not x.hidden) as contributors,
       (select count(*) from public.library_uploads x where x.game_key = u.game_key and not x.hidden) as versions
from public.library_uploads u where not u.hidden
order by u.game_key, u.created_at desc;
grant select on public.library_latest to anon, authenticated;

-- ที่เก็บไฟล์ (สาธารณะสำหรับอ่าน, เขียนได้เฉพาะโฟลเดอร์ของตัวเอง, ไฟล์ละไม่เกิน 20 MB)
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('library', 'library', true, 20971520, array['application/json'])
on conflict (id) do nothing;
create policy "อัพไฟล์คลังในโฟลเดอร์ตัวเอง" on storage.objects for insert to authenticated
  with check (bucket_id = 'library' and (storage.foldername(name))[1] = auth.uid()::text);
