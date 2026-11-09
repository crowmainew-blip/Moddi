"""moddi — แอปทำ mod ภาษาไทยสำหรับเกม (ตัวต้นแบบ: RPG Maker MV/MZ)

วิธีใช้: ดับเบิลคลิก start.bat (Windows) หรือรัน  python app.py
แอปจะเปิดหน้าเว็บในเบราว์เซอร์ของเครื่องเอง (ไม่ได้ขึ้นอินเทอร์เน็ต)
"""
import glob
import json
import os
import re
import shutil
import string
import subprocess
import sys
import threading
import traceback
import urllib.request
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import engines, project, rpgmaker, safety, thai_shape, translator, unity, unity_scan  # noqa: E402

PORT = 8765
FROZEN = getattr(sys, "frozen", False)  # รันจาก moddi.exe (PyInstaller)
HERE = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(project.APP_DIR, "settings.json")
SITE = os.path.join(HERE, "site")

JOB = {"running": False, "done": 0, "total": 0, "msg": "", "failed": 0, "stop": False}
PULL = {"running": False, "pct": 0, "msg": ""}
UJOB = {"running": False, "pct": 0, "msg": ""}
SJOB = {"running": False, "pct": 0, "msg": ""}
LIVE_LOCK = threading.Lock()
LIVE_URL = f"http://127.0.0.1:{PORT}/xunity"
OLLAMA_URL = "http://127.0.0.1:11434"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LOCK = threading.Lock()


def load_settings():
    if os.path.isfile(SETTINGS):
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    return {"backend": "ollama", "model": "gemma3:4b", "base_url": "https://openrouter.ai/api/v1",
            "api_key": "", "translator_name": "", "batch": 10}


def save_settings(s):
    os.makedirs(project.APP_DIR, exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def need_game(d):
    info = rpgmaker.detect(d or "")
    if info:
        info["kind"] = "rpgmaker"
    else:
        info = unity.detect(d or "")
    if not info:
        raise ValueError("ไม่เจอเกมที่รองรับในโฟลเดอร์นี้ ต้องเป็นโฟลเดอร์ที่มีไฟล์ .exe ของเกม "
                         "(RPG Maker MV/MZ หรือเกม Unity) ถ้าเกมมีแค่ไฟล์ .exe ไฟล์เดียว แปลว่าถูกแพ็กไว้ รุ่นนี้ยังไม่รองรับ")
    return info


# ---------------------------------------------------------------- actions
def act_scan(_):
    """หาเกม RPG Maker ในโฟลเดอร์ Steam ทั่วไป"""
    roots = []
    if os.name == "nt":
        for d in string.ascii_uppercase:
            roots += [f"{d}:\\Program Files (x86)\\Steam\\steamapps\\common",
                      f"{d}:\\Program Files\\Steam\\steamapps\\common",
                      f"{d}:\\SteamLibrary\\steamapps\\common"]
    roots.append(os.path.expanduser("~/.steam/steam/steamapps/common"))
    for vdf in [r"C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf",
                r"C:\Program Files\Steam\steamapps\libraryfolders.vdf"]:
        try:
            with open(vdf, encoding="utf-8", errors="ignore") as f:
                for lib in re.findall(r'"path"\s+"([^"]+)"', f.read()):
                    roots.append(os.path.join(lib.replace("\\\\", "\\"), "steamapps", "common"))
        except OSError:
            pass
    found, seen = [], set()
    for r in roots:
        for g in glob.glob(os.path.join(r, "*")):
            info = rpgmaker.detect(g)
            if info and os.path.normcase(g) not in seen:
                seen.add(os.path.normcase(g))
                found.append({"dir": g, "title": info["title"] or os.path.basename(g), "engine": info["engine"]})
    return {"games": found}


def get_units(game_dir, info, proj=None):
    if info["kind"] == "rpgmaker":
        return rpgmaker.extract(game_dir)
    proj = proj or project.load(game_dir)
    units, seen = [], set()
    scan = proj.get("unity_scan") or {}
    labels = {x["id"]: x["label"] for x in scan.get("sources", [])}
    for sid in proj.get("unity_selected", []):
        for t in scan.get("texts", {}).get(sid, []):
            if t not in seen:
                seen.add(t)
                units.append({"src": t, "kind": "สแกน", "file": labels.get(sid, sid)})
    for k in proj["translations"]:
        if k not in seen:
            seen.add(k)
            units.append({"src": k, "kind": "ระหว่างเล่น", "file": info["exe"]})
    return units


def act_detect(b):
    try:
        info = need_game(b.get("dir"))
    except ValueError:
        key = engines.identify_unsupported(b.get("dir"))
        if not key:
            raise
        sup = engines.support_for({"kind": "unsupported", "key": key})
        return {"kind": "unsupported", "engine": sup["engine"], "title": os.path.basename(os.path.normpath(b["dir"])),
                "support": sup, "anticheat": safety.detect_anticheat(b["dir"])}
    proj = project.load(b["dir"])
    out = {"kind": info["kind"], "title": info["title"], "engine": info["engine"], "glossary": proj.get("glossary", {}),
           "anticheat": safety.detect_anticheat(b["dir"]), "support": engines.support_for(info)}
    if info["kind"] == "unity":
        if "thai_fix" in proj:  # โปรเจกต์จากรุ่นก่อน: ปิดการจัดสระที่ทำให้สระหาย แล้วเขียนคำแปลใหม่
            _set_thai_fix(b["dir"], proj.get("font_fix", True), False, proj.get("tmp_font", False))
            proj = project.load(b["dir"])
        auto = unity.read_auto(b["dir"])  # คำแปลที่ XUnity เก็บไว้เอง รวมเข้าโปรเจกต์
        new = {k: v for k, v in auto.items() if k not in proj["translations"]}
        if new:
            proj["translations"].update(new)
            project.save(proj)
        cfg = unity.read_config(b["dir"])
        units = get_units(b["dir"], info, proj)
        scan = proj.get("unity_scan") or {}
        out.update(scan={"sources": scan.get("sources", []), "selected": proj.get("unity_selected", []),
                         "lang": scan.get("lang"), "assets_ok": scan.get("assets_ok", True)} if scan else None)
        out.update(lines=len(units), translated=sum(1 for u in units if proj["translations"].get(u["src"])),
                   stats=_stats(proj, units),
                   found_scan=sum(1 for u in units if u["kind"] == "สแกน"),
                   found_live=sum(1 for u in units if u["kind"] == "ระหว่างเล่น"),
                   installed=info["managed"] or info["xunity"], runtime=info["bepinex"] and info["xunity"],
                   il2cpp=info["il2cpp"], live=cfg.get("Service.Endpoint") == "CustomTranslate" and cfg.get("Custom.Url") == LIVE_URL,
                   from_lang=cfg.get("General.FromLanguage") or "en", font_fix=proj.get("font_fix", True), thai_shape=proj.get("thai_shape", False),
                   tmp_font=proj.get("tmp_font", False))
        return out
    units = rpgmaker.extract(b["dir"])
    tr = sum(1 for u in units if proj["translations"].get(u["src"]))
    out.update(lines=len(units), translated=tr, installed=rpgmaker.is_installed(b["dir"]),
               stats=_stats(proj, units))
    return out


def _stats(proj, units):
    entries = {u["src"] for u in units if proj["translations"].get(u["src"])}
    return project.stats(entries, proj.get("origin", {}), len(units))


def _run_translate(game_dir, cfg):
    try:
        info = need_game(game_dir)
        proj = project.load(game_dir)
        units = get_units(game_dir, info, proj)
        backend = translator.make_backend(cfg)

        import time as _t
        last_write = [_t.time()]
        unity_ready = info["kind"] == "unity" and info["bepinex"] and info["xunity"]

        def prog(done, total):
            with LOCK:
                JOB.update(done=done, total=total, msg=f"แปลแล้ว {done}/{total}")
            project.save(proj)  # เซฟระหว่างทาง ปิดแอปกลางคันก็ไม่เสียของ
            if unity_ready and _t.time() - last_write[0] > 60:
                # ใส่คำแปลที่ได้แล้วลงเกมทุก 1 นาที (ในเกมกด Alt+R เพื่อโหลดใหม่)
                unity.write_translations(game_dir, proj["translations"], proj.get("thai_shape", False))
                last_write[0] = _t.time()

        with LOCK:
            JOB["total"] = sum(1 for u in units if u["src"] not in proj["translations"])
        before = set(proj["translations"])
        code = "p" if cfg.get("backend") == "api" else "f"

        def mark():
            org = proj.setdefault("origin", {})
            for k in proj["translations"]:
                if k not in before:
                    org.setdefault(k, code)

        def prog(done, total, _p=prog):
            mark()
            _p(done, total)
        _, failed = translator.translate_all(units, backend, proj["translations"], proj.get("glossary"),
                                             batch=int(cfg.get("batch") or 10), progress=prog,
                                             stop=lambda: JOB["stop"])
        mark()
        project.save(proj)
        if info["kind"] == "unity" and info["bepinex"] and info["xunity"]:
            unity.write_translations(game_dir, proj["translations"], proj.get("thai_shape", False))  # ใส่ลงเกมให้เลย
        with LOCK:
            JOB.update(failed=len(failed),
                       msg=("หยุดแล้ว" if JOB["stop"] else "แปลเสร็จแล้ว") +
                       (f" (แปลไม่ผ่าน {len(failed)} บรรทัด กดแปลอีกรอบเพื่อลองใหม่)" if failed else ""))
    except Exception as e:
        with LOCK:
            JOB["msg"] = "ผิดพลาด: " + _friendly(e)
    finally:
        with LOCK:
            JOB["running"] = False


def _friendly(e):
    s = str(e)
    if "11434" in s or "Connection refused" in s or "10061" in s:
        return "ต่อ Ollama ไม่ได้ — ติดตั้ง Ollama จาก ollama.com แล้วเปิดไว้ก่อน"
    if "404" in s:
        return "ไม่เจอโมเดลนี้ กดโหลดโมเดลในกล่องตัวแปลก่อน (ถ้าใช้ AI ออนไลน์ ให้เช็กชื่อโมเดล)"
    if "401" in s:
        return "API key ไม่ถูกต้อง"
    if "402" in s:
        return "เครดิตของผู้ให้บริการ AI หมด เติมเงินแล้วกดแปลต่อได้"
    if "429" in s:
        return "ผู้ให้บริการ AI จำกัดจำนวนครั้งชั่วคราว รอสักครู่แล้วกดแปลต่อ"
    return s


def _check_backend(cfg):
    """เช็กว่าตัวแปลพร้อมก่อนเริ่ม จะได้ไม่วิ่งล้มเหลวทั้งเกม"""
    kind = cfg.get("backend", "ollama")
    if kind == "ollama":
        model = cfg.get("model") or "gemma3:4b"
        st = act_ollama_status({"model": model})
        if not st["running"]:
            raise ValueError("ยังไม่ได้เปิด Ollama กดเปิด Ollama ในกล่องตัวแปลก่อน")
        if not st["has_model"]:
            raise ValueError(f"ยังไม่ได้โหลดโมเดล {model} กดโหลดโมเดลในกล่องตัวแปลก่อน")
    elif kind == "api":
        if not cfg.get("api_key"):
            raise ValueError("ใส่ API key ก่อน")
        if not cfg.get("model"):
            raise ValueError("เลือกโมเดลก่อน")


def act_translate(b):
    info = need_game(b.get("dir"))
    if info["kind"] == "unity" and not project.load(b["dir"]).get("unity_selected"):
        raise ValueError("กดสแกนหาข้อความในเกม แล้วเลือกแหล่งข้อความก่อน หรือเปิดเกมเล่นเพื่อแปลระหว่างเล่น")
    cfg = load_settings()
    cfg.update({k: v for k, v in (b.get("settings") or {}).items() if v is not None})
    save_settings(cfg)
    _check_backend(cfg)
    with LOCK:
        if JOB["running"]:
            raise ValueError("กำลังแปลอยู่")
        JOB.update(running=True, done=0, total=0, failed=0, stop=False, msg="กำลังเริ่ม...")
    threading.Thread(target=_run_translate, args=(b["dir"], cfg), daemon=True).start()
    return {"ok": True}


def act_progress(_):
    with LOCK:
        return dict(JOB)


def act_stop(_):
    JOB["stop"] = True
    return {"ok": True}


def act_lines(b):
    units = get_units(b["dir"], need_game(b.get("dir")))
    proj = project.load(b["dir"])
    tr = proj["translations"]
    q = (b.get("q") or "").lower()
    only = b.get("filter")
    rows = []
    for u in units:
        t = tr.get(u["src"], "")
        if only == "todo" and t:
            continue
        if q and q not in u["src"].lower() and q not in t.lower():
            continue
        org = proj.get("origin", {}).get(u["src"], "f") if t else ""
        if only == "machine" and (not t or org == "h"):
            continue
        rows.append({"src": u["src"], "tgt": t, "kind": u["kind"], "file": u["file"], "origin": org})
    if b.get("all"):
        return {"total": len(rows), "rows": rows}
    page = int(b.get("page") or 0)
    return {"total": len(rows), "rows": rows[page * 50:(page + 1) * 50]}


def act_edit(b):
    proj = project.load(b["dir"])
    org = proj.setdefault("origin", {})
    if b.get("tgt"):
        if proj["translations"].get(b["src"]) != b["tgt"]:
            org[b["src"]] = "h"  # คนแก้/เกลา
        proj["translations"][b["src"]] = b["tgt"]
    else:
        proj["translations"].pop(b["src"], None)
        org.pop(b["src"], None)
    project.save(proj)
    return {"ok": True}


def act_glossary(b):
    proj = project.load(b["dir"])
    proj["glossary"] = {k.strip(): v.strip() for k, v in (b.get("glossary") or {}).items() if k.strip() and v.strip()}
    project.save(proj)
    return {"ok": True}


def act_install(b):
    info = need_game(b.get("dir"))
    safety.guard(b["dir"])
    proj = project.load(b["dir"])
    if info["kind"] == "unity":
        if not (info["bepinex"] and info["xunity"]):
            raise ValueError("ยังไม่ได้ติดตั้งระบบแปลของเกม Unity กดติดตั้งระบบแปลก่อน")
        n = unity.write_translations(b["dir"], proj["translations"], proj.get("thai_shape", False))
    else:
        n = rpgmaker.install(b["dir"], proj["translations"])
    msg = f"ติดตั้งแล้ว ใส่คำแปล {n} จุด"
    if b.get("play"):
        appid = steam_appid(b["dir"])
        exe = os.path.join(b["dir"], info.get("exe") or "Game.exe")
        if appid and hasattr(os, "startfile"):
            os.startfile(f"steam://rungameid/{appid}")  # เกม Steam ต้องเปิดผ่าน Steam
            msg += " กำลังเปิดเกมผ่าน Steam..."
        elif os.path.isfile(exe):
            subprocess.Popen([exe], cwd=b["dir"])
            msg += " กำลังเปิดเกม..."
        else:
            msg += " (หาไฟล์เกมไม่เจอ เปิดเกมเองได้เลย)"
    return {"msg": msg}


def steam_appid(game_dir):
    """หาเลขเกม Steam จาก steam_appid.txt หรือ appmanifest_*.acf ในคลัง Steam"""
    p = os.path.join(game_dir, "steam_appid.txt")
    if os.path.isfile(p):
        with open(p, encoding="utf-8", errors="ignore") as f:
            v = f.read().strip()
        if v.isdigit():
            return v
    common = os.path.dirname(os.path.abspath(game_dir))
    if os.path.basename(common).lower() != "common":
        return None
    steamapps = os.path.dirname(common)
    name = os.path.basename(os.path.abspath(game_dir)).lower()
    for acf in glob.glob(os.path.join(steamapps, "appmanifest_*.acf")):
        try:
            with open(acf, encoding="utf-8", errors="ignore") as f:
                t = f.read()
        except OSError:
            continue
        m = re.search(r'"installdir"\s+"([^"]+)"', t)
        a = re.search(r'"appid"\s+"(\d+)"', t)
        if m and a and m.group(1).lower() == name:
            return a.group(1)
    return None


def act_uninstall(b):
    if need_game(b.get("dir"))["kind"] == "unity":
        unity.uninstall(b["dir"])
        return {"msg": "ถอนระบบแปลและคำแปลออกจากเกมแล้ว"}
    rpgmaker.uninstall(b["dir"])
    return {"msg": "ถอน mod แล้ว เกมกลับเป็นต้นฉบับทุกไฟล์"}


def act_export(b):
    info = need_game(b.get("dir"))
    units = get_units(b["dir"], info)
    mod = project.export_mod(project.load(b["dir"]), info, units, load_settings().get("translator_name", ""))
    mod["kind"] = info["kind"]
    mod["steam_appid"] = steam_appid(b["dir"]) or ""
    return {"filename": (info["title"] or "game") + ".moddi.json", "mod": mod}


def act_import(b):
    info = need_game(b.get("dir"))
    mod = project.read_mod(b["content"].encode("utf-8"))
    proj = project.load(b["dir"])
    if info["kind"] == "unity":
        hit = dict(mod["entries"])  # เกม Unity ไม่มีรายการข้อความตายตัว รับทั้งหมด
    else:
        srcs = {u["src"] for u in rpgmaker.extract(b["dir"])}
        hit = {k: v for k, v in mod["entries"].items() if k in srcs}
    # รวมแบบไม่ทับงานที่ดีกว่า: คนเกลา > พรีเมียม > แปลด่วน
    rank = {"f": 1, "p": 2, "h": 3}
    org = proj.setdefault("origin", {})
    for k, v in list(hit.items()):
        o = mod["origin"].get(k, "f")
        if k in proj["translations"] and rank.get(org.get(k, "f"), 1) > rank.get(o, 1):
            del hit[k]
            continue
        proj["translations"][k] = v
        org[k] = o
    for k, v in mod["glossary"].items():
        proj["glossary"].setdefault(k, v)
    project.save(proj)
    return {"msg": f"นำเข้า mod แล้ว ใช้ได้ {len(hit)} จาก {len(mod['entries'])} ข้อความ"
                   + (f" (ผู้แปล: {mod['translator']})" if mod["translator"] else "")}


def act_settings(b):
    s = load_settings()
    if b.get("save"):
        s.update(b["save"])
        save_settings(s)
    return {k: v for k, v in s.items()}


def _set_thai_fix(game_dir, font_fix, shape, tmp_font=None):
    """font_fix = บังคับฟอนต์ Tahoma · shape = จัดสระวรรณยุกต์ด้วยตัวอักษรพิเศษ (ฟอนต์ต้องมีตัวชุดนี้)"""
    proj = project.load(game_dir)
    proj["font_fix"], proj["thai_shape"] = bool(font_fix), bool(shape)
    if tmp_font is not None:
        proj["tmp_font"] = bool(tmp_font)
    proj.pop("thai_fix", None)  # ค่าเก่าจากรุ่นก่อน
    project.save(proj)
    info = unity.detect(game_dir)
    if info and info["bepinex"] and info["xunity"]:
        # เขียนทุกคำแปล (รวมที่แปลสดไปแล้ว) ลง moddi.txt ซึ่งมีความสำคัญเหนือไฟล์ที่ XUnity เก็บเอง
        unity.write_translations(game_dir, proj["translations"], proj["thai_shape"])


def _run_unity_setup(game_dir, from_lang, font_fix, shape=False, tmp_font=False):
    def prog(msg, pct):
        UJOB.update(msg=msg, pct=pct)
    try:
        _set_thai_fix(game_dir, font_fix, shape, tmp_font)
        unity.install_runtime(game_dir, prog)
        unity.write_config(game_dir, LIVE_URL, from_lang, font_fix, tmp_font)
        s = load_settings()
        s["live_game"] = os.path.abspath(game_dir)
        save_settings(s)
        UJOB.update(msg="ติดตั้งระบบแปลแล้ว เปิดเกมแล้วเล่นได้เลย", pct=100)
    except Exception as e:
        _log(traceback.format_exc())
        err = str(e)
        if "403" in err or "429" in err or "urlopen" in err or "timed out" in err:
            err = "ต่อ GitHub เพื่อโหลดระบบแปลไม่ได้ เช็กอินเทอร์เน็ต หรือรอสักพักแล้วลองใหม่"
        else:
            err = _friendly(e)
        UJOB["msg"] = "ติดตั้งไม่สำเร็จ: " + err
    finally:
        UJOB["running"] = False


def act_unity_setup(b):
    info = need_game(b.get("dir"))
    if info["kind"] != "unity":
        raise ValueError("ไม่ใช่เกม Unity")
    safety.guard(b["dir"])
    if UJOB["running"]:
        raise ValueError("กำลังติดตั้งอยู่")
    UJOB.update(running=True, pct=0, msg="กำลังเตรียมติดตั้ง")
    threading.Thread(target=_run_unity_setup, args=(b["dir"], b.get("from_lang") or "en", bool(b.get("font_fix", True)), bool(b.get("thai_shape", False)),
                           bool(b.get("tmp_font", False))),
                     daemon=True).start()
    return {"ok": True}


def act_unity_progress(_):
    return dict(UJOB)


def _ensure_unitypy():
    try:
        import UnityPy  # noqa: F401
        return True
    except ImportError:
        pass
    if FROZEN:  # ใน .exe มีตัวอ่านติดมาแล้ว ถ้า import ไม่ได้คือไฟล์เสีย ติดตั้งเพิ่มไม่ได้
        return False
    SJOB.update(msg="กำลังติดตั้งตัวอ่านไฟล์ Unity (ครั้งแรกครั้งเดียว อาจใช้เวลา 1-2 นาที)")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--user", "--disable-pip-version-check", "-q",
                        "UnityPy", "TypeTreeGeneratorAPI"], capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        _log("pip UnityPy: " + r.stderr[-2000:])
        return False
    import importlib
    import site
    site.addsitedir(site.getusersitepackages())
    importlib.invalidate_caches()
    try:
        import UnityPy  # noqa: F401,F811
        return True
    except ImportError:
        return False


def _run_scan(game_dir, lang, sig=None):
    try:
        info = need_game(game_dir)
        data_dir = os.path.join(game_dir, info["title"] + "_Data")
        _ensure_unitypy()

        def prog(msg, n, total):
            SJOB.update(msg=msg, pct=int(100 * n / max(1, total)))
        sources, assets_ok = unity_scan.scan(game_dir, data_dir, lang, prog)
        proj = project.load(game_dir)
        import time as _t
        proj["unity_scan"] = {"lang": lang, "assets_ok": assets_ok, "sig": sig, "when": _t.strftime("%Y-%m-%d %H:%M"),
                              "sources": [{k: v for k, v in x.items() if k != "texts"} for x in sources],
                              "texts": {x["id"]: x["texts"] for x in sources}}
        proj["unity_selected"] = [x["id"] for x in sources if x["default"]]
        project.save(proj)
        total = sum(x["count"] for x in sources)
        SJOB.update(pct=100, msg=f"สแกนเสร็จ เจอ {total:,} ข้อความ จาก {len(sources)} แหล่ง" if sources
                    else "สแกนเสร็จ แต่ไม่เจอข้อความที่ดึงล่วงหน้าได้ เกมนี้ต้องแปลระหว่างเล่น")
    except Exception as e:
        _log(traceback.format_exc())
        SJOB["msg"] = "สแกนไม่สำเร็จ: " + _friendly(e)
    finally:
        SJOB["running"] = False


def act_unity_scan(b):
    info = need_game(b.get("dir"))
    if info["kind"] != "unity":
        raise ValueError("ไม่ใช่เกม Unity")
    if SJOB["running"]:
        raise ValueError("กำลังสแกนอยู่")
    lang = b.get("from_lang") or "en"
    data_dir = os.path.join(b["dir"], info["title"] + "_Data")
    sig = unity_scan.fingerprint(b["dir"], data_dir, lang)
    old = project.load(b["dir"]).get("unity_scan") or {}
    if not b.get("force") and old.get("sig") == sig:
        total = sum(x.get("count", 0) for x in old.get("sources", []))
        return {"already": True, "when": old.get("when", ""), "total": total}
    SJOB.update(running=True, pct=0, msg="กำลังเริ่มสแกน")
    threading.Thread(target=_run_scan, args=(b["dir"], lang, sig), daemon=True).start()
    return {"ok": True}


def act_unity_scan_progress(_):
    return dict(SJOB)


def act_unity_select(b):
    proj = project.load(b["dir"])
    ids = {x["id"] for x in (proj.get("unity_scan") or {}).get("sources", [])}
    proj["unity_selected"] = [i for i in b.get("selected", []) if i in ids]
    project.save(proj)
    return {"ok": True}


def act_unity_live(b):
    """เปิด/ปิดการแปลสดระหว่างเล่น และตั้งภาษาต้นฉบับ"""
    info = need_game(b.get("dir"))
    if info["kind"] != "unity" or not (info["bepinex"] and info["xunity"]):
        raise ValueError("ยังไม่ได้ติดตั้งระบบแปลของเกม Unity")
    on = bool(b.get("on", True))
    if on:
        safety.guard(b["dir"])
    font_fix = bool(b.get("font_fix", True))
    unity.write_config(b["dir"], LIVE_URL if on else None, b.get("from_lang") or "en", font_fix, bool(b.get("tmp_font", False)))
    _set_thai_fix(b["dir"], font_fix, bool(b.get("thai_shape", False)), bool(b.get("tmp_font", False)))
    s = load_settings()
    s["live_game"] = os.path.abspath(b["dir"]) if on else ""
    save_settings(s)
    return {"msg": "เปิดแปลสดระหว่างเล่นแล้ว" if on else "ปิดแปลสดแล้ว เกมจะใช้แค่คำแปลที่มีอยู่"}


def live_translate(text):
    """XUnity เรียกมาทีละข้อความระหว่างเล่นเกม"""
    s = load_settings()
    game = s.get("live_game")
    if not game:
        raise ValueError("ยังไม่ได้เลือกเกมที่จะแปลสด")
    with LIVE_LOCK:
        proj = project.load(game)
        fix = proj.get("thai_shape", False)
        if text in proj["translations"]:
            return thai_shape.shape(proj["translations"][text]) if fix else proj["translations"][text]
        backend = translator.make_backend(s)
        _, failed = translator.translate_all([{"src": text}], backend, proj["translations"], proj.get("glossary"), batch=1)
        if failed:
            raise ValueError("แปลไม่สำเร็จ")
        proj.setdefault("origin", {})[text] = "p" if s.get("backend") == "api" else "f"
        project.save(proj)
        return thai_shape.shape(proj["translations"][text]) if fix else proj["translations"][text]


# ---------------------------------------------------------------- แปลพรีเมียม: รายการโมเดล + ประเมินราคา
PREMIUM_MODELS = [  # (รหัสโมเดลบน OpenRouter, ชื่อ, จุดเด่น) — แสดงเฉพาะตัวที่ยังมีอยู่จริง
    ("google/gemini-2.5-flash", "Gemini 2.5 Flash", "คุ้มสุด เร็ว ภาษาไทยดี เหมาะกับเกมทั่วไป"),
    ("deepseek/deepseek-chat-v3.1", "DeepSeek V3.1", "ถูกมาก แปลได้ดี แต่บางครั้งช้า"),
    ("openai/gpt-5-mini", "GPT-5 mini", "แม่นและสม่ำเสมอ ราคากลางๆ"),
    ("anthropic/claude-haiku-4.5", "Claude Haiku 4.5", "สำนวนเป็นธรรมชาติ เก็บน้ำเสียงตัวละครได้ดี"),
    ("google/gemini-2.5-pro", "Gemini 2.5 Pro", "คุณภาพสูง เข้าใจบริบทยาวๆ ราคาสูง"),
    ("anthropic/claude-sonnet-4.5", "Claude Sonnet 4.5", "สำนวนดีที่สุด เหมาะกับเกมเน้นเนื้อเรื่อง ราคาสูง"),
    ("openai/gpt-5", "GPT-5", "คุณภาพสูงสุดของ OpenAI ราคาสูง"),
]
_MODEL_CACHE = {"t": 0, "data": None}


def _openrouter_models():
    import time
    if _MODEL_CACHE["data"] and time.time() - _MODEL_CACHE["t"] < 3600:
        return _MODEL_CACHE["data"]
    req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers={"User-Agent": "moddi"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = {m["id"]: m for m in json.loads(r.read().decode("utf-8")).get("data", [])}
    _MODEL_CACHE.update(t=time.time(), data=data)
    return data


def estimate_tokens(texts):
    """ประเมินจำนวนโทเคน (เผื่อไว้เล็กน้อย): ภาษาอังกฤษ ~3.5 ตัวอักษร/โทเคน, จีน/ญี่ปุ่น/เกาหลี ~1 ตัว/โทเคน
    ภาษาไทยที่ได้ออกมามักกินโทเคนมากกว่าต้นฉบับประมาณ 2 เท่า"""
    src = 0
    for t in texts:
        cjk = sum(1 for c in t if "\u3040" <= c <= "\u9fff" or "\uac00" <= c <= "\ud7af")
        src += cjk + (len(t) - cjk) / 3.5 + 4
    batches = max(1, -(-len(texts) // 10))
    prompt = src * 1.1 + batches * 320          # คำสั่งระบบต่อชุด
    completion = src * 2.0 + batches * 20
    return int(prompt), int(completion)


def act_premium_quote(b):
    info = need_game(b.get("dir"))
    proj = project.load(b["dir"])
    todo = [u["src"] for u in get_units(b["dir"], info, proj) if u["src"] not in proj["translations"]]
    p_tok, c_tok = estimate_tokens(todo)
    rate = float(load_settings().get("usd_thb") or 33)
    out = {"lines": len(todo), "prompt_tokens": p_tok, "completion_tokens": c_tok, "usd_thb": rate, "models": []}
    try:
        catalog = _openrouter_models()
    except Exception:
        out["error"] = "ดึงราคาล่าสุดจาก OpenRouter ไม่ได้ ใส่ชื่อโมเดลเองได้ แต่ประเมินราคาไม่ได้"
        catalog = {}
    for mid, name, pros in PREMIUM_MODELS:
        m = catalog.get(mid)
        if not m:
            continue
        pr = m.get("pricing") or {}
        try:
            usd = p_tok * float(pr.get("prompt", 0)) + c_tok * float(pr.get("completion", 0))
        except (TypeError, ValueError):
            continue
        out["models"].append({"id": mid, "name": name, "pros": pros, "usd": round(usd, 4),
                              "thb": round(usd * rate, 2)})
    return out


def act_browse(_):
    """เปิดหน้าต่างเลือกโฟลเดอร์ของ Windows"""
    code = ("import tkinter as t, tkinter.filedialog as f; r=t.Tk(); r.withdraw(); r.attributes('-topmost', 1); "
            "print(f.askdirectory(title='เลือกโฟลเดอร์เกม (ที่มี Game.exe)') or '')")
    try:
        cmd = [sys.executable, "--browse"] if FROZEN else [sys.executable, "-c", code]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           timeout=600, creationflags=NO_WINDOW)
        if r.returncode != 0:
            raise RuntimeError(r.stderr)
        out = r.stdout.strip()
    except Exception:
        raise ValueError("เปิดหน้าต่างเลือกโฟลเดอร์ไม่ได้ วางที่อยู่โฟลเดอร์เองได้เลย")
    return {"dir": os.path.normpath(out) if out else ""}


def _ollama_exe():
    exe = shutil.which("ollama")
    if exe:
        return exe
    cand = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe")
    return cand if os.path.isfile(cand) else None


def _ollama_models():
    with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=3) as r:
        return [m["name"] for m in json.loads(r.read().decode("utf-8")).get("models", [])]


def act_ollama_status(b):
    model = (b.get("model") or "gemma3:4b").strip()
    st = {"installed": bool(_ollama_exe()), "running": False, "models": [], "has_model": False, "pull": dict(PULL)}
    try:
        st["models"] = _ollama_models()
        st["running"] = st["installed"] = True
        base = model if ":" in model else model + ":latest"
        st["has_model"] = any(m == model or m == base for m in st["models"])
    except Exception:
        pass
    return st


def act_ollama_install(_):
    if shutil.which("winget"):
        subprocess.Popen(["winget", "install", "-e", "--id", "Ollama.Ollama",
                          "--accept-package-agreements", "--accept-source-agreements"])
        return {"msg": "กำลังติดตั้ง Ollama ในหน้าต่างใหม่ ถ้า Windows ถามสิทธิ์ให้กดอนุญาต เสร็จแล้วกดตรวจอีกครั้ง"}
    webbrowser.open("https://ollama.com/download")
    return {"msg": "เปิดหน้าดาวน์โหลด Ollama ให้แล้ว ติดตั้งเสร็จแล้วกดตรวจอีกครั้ง"}


def act_ollama_start(_):
    exe = _ollama_exe()
    if not exe:
        raise ValueError("ยังไม่ได้ติดตั้ง Ollama")
    subprocess.Popen([exe, "serve"], creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"msg": "กำลังเปิด Ollama"}


def _run_pull(model):
    try:
        req = urllib.request.Request(OLLAMA_URL + "/api/pull", data=json.dumps({"name": model, "stream": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3600) as r:
            for line in r:
                if not line.strip():
                    continue
                ev = json.loads(line.decode("utf-8"))
                if ev.get("error"):
                    raise ValueError(ev["error"])
                if ev.get("total"):
                    done = ev.get("completed") or 0  # บางจังหวะ Ollama ส่งมาแค่ total
                    PULL["pct"] = int(100 * done / ev["total"])
                    PULL["msg"] = f"กำลังโหลดโมเดล {done / 1e9:.1f} / {ev['total'] / 1e9:.1f} GB"
                elif ev.get("status") == "success":
                    PULL.update(pct=100, msg="โหลดโมเดลเสร็จแล้ว พร้อมแปล")
                else:
                    PULL["msg"] = ev.get("status", "")
    except Exception as e:
        PULL["msg"] = "โหลดโมเดลไม่สำเร็จ: " + _friendly(e)
    finally:
        PULL["running"] = False


def act_ollama_pull(b):
    model = (b.get("model") or "gemma3:4b").strip()
    if PULL["running"]:
        raise ValueError("กำลังโหลดโมเดลอยู่")
    PULL.update(running=True, pct=0, msg="กำลังเริ่มโหลด " + model)
    threading.Thread(target=_run_pull, args=(model,), daemon=True).start()
    return {"ok": True}


ACTIONS = {name[4:]: fn for name, fn in globals().items() if name.startswith("act_")}


# ---------------------------------------------------------------- server
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/xunity?"):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            text = (q.get("text") or [""])[0]
            try:
                out = live_translate(text) if text.strip() else text
                return self._send(200, out.encode("utf-8"), "text/plain; charset=utf-8")
            except Exception as e:
                _log("live: " + repr(e))
                return self._send(500, str(e).encode("utf-8"), "text/plain; charset=utf-8")
        # หน้าตาเดียวกับเว็บ (site/index.html) — แอปจะเปิดแท็บ "แปลเกม" ให้ใช้งานจริง
        rel = self.path.split("?", 1)[0].split("#", 1)[0].lstrip("/") or "index.html"
        rel = urllib.parse.unquote(rel)
        path = os.path.realpath(os.path.join(SITE, rel))
        if not path.startswith(os.path.realpath(SITE) + os.sep) or not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        ctype = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
                 ".zip": "application/zip"}.get(os.path.splitext(path)[1], "application/octet-stream")
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_POST(self):
        # กันเว็บอื่นยิงคำสั่งมาที่แอปในเครื่อง
        origin = self.headers.get("Origin", "")
        if origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self._send(403, {"error": "forbidden"})
        name = self.path.strip("/").removeprefix("api/")
        fn = ACTIONS.get(name)
        if not fn:
            return self._send(404, {"error": "ไม่มีคำสั่งนี้"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, fn(body))
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except Exception as e:
            _log(traceback.format_exc())
            self._send(400, {"error": _friendly(e)})


def _log(text):
    try:
        os.makedirs(project.APP_DIR, exist_ok=True)
        with open(os.path.join(project.APP_DIR, "log.txt"), "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- อัปเดตตัวเอง (เฉพาะ moddi.exe)
REPO = "crowmainew-blip/Moddi"
LATEST = f"https://github.com/{REPO}/releases/latest/download/"


def build_info():
    try:
        with open(os.path.join(HERE, "build.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"version": "dev", "build": 0}


def act_update_check(_):
    cur = build_info()
    out = {"current": cur, "frozen": bool(FROZEN), "available": False}
    if not FROZEN:
        return out  # รันจากโค้ด ไม่ต้องอัปเดตตัวเอง
    try:
        req = urllib.request.Request(LATEST + "latest.json", headers={"User-Agent": "moddi"})
        with urllib.request.urlopen(req, timeout=8) as r:
            new = json.loads(r.read().decode("utf-8"))
        out["latest"] = new
        out["available"] = int(new.get("build", 0)) > int(cur.get("build", 0))
    except Exception as e:
        _log("update check: " + repr(e))
    return out


def act_update_apply(_):
    if not FROZEN:
        raise ValueError("อัปเดตอัตโนมัติใช้ได้กับ moddi.exe เท่านั้น")
    import tempfile
    exe = sys.executable
    tmp = os.path.join(tempfile.gettempdir(), "moddi-new.exe")
    req = urllib.request.Request(LATEST + "moddi.exe", headers={"User-Agent": "moddi"})
    with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    if os.path.getsize(tmp) < 5_000_000:
        raise ValueError("ดาวน์โหลดไฟล์อัปเดตไม่ครบ ลองใหม่อีกครั้ง")
    bat = os.path.join(tempfile.gettempdir(), "moddi-update.bat")
    with open(bat, "w", encoding="utf-8") as f:  # รอแอปเดิมปิด แล้ววางไฟล์ใหม่ทับ แล้วเปิดใหม่
        f.write(f'@echo off\r\nchcp 65001 >nul\r\n:w\r\ntimeout /t 1 /nobreak >nul\r\n'
                f'tasklist /fi "PID eq {os.getpid()}" | find "{os.getpid()}" >nul && goto w\r\n'
                f'move /y "{tmp}" "{exe}" >nul\r\nstart "" "{exe}" --no-browser\r\ndel "%~f0"\r\n')
    subprocess.Popen(["cmd", "/c", bat], creationflags=NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0))
    threading.Timer(1.0, lambda: os._exit(0)).start()
    return {"msg": "กำลังอัปเดต แอปจะเปิดใหม่เองในไม่กี่วินาที"}


ACTIONS.update(update_check=act_update_check, update_apply=act_update_apply)


def _browse_child():
    import tkinter as t
    import tkinter.filedialog as f
    r = t.Tk()
    r.withdraw()
    r.attributes("-topmost", 1)
    sys.stdout.reconfigure(encoding="utf-8")
    print(f.askdirectory(title="เลือกโฟลเดอร์เกม (ที่มี Game.exe)") or "")


def _selftest():
    """ใช้ตอน build: เช็คว่าไฟล์และไลบรารีที่ต้องใช้ติดมาใน .exe ครบ"""
    import UnityPy  # noqa: F401
    from core import unity, unity_scan, rpgmaker, thai_shape, safety, engines  # noqa: F401
    for need in ("site/index.html", "site/catalog.json", "fonts/" + rpgmaker.FONT_NAME):
        assert os.path.isfile(os.path.join(HERE, need)), need
    try:
        from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator  # noqa: F401
        tt = "ok"
    except Exception as e:
        tt = "missing (" + type(e).__name__ + ")"
    print("selftest ok · typetree", tt)


def main():
    if "--browse" in sys.argv:
        return _browse_child()
    if "--selftest" in sys.argv:
        return _selftest()
    url = f"http://127.0.0.1:{PORT}/"
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print("moddi เปิดอยู่แล้ว กำลังเปิดหน้าแอปให้")
        webbrowser.open(url)
        return
    print("moddi เปิดอยู่ที่", url, "(ปิดหน้าต่างนี้เพื่อออก)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
