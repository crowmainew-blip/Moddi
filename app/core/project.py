"""โปรเจกต์แปล (เก็บคำแปลของแต่ละเกม) และไฟล์ mod สำหรับแชร์

ไฟล์ mod (.moddi.json) เป็น JSON ข้อความล้วน ไม่มีไฟล์เกม ไม่มีโปรแกรม
ตอนนำเข้าแอปจะตรวจซ้ำว่าเป็นข้อความล้วนจริง จึงยัดไวรัสมาไม่ได้
"""
import hashlib
import json
import os
import re
import time

APP_DIR = os.path.join(os.path.expanduser("~"), ".moddi")
PROJ_DIR = os.path.join(APP_DIR, "projects")
MOD_FORMAT = "moddi/1"
OLD_FORMATS = ("thaimod/1",)
MAX_MOD_BYTES = 50 * 1024 * 1024


def _key(game_dir):
    return hashlib.sha1(os.path.abspath(game_dir).lower().encode("utf-8")).hexdigest()[:16]


def load(game_dir):
    path = os.path.join(PROJ_DIR, _key(game_dir) + ".json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"game_dir": os.path.abspath(game_dir), "translations": {}, "glossary": {}}


def save(proj):
    os.makedirs(PROJ_DIR, exist_ok=True)
    path = os.path.join(PROJ_DIR, _key(proj["game_dir"]) + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(proj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def export_mod(proj, info, units, translator_name=""):
    srcs = {u["src"] for u in units}
    entries = {s: t for s, t in proj["translations"].items() if s in srcs and t and t != s}
    origin = {s: proj.get("origin", {}).get(s, "f") for s in entries}
    return {
        "format": MOD_FORMAT,
        "title": info.get("title", ""),
        "engine": info.get("engine", ""),
        "translator": translator_name,
        "created": time.strftime("%Y-%m-%d"),
        "total_lines": len(units),
        "translated_lines": len(entries),
        "glossary": proj.get("glossary", {}),
        "stats": stats(entries, origin, len(units)),
        "origin": origin,
        "entries": entries,
    }


ORIGINS = {"f": "แปลด่วน", "p": "แปลพรีเมียม", "h": "คนแปล"}


def stats(entries, origin, total):
    """นับว่าแต่ละบรรทัดแปลด้วยวิธีไหน: f=แปลด่วน (ออฟไลน์) p=แปลพรีเมียม (AI ออนไลน์) h=คนแปล/เกลา"""
    c = {"f": 0, "p": 0, "h": 0}
    for s in entries:
        c[origin.get(s, "f")] = c.get(origin.get(s, "f"), 0) + 1
    return {"total": total, "fast": c["f"], "premium": c["p"], "human": c["h"]}


def read_mod(raw_bytes):
    """ตรวจไฟล์ mod อย่างเข้มงวด: ต้องเป็น JSON ข้อความล้วนตามรูปแบบเท่านั้น"""
    if len(raw_bytes) > MAX_MOD_BYTES:
        raise ValueError("ไฟล์ mod ใหญ่เกินไป")
    try:
        data = json.loads(raw_bytes.decode("utf-8-sig"))
    except Exception:
        raise ValueError("ไฟล์นี้ไม่ใช่ไฟล์ mod (ต้องเป็น .moddi.json)")
    if not isinstance(data, dict) or data.get("format") not in (MOD_FORMAT,) + OLD_FORMATS:
        raise ValueError("รูปแบบไฟล์ mod ไม่ถูกต้อง")
    entries = data.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("ไฟล์ mod ไม่มีคำแปล")
    clean = {}
    for k, v in entries.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError("ไฟล์ mod มีข้อมูลที่ไม่ใช่ข้อความ")
        if len(v) > 10000 or re.search(r"<\s*script", v, re.I):
            raise ValueError("ไฟล์ mod มีเนื้อหาน่าสงสัย")
        clean[k] = v
    gl = data.get("glossary") or {}
    gl = {k: v for k, v in gl.items() if isinstance(k, str) and isinstance(v, str)}
    org = data.get("origin") or {}
    org = {k: v for k, v in org.items() if k in clean and v in ORIGINS} if isinstance(org, dict) else {}
    return {"title": str(data.get("title", "")), "translator": str(data.get("translator", "")),
            "entries": clean, "glossary": gl, "origin": org}
