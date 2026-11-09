"""RPG Maker MV / MZ: ตรวจเกม ดึงข้อความ ใส่คำแปลกลับ สำรอง/คืนค่า และเปลี่ยนฟอนต์ไทย

หลักการ: ข้อความทุกชิ้นถูกเก็บเป็น "หน่วย" (unit) โดยใช้ข้อความต้นฉบับเป็นกุญแจ
ไฟล์ mod จึงเป็นแค่ {ต้นฉบับ: คำแปล} ไม่มีไฟล์เกมติดไปเลย และยังใช้ได้แม้เกมอัปเดต
"""
import json
import os
import re
import shutil

BACKUP_DIR = "moddi_backup"
FONT_NAME = "ThaiGameFont.woff"
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
FONT_SRC = os.path.join(getattr(sys, "_MEIPASS", os.path.join(HERE, "..")), "fonts", FONT_NAME)

# ฟิลด์ในฐานข้อมูลที่ผู้เล่นมองเห็น
DB_FIELDS = {
    "Actors.json": ["name", "nickname", "profile"],
    "Classes.json": ["name"],
    "Skills.json": ["name", "description", "message1", "message2"],
    "Items.json": ["name", "description"],
    "Weapons.json": ["name", "description"],
    "Armors.json": ["name", "description"],
    "Enemies.json": ["name"],
    "States.json": ["name", "message1", "message2", "message3", "message4"],
}
SYSTEM_LISTS = ["elements", "skillTypes", "weaponTypes", "armorTypes", "equipTypes"]
TERM_LISTS = ["basic", "commands", "params"]


# ---------------------------------------------------------------- ตรวจเกม
def detect(game_dir):
    """คืนค่า dict ข้อมูลเกม หรือ None ถ้าไม่ใช่ RPG Maker MV/MZ"""
    for root in (game_dir, os.path.join(game_dir, "www")):
        data = os.path.join(root, "data")
        if not os.path.isfile(os.path.join(data, "System.json")):
            continue
        js = os.path.join(root, "js")
        if os.path.isfile(os.path.join(js, "rmmz_core.js")):
            engine = "RPG Maker MZ"
        elif os.path.isfile(os.path.join(js, "rpg_core.js")):
            engine = "RPG Maker MV"
        else:
            engine = "RPG Maker MV" if root.endswith("www") else "RPG Maker MZ"
        sys_json = os.path.join(root, BACKUP_DIR, "data", "System.json")  # ชื่อเดิมก่อนแปล
        if not os.path.isfile(sys_json):
            sys_json = os.path.join(data, "System.json")
        with open(sys_json, encoding="utf-8-sig") as f:
            title = json.load(f).get("gameTitle", "")
        return {"engine": engine, "root": root, "data": data, "title": title}
    return None


def _data_files(info):
    names = sorted(os.listdir(info["data"]))
    return [n for n in names if n.endswith(".json")]


def _load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------- เดินผ่านข้อความ
def _is_text(s):
    return isinstance(s, str) and s.strip() != ""


def _walk_event_list(cmds, visit, ctx):
    """เดินคำสั่ง event; visit(text, kind, ctx) คืนค่าคำแปลหรือ None
    ข้อความหลายบรรทัด (401/405) ถูกรวมเป็นก้อนเดียวด้วย \\n
    คืนค่า list คำสั่งใหม่ (จำนวนบรรทัดอาจเปลี่ยน)"""
    out = []
    i = 0
    while i < len(cmds):
        c = cmds[i]
        code = c.get("code")
        p = c.get("parameters", [])
        if code in (401, 405):
            j = i
            lines = []
            while j < len(cmds) and cmds[j].get("code") == code:
                lines.append(cmds[j]["parameters"][0] if cmds[j].get("parameters") else "")
                j += 1
            block = "\n".join(lines)
            new = visit(block, "dialogue" if code == 401 else "scroll", ctx) if _is_text(block) else None
            if new is None:
                out.extend(cmds[i:j])
            else:
                for line in new.split("\n"):
                    out.append({"code": code, "indent": c.get("indent", 0), "parameters": [line]})
            i = j
            continue
        c = dict(c)
        p = list(p)
        if code == 101 and len(p) > 4 and _is_text(p[4]):  # MZ ชื่อผู้พูด
            p[4] = visit(p[4], "speaker", ctx) or p[4]
        elif code == 102 and p and isinstance(p[0], list):  # ตัวเลือก
            p[0] = [(visit(s, "choice", ctx) or s) if _is_text(s) else s for s in p[0]]
        elif code == 402 and len(p) > 1 and _is_text(p[1]):
            p[1] = visit(p[1], "choice", ctx) or p[1]
        elif code in (320, 324, 325) and len(p) > 1 and _is_text(p[1]):
            p[1] = visit(p[1], "name", ctx) or p[1]
        c["parameters"] = p
        out.append(c)
        i += 1
    return out


def _walk_file(name, obj, visit):
    """เดินไฟล์ data หนึ่งไฟล์ แก้ obj ในที่ คืนค่า obj"""
    ctx = {"file": name}
    if name in DB_FIELDS:
        for row in obj:
            if not row:
                continue
            for k in DB_FIELDS[name]:
                if _is_text(row.get(k)):
                    row[k] = visit(row[k], "db", ctx) or row[k]
    elif name == "System.json":
        if _is_text(obj.get("gameTitle")):
            obj["gameTitle"] = visit(obj["gameTitle"], "title", ctx) or obj["gameTitle"]
        if _is_text(obj.get("currencyUnit")):
            obj["currencyUnit"] = visit(obj["currencyUnit"], "term", ctx) or obj["currencyUnit"]
        for k in SYSTEM_LISTS:
            if isinstance(obj.get(k), list):
                obj[k] = [(visit(s, "term", ctx) or s) if _is_text(s) else s for s in obj[k]]
        terms = obj.get("terms", {})
        for k in TERM_LISTS:
            if isinstance(terms.get(k), list):
                terms[k] = [(visit(s, "term", ctx) or s) if _is_text(s) else s for s in terms[k]]
        msgs = terms.get("messages", {})
        for k, v in list(msgs.items()):
            if _is_text(v):
                msgs[k] = visit(v, "term", ctx) or v
    elif name == "CommonEvents.json":
        for ev in obj:
            if ev and isinstance(ev.get("list"), list):
                ev["list"] = _walk_event_list(ev["list"], visit, ctx)
    elif name == "Troops.json":
        for tr in obj:
            for pg in (tr or {}).get("pages", []):
                pg["list"] = _walk_event_list(pg.get("list", []), visit, ctx)
    elif re.fullmatch(r"Map\d+\.json", name):
        if _is_text(obj.get("displayName")):
            obj["displayName"] = visit(obj["displayName"], "map", ctx) or obj["displayName"]
        for ev in obj.get("events", []):
            for pg in (ev or {}).get("pages", []):
                pg["list"] = _walk_event_list(pg.get("list", []), visit, ctx)
    return obj


# ---------------------------------------------------------------- API หลัก
def extract(game_dir):
    """คืนค่า list ของหน่วยข้อความ (ไม่ซ้ำ) เรียงตามลำดับที่เจอ
    แต่ละหน่วย: {"src": ต้นฉบับ, "kind": ชนิด, "file": ไฟล์แรกที่เจอ}"""
    info = detect(game_dir)
    if not info:
        raise ValueError("ไม่ใช่เกม RPG Maker MV/MZ หรือหาโฟลเดอร์ data ไม่เจอ")
    src_dir = _backup_data_dir(info) if is_installed(game_dir) else info["data"]
    seen, units = set(), []

    def visit(text, kind, ctx):
        if text not in seen:
            seen.add(text)
            units.append({"src": text, "kind": kind, "file": ctx["file"]})
        return None

    for name in _data_files(info):
        path = os.path.join(src_dir, name)
        if os.path.isfile(path):
            _walk_file(name, _load(path), visit)
    return units


def _backup_root(info):
    return os.path.join(info["root"], BACKUP_DIR)


def _backup_data_dir(info):
    return os.path.join(_backup_root(info), "data")


def is_installed(game_dir):
    info = detect(game_dir)
    return bool(info) and os.path.isdir(_backup_data_dir(info))


def _make_backup(info):
    broot = _backup_root(info)
    if os.path.isdir(os.path.join(broot, "data")):
        return  # มี backup ต้นฉบับอยู่แล้ว ห้ามทับ
    os.makedirs(broot, exist_ok=True)
    shutil.copytree(info["data"], os.path.join(broot, "data"))
    css = os.path.join(info["root"], "fonts", "gamefont.css")
    if os.path.isfile(css):
        shutil.copy2(css, os.path.join(broot, "gamefont.css"))


def install(game_dir, translations, font=True):
    """ใส่คำแปลลงเกม (สำรองต้นฉบับก่อนเสมอ) คืนค่าจำนวนข้อความที่ถูกแปล"""
    info = detect(game_dir)
    if not info:
        raise ValueError("ไม่ใช่เกม RPG Maker MV/MZ")
    _make_backup(info)
    bdata = _backup_data_dir(info)
    count = [0]

    def visit(text, kind, ctx):
        t = translations.get(text)
        if t and t != text:
            count[0] += 1
            return t
        return None

    for name in _data_files({"data": bdata}):
        obj = _walk_file(name, _load(os.path.join(bdata, name)), visit)
        if font and name == "System.json" and info["engine"] == "RPG Maker MZ":
            adv = obj.setdefault("advanced", {})
            adv["mainFontFilename"] = FONT_NAME
        _save(os.path.join(info["data"], name), obj)
    if font:
        _install_font(info)
    return count[0]


def _install_font(info):
    fdir = os.path.join(info["root"], "fonts")
    os.makedirs(fdir, exist_ok=True)
    shutil.copy2(FONT_SRC, os.path.join(fdir, FONT_NAME))
    if info["engine"] == "RPG Maker MV":
        with open(os.path.join(fdir, "gamefont.css"), "w", encoding="utf-8") as f:
            f.write('@font-face {\n    font-family: GameFont;\n    src: url("%s");\n}\n' % FONT_NAME)


def uninstall(game_dir):
    """คืนเกมกลับเป็นต้นฉบับ 100%"""
    info = detect(game_dir)
    if not info or not os.path.isdir(_backup_data_dir(info)):
        raise ValueError("เกมนี้ยังไม่ได้ติดตั้ง mod")
    broot = _backup_root(info)
    shutil.rmtree(info["data"])
    shutil.copytree(os.path.join(broot, "data"), info["data"])
    css_b = os.path.join(broot, "gamefont.css")
    if os.path.isfile(css_b):
        shutil.copy2(css_b, os.path.join(info["root"], "fonts", "gamefont.css"))
    font = os.path.join(info["root"], "fonts", FONT_NAME)
    if os.path.isfile(font):
        os.remove(font)
    shutil.rmtree(broot)
