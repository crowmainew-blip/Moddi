"""ตรวจระบบกันโกง (anti-cheat) ในโฟลเดอร์เกม

การใส่ BepInEx หรือแก้ไฟล์เกมที่มีระบบกันโกง อาจทำให้ผู้เล่นโดนแบนไอดี
moddi จึงไม่ติดตั้งอะไรลงเกมที่ตรวจเจอระบบเหล่านี้
"""
import os
import re

# (ชื่อที่แสดง, รูปแบบชื่อไฟล์/โฟลเดอร์ เทียบแบบไม่สนตัวพิมพ์)
SIGNATURES = [
    ("Easy Anti-Cheat", [r"easyanticheat", r"easyanticheat.*\.(exe|dll|sys)", r"start_protected_game\.exe", r"eac_launcher\.exe"]),
    ("BattlEye", [r"battleye", r"beservice.*\.exe", r"beclient.*\.dll", r".*_be\.exe"]),
    ("Anti-Cheat Expert (Tencent)", [r"anticheatexpert", r"ace-.*\.(exe|dll|sys)", r"sguard.*\.(exe|dll)"]),
    ("nProtect GameGuard", [r"gameguard", r"gamemon(64)?\.des", r"npggnt.*"]),
    ("XIGNCODE3", [r"xigncode", r"x3\.xem", r"xxd-0\.xem"]),
    ("mhyprot (HoYoverse)", [r"mhyprot\d*\.sys"]),
    ("EQU8", [r"equ8", r"equ8_.*\.(exe|dll)"]),
    ("AhnLab HackShield", [r"hshield", r"ehsvc\.dll"]),
    ("PunkBuster", [r"pb", r"pbsvc.*\.exe"]),
    ("Riot Vanguard", [r"vgc\.exe", r"vgk\.sys"]),
]
_COMPILED = [(name, [re.compile(p + r"$", re.I) for p in pats]) for name, pats in SIGNATURES]


def detect_anticheat(game_dir, max_depth=2):
    """คืนชื่อระบบกันโกงที่เจอ (list) หรือ [] ถ้าไม่เจอ"""
    found = []
    if not game_dir or not os.path.isdir(game_dir):
        return found
    base = os.path.abspath(game_dir).rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(game_dir):
        depth = root.rstrip(os.sep).count(os.sep) - base
        if depth >= max_depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d.lower() not in ("bepinex", "moddi_backup", "moddi_unity_backup")]
        for entry in dirs + files:
            for name, pats in _COMPILED:
                if name in found:
                    continue
                if name == "PunkBuster" and entry.lower() == "pb" and entry not in dirs:
                    continue  # "pb" ต้องเป็นโฟลเดอร์เท่านั้น
                if any(p.match(entry) for p in pats):
                    found.append(name)
    return found


def guard(game_dir):
    """โยน error ถ้าเกมนี้มีระบบกันโกง"""
    ac = detect_anticheat(game_dir)
    if ac:
        raise ValueError(
            f"เกมนี้มีระบบกันโกง ({', '.join(ac)}) moddi จะไม่ติดตั้งอะไรลงเกมนี้ "
            "เพราะการใส่ mod อาจทำให้โดนแบนไอดี")
