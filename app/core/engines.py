"""ระบุเอนจินของเกม (รวมเอนจินที่ยังไม่รองรับ) และบอกว่า moddi แปลได้ประมาณกี่ %

ตัวเลขเป็นค่าประมาณจากสิ่งที่ระบบดึงข้อความได้ ไม่ใช่ผลวัดจากทุกเกม
"""
import glob
import os

SUPPORT = {
    "rpgmaker_mvmz": {
        "pct": 90, "level": "รองรับเต็ม · แปลล่วงหน้าได้ทั้งเกม", "label": "≈ 90%",
        "can": ["บทพูด ตัวเลือก ชื่อผู้พูด", "ไอเทม สกิล อาวุธ สถานะ ศัตรู", "เมนู ข้อความต่อสู้ ชื่อแผนที่", "ใส่ฟอนต์ไทยให้อัตโนมัติ"],
        "cannot": ["ข้อความในปลั๊กอิน (plugins.js)", "ตัวหนังสือที่อยู่ในรูปภาพ"],
    },
    "unity_mono": {
        "pct": 85, "level": "รองรับ · เมื่อสแกน + เล่นเก็บ", "label": "≈ 85%",
        "can": ["ข้อความจากไฟล์ภาษาและ asset ที่สแกนเจอ (แปลล่วงหน้า)", "ทุกข้อความที่โผล่บนจอระหว่างเล่น (แปลสด)",
                "เมนู UI ทั้ง UGUI และ TextMeshPro"],
        "cannot": ["ข้อความที่ไม่เคยโผล่และสแกนไม่เจอ", "ตัวหนังสือที่อยู่ในรูปภาพ",
                   "ภาษาไทยอาจแสดงไม่สวยในบางเกม (สระลอย/ซ้อน)"],
    },
    "unity_il2cpp": {
        "pct": 60, "level": "ทดลอง · เกม Unity แบบ IL2CPP", "label": "≈ 60%",
        "can": ["ข้อความที่สแกนเจอ", "ข้อความระหว่างเล่นส่วนใหญ่"],
        "cannot": ["บางข้อความไม่ถูกดักจับ (ข้อจำกัดของ IL2CPP)", "ตัวหนังสือที่อยู่ในรูปภาพ", "บางเกมอาจเปิดไม่ขึ้นหลังติดตั้ง ให้กดถอน mod"],
    },
}

UNSUPPORTED = {
    "rpgmaker_vxace": ("RPG Maker VX Ace", "ข้อความอยู่ในไฟล์ .rvdata2 (Ruby) ยังไม่มีตัวแกะ"),
    "rpgmaker_vx": ("RPG Maker VX", "ข้อความอยู่ในไฟล์ .rvdata (Ruby) ยังไม่มีตัวแกะ"),
    "rpgmaker_xp": ("RPG Maker XP", "ข้อความอยู่ในไฟล์ .rxdata (Ruby) ยังไม่มีตัวแกะ"),
    "rpgmaker_2k": ("RPG Maker 2000/2003", "รูปแบบไฟล์เก่า ยังไม่มีตัวแกะ"),
    "renpy": ("Ren'Py", "ยังไม่รองรับ แต่ทำเพิ่มได้ไม่ยาก (ข้อความเป็นสคริปต์ .rpy)"),
    "unreal": ("Unreal Engine", "ข้อความอยู่ในไฟล์ .pak ที่มักถูกเข้ารหัส ยังไม่รองรับ"),
    "godot": ("Godot", "ข้อความอยู่ในไฟล์ .pck ยังไม่รองรับ"),
    "gamemaker": ("GameMaker", "ข้อความอยู่ในไฟล์ data.win ยังไม่รองรับ"),
    "wolf": ("WOLF RPG Editor", "ข้อความอยู่ในไฟล์ .wolf ยังไม่รองรับ"),
    "kirikiri": ("KiriKiri", "ข้อความอยู่ในไฟล์ .xp3 ยังไม่รองรับ"),
    "electron": ("Electron / NW.js (เกมเว็บ)", "ยังไม่รองรับ"),
    "unknown": ("ไม่รู้จัก", "ไม่เจอลักษณะของเอนจินที่รู้จัก อาจเป็นเอนจินที่ผู้พัฒนาเขียนเอง"),
}


def _has(d, *patterns):
    return any(glob.glob(os.path.join(d, p)) for p in patterns)


def identify_unsupported(d):
    """เดาเอนจินของเกมที่ moddi ยังไม่รองรับ"""
    if not d or not os.path.isdir(d):
        return None
    if _has(d, "Game.rgss3a", "Data/*.rvdata2"):
        return "rpgmaker_vxace"
    if _has(d, "Game.rgss2a", "Data/*.rvdata"):
        return "rpgmaker_vx"
    if _has(d, "Game.rgssad", "Data/*.rxdata"):
        return "rpgmaker_xp"
    if _has(d, "RPG_RT.exe", "RPG_RT.ldb"):
        return "rpgmaker_2k"
    if _has(d, "renpy", "game/*.rpa", "game/*.rpy", "game/*.rpyc"):
        return "renpy"
    if _has(d, "*/Content/Paks/*.pak", "Engine/Binaries", "*/Binaries/Win64"):
        return "unreal"
    if _has(d, "*.pck", "data.pck"):
        return "godot"
    if _has(d, "data.win"):
        return "gamemaker"
    if _has(d, "Data.wolf", "Data/*.wolf", "*.wolf"):
        return "wolf"
    if _has(d, "*.xp3"):
        return "kirikiri"
    if _has(d, "resources/app.asar", "package.nw", "nw.dll"):
        return "electron"
    if _has(d, "*.exe"):
        return "unknown"
    return None


def support_for(info):
    """ข้อมูลการรองรับของเกมที่ตรวจเจอ"""
    if info.get("kind") == "rpgmaker":
        key = "rpgmaker_mvmz"
    elif info.get("kind") == "unity":
        key = "unity_il2cpp" if info.get("il2cpp") else "unity_mono"
    else:
        name, why = UNSUPPORTED.get(info.get("key", "unknown"), UNSUPPORTED["unknown"])
        return {"pct": 0, "level": "ยังไม่รองรับ", "label": "0%", "engine": name, "can": [], "cannot": [why]}
    out = dict(SUPPORT[key])
    out["engine"] = info.get("engine", "")
    return out
