# moddi

แปลเกมเป็นภาษาไทย (RPG Maker MV/MZ, Unity) + คลังม็อดภาษาไทย

- `app/` โปรแกรมบน Windows (Python) · ผู้ใช้ทั่วไปโหลด `moddi.exe` จากหน้า Releases
- `web/` หน้าเว็บคลัง (แก้ที่ `template.html` แล้วรัน `python web/build.py`) · Vercel เสิร์ฟโฟลเดอร์ `web/site`

## ปล่อยเวอร์ชันใหม่
push ขึ้น `main` → GitHub Actions สร้าง moddi.exe ให้ (ดูในแท็บ Actions)
สร้าง tag เช่น `v0.1.0` → ได้หน้า Release ให้คนโหลด
