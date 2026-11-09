"""สแกนหาข้อความในเกม Unity ล่วงหน้า เพื่อแปลทั้งเกมโดยไม่ต้องเล่น

แหล่งที่สแกน
1. ไฟล์ภาษาที่เปิดอ่านได้ (StreamingAssets ฯลฯ): csv, tsv, json, xml, po, txt, yarn, ink
2. ไฟล์ asset ของ Unity ผ่าน UnityPy: TextAsset และ MonoBehaviour (เช่น I2 Localization)
3. ข้อความที่เขียนไว้ในโค้ด: Assembly-CSharp.dll (Mono) หรือ global-metadata.dat (IL2CPP)

ทุกแหล่งผ่านตัวกรอง "หน้าตาเหมือนข้อความที่คนอ่าน" เพื่อตัดชื่อไฟล์ คีย์ และโค้ดทิ้ง
ผลลัพธ์แยกตามแหล่ง ให้ผู้ใช้เลือกเองว่าจะแปลแหล่งไหน
"""
import csv
import io
import json
import os
import re
import struct
import xml.etree.ElementTree as ET

SKIP_FILES = {"unityservicesprojectconfiguration.json", "settings.json", "config.json", "manifest.json",
              "steam_appid.txt", "doorstop_config.ini", "boot.config", "runtimeinitializeonloads.json",
              "scriptingassemblies.json", "unitysubsystemsmanifest.json", "app.info", "moddi_unity.json"}
SCANNER_VERSION = "2026.11.10b"   # เปลี่ยนเมื่อปรับตัวกรอง ผลสแกนเก่าจะถือว่าเก่า


def fingerprint(game_dir, data_dir, lang):
    """ลายนิ้วมือของไฟล์เกมที่เกี่ยวกับการสแกน: เปลี่ยนเมื่อเกมอัปเดต ลง DLC หรือ moddi ปรับตัวกรอง"""
    import hashlib
    h = hashlib.sha1(f"{SCANNER_VERSION}|{lang}".encode())
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = sorted(d for d in dirs if d.lower() not in ("bepinex", "moddi_backup", "moddi_unity_backup"))
        for f in sorted(files):
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            h.update(f"{os.path.relpath(p, game_dir)}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8", "ignore"))
    return h.hexdigest()


TEXT_EXT = {".csv", ".tsv", ".json", ".xml", ".po", ".txt", ".yarn", ".ink", ".lang", ".loc"}
SKIP_DIRS = {"bepinex", "managed", "monobleedingedge", "il2cpp_data", "moddi_backup", "moddi_unity_backup", "plugins", "baselib"}
LANG_HEADERS = {
    "en": {"en", "eng", "english", "en-us", "en_us", "en-gb", "english(en)"},
    "ja": {"ja", "jp", "jpn", "japanese", "ja-jp", "日本語"},
    "zh": {"zh", "cn", "chs", "chinese", "zh-cn", "zh_cn", "zh-hans", "schinese", "简体中文", "中文"},
    "ko": {"ko", "kr", "kor", "korean", "ko-kr", "한국어"},
}
CJK = re.compile(r"[぀-ヿ㐀-鿿]")
HANGUL = re.compile(r"[가-힯]")
LATIN = re.compile(r"[A-Za-z]")
CODEY = set("{}()[];=<>|\\$#@")
URLISH = re.compile(r"^(https?:|www\.|[a-z]:\\|/)|\.(png|jpg|wav|ogg|mp3|prefab|asset|unity|mat|cs|dll|json|xml|txt|csv|shader|anim)$", re.I)


EN_WORDS = set("the a an of and to in is it you your for on with this that are be not or as at by from can will have has was we they he she his her my me our all no yes more".split())
OTHER_WORDS = set((
    "le la les des du un une et est pas pour que qui dans sur avec vous nous ce cette sont "        # ฝรั่งเศส
    "der die das und ist nicht ein eine zu mit von den dem sie ich wir auf für sind "              # เยอรมัน
    "el los las del y es una por con para que se su sus al lo como más "                          # สเปน
    "il di che non per una sono gli della nel con è "                                             # อิตาลี
    "o os da do das dos em um uma não com para são você "                                         # โปรตุเกส
    "og er ikke det på av til jeg du vi ze nie jest się na w z do że to bir ve bu"                # อื่นๆ
).split())
ACCENTS = re.compile(r"[àâçéèêëîïôûùüÿœæäößñáíóú¿¡ãõąćęłńśźżğışÀÂÇÉÈÊËÎÏÔÛÙÜŸŒÆÄÖÑÁÍÓÚÃÕ]")


CODE_NAME = re.compile(
    r"PublicKeyToken=|Culture=neutral|Version=\d+\.\d+\.\d+"          # ชื่อ assembly ของ .NET
    r"|\b[A-Z][A-Za-z0-9]+(\.[A-Z][A-Za-z0-9]+){2,}\b"                    # Namespace.Class.Member
    r"|\b(System|UnityEngine|Unity|Microsoft|Steamworks|Newtonsoft)\.[A-Z]"  # namespace ที่รู้จัก
    r"|\b[a-z]+(_[a-z0-9]+){2,}\b"                                         # snake_case_key_name
    r"|\{\s*\"|\"\s*:\s*[\[{\"]"                                            # JSON ที่ฝังอยู่ในข้อความ
)


def is_english(s):
    """แยกภาษาอังกฤษออกจากภาษายุโรปอื่นที่ใช้ตัวอักษรละตินเหมือนกัน"""
    words = re.findall(r"[a-zà-ÿ']+", s.lower())
    en = sum(1 for w in words if w in EN_WORDS)
    other = sum(1 for w in words if w in OTHER_WORDS and w not in EN_WORDS)
    accents = len(ACCENTS.findall(s))
    if accents >= 2 or (accents == 1 and (en == 0 or other >= 1)):
        return False
    if len(words) >= 3 and other > en:
        return False
    return True


def looks_like_text(s, lang="en"):
    """ตัวกรอง: ข้อความนี้น่าจะเป็นข้อความที่แสดงให้ผู้เล่นอ่านไหม"""
    if not isinstance(s, str):
        return False
    s = s.strip()
    if not (2 <= len(s) <= 4000) or "\x00" in s:
        return False
    if sum(1 for c in s if ord(c) < 32 and c not in "\n\r\t") > 0:
        return False
    if URLISH.search(s) or re.fullmatch(r"[0-9a-fA-F\-]{16,}", s) or re.fullmatch(r"[\d\s.,:%+\-/]+", s):
        return False
    if lang in ("ja", "zh"):
        return bool(CJK.search(s))
    if lang == "ko":
        return bool(HANGUL.search(s))
    if not LATIN.search(s):
        return False
    if CODE_NAME.search(s):
        return False  # ชื่อระบบภายในของ .NET / Unity เช่น "Version=0.0.0.0, Culture=neutral" หรือ Unity.Services.Core
    if re.search(r"[\u0E00-\u0E7F]", s):
        return False  # มีภาษาไทยอยู่แล้ว (มักมาจากม็อดไทยของคนอื่น) ไม่ใช่ต้นฉบับ
    if lang == "en" and not is_english(s):
        return False
    plain = re.sub(r"</?[A-Za-z][^<>]{0,40}>|\{\d+\}", "", s)  # ไม่นับแท็ก rich text และ {0}
    if sum(1 for c in plain if c in CODEY) > max(2, len(plain) * 0.12):
        return False
    if " " not in s:
        # คำเดียว: รับเฉพาะแบบ "Start", "OPTIONS", "HP" ไม่รับ snake_case, camelCase, a.b.c
        if any(c in s for c in "_./:") or re.search(r"[a-z][A-Z]", s) or re.search(r"\d[A-Za-z]|[A-Za-z]\d", s):
            return False
        return bool(re.fullmatch(r"[A-Z][a-z']{1,20}[!?.]?|[A-Z]{2,20}[!?.]?", s))
    words = s.split()
    if sum(1 for w in words if "_" in w or re.search(r"[a-z][A-Z]", w)) > len(words) / 2:
        return False
    return True


# ---------------------------------------------------------------- file parsers
def _decode(raw):
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def parse_csv(text, lang, delim=None):
    if delim is None:
        first = text.split("\n", 1)[0]
        delim = "\t" if first.count("\t") > first.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    col = next((i for i, h in enumerate(header) if h in LANG_HEADERS.get(lang, set())), None)
    out = []
    if col is not None:
        for r in rows[1:]:
            if col < len(r) and looks_like_text(r[col], lang):
                out.append(r[col].strip())
        return out
    for r in rows:
        for cell in r:
            if looks_like_text(cell, lang):
                out.append(cell.strip())
    return out


def walk_json(obj, lang, out, key=None):
    if isinstance(obj, dict):
        # รูปแบบ {"en": "...", "ja": "..."} → เอาเฉพาะภาษาต้นฉบับ
        hit = [k for k in obj if isinstance(k, str) and k.strip().lower() in LANG_HEADERS.get(lang, set())]
        if hit and isinstance(obj[hit[0]], str):
            if looks_like_text(obj[hit[0]], lang):
                out.append(obj[hit[0]].strip())
            return
        for k, v in obj.items():
            walk_json(v, lang, out, k)
    elif isinstance(obj, list):
        for v in obj:
            walk_json(v, lang, out, key)
    elif isinstance(obj, str):
        if looks_like_text(obj, lang):
            out.append(obj.strip())


def parse_json(text, lang):
    try:
        data = json.loads(text)
    except Exception:
        return []
    out = []
    walk_json(data, lang, out)
    return out


def parse_xml(text, lang):
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except Exception:
        return []
    out = []
    for el in root.iter():
        for t in (el.text, el.tail):
            if t and looks_like_text(t, lang):
                out.append(t.strip())
        for k, v in el.attrib.items():
            if k.lower() in ("text", "value", "label", "title", "desc", "description", "name") and looks_like_text(v, lang):
                out.append(v.strip())
    return out


def parse_po(text, lang):
    out = []
    for m in re.finditer(r'^msgid\s+((?:"(?:[^"\\]|\\.)*"\s*)+)', text, re.M):
        s = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1)))
        s = s.encode("utf-8").decode("unicode_escape", errors="ignore") if "\\" in s else s
        if looks_like_text(s, lang):
            out.append(s.strip())
    return out


def parse_lines(text, lang):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("//", "#", "<<", "->", "===", "---", "title:", "tags:", "position:", "VAR ", "~", "INCLUDE")):
            continue
        line = re.sub(r"\s*#line:\w+$", "", line)            # Yarn line id
        m = re.match(r"^([A-Za-z฀-๿][\w ฀-๿]{0,24}):\s+(.+)$", line)  # "Name: text"
        if m:
            line = m.group(2)
        line = re.sub(r"^\*+\s*|\s*->\s*\w+$", "", line)      # Ink choices / diverts
        line = re.sub(r"\[([^\]]*)\]", r"\1", line).strip()
        if looks_like_text(line, lang):
            out.append(line)
    return out


def parse_text_blob(text, lang, name=""):
    """เดารูปแบบจากเนื้อหา (ใช้กับ TextAsset ที่ไม่มีนามสกุล)"""
    t = text.lstrip()
    ext = os.path.splitext(name.lower())[1]
    if ext == ".po" or t.startswith("msgid"):
        return parse_po(text, lang)
    if t[:1] in "{[" or ext == ".json":
        r = parse_json(text, lang)
        if r:
            return r
    if t.startswith("<") or ext == ".xml":
        r = parse_xml(text, lang)
        if r:
            return r
    lines = [l for l in text.splitlines()[:20] if l.strip()]
    if ext in (".csv", ".tsv") or (len(lines) > 2 and all(l.count(",") >= 1 or l.count("\t") >= 1 for l in lines)):
        return parse_csv(text, lang)
    return parse_lines(text, lang)


def scan_loose_files(game_dir, lang, progress=None):
    """ไฟล์ข้อความที่วางอยู่ในโฟลเดอร์เกม"""
    sources = []
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in TEXT_EXT:
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, game_dir)
            fl = f.lower()
            if (fl.startswith(("readme", "changelog", "license", "licence", "eula", "credits", "third", "notice", "patch_notes"))
                    or fl in SKIP_FILES or fl.endswith((".deps.json", ".runtimeconfig.json"))
                    or os.path.getsize(p) > 30 * 1024 * 1024):
                continue
            if root == game_dir and ext == ".txt":
                continue  # ไฟล์ .txt ที่วางไว้หน้าสุดของเกมมักเป็นคู่มือหรือไฟล์ของม็อดอื่น
            with open(p, "rb") as fh:
                text = _decode(fh.read())
            if ext in (".csv", ".tsv"):
                found = parse_csv(text, lang, "\t" if ext == ".tsv" else None)
            elif ext == ".json":
                found = parse_json(text, lang)
            elif ext == ".xml":
                found = parse_xml(text, lang)
            elif ext == ".po":
                found = parse_po(text, lang)
            else:
                found = parse_lines(text, lang)
            if found:
                sources.append({"id": "file:" + rel, "label": rel, "kind": "file", "texts": found})
    return sources


# ---------------------------------------------------------------- Unity assets (UnityPy)
def _raw_strings(raw, lang):
    """อ่าน string ที่ Unity เก็บแบบ (ความยาว int32 + utf-8 + เติมให้ครบ 4 ไบต์) โดยไม่ต้องรู้โครงสร้าง"""
    out, i, n = [], 0, len(raw)
    while i + 4 <= n:
        ln = struct.unpack_from("<i", raw, i)[0]
        if 2 <= ln <= 4000 and i + 4 + ln <= n:
            chunk = raw[i + 4:i + 4 + ln]
            try:
                s = chunk.decode("utf-8")
            except UnicodeDecodeError:
                s = None
            if s and looks_like_text(s, lang):
                out.append(s.strip())
                i += 4 + ((ln + 3) & ~3)
                continue
        i += 4
    return out


def _walk_tree(obj, lang, out, depth=0):
    if depth > 40:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("m_Name", "m_Script", "m_GameObject", "m_EditorClassIdentifier", "guid", "id", "key", "Key", "Term"):
                continue
            _walk_tree(v, lang, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _walk_tree(v, lang, out, depth + 1)
    elif isinstance(obj, str) and looks_like_text(obj, lang):
        out.append(obj.strip())


def _i2_terms(tree, lang):
    """I2 Localization: mSource.mLanguages + mSource.mTerms[].Languages[]"""
    src = tree.get("mSource") if isinstance(tree, dict) else None
    if not isinstance(src, dict) or "mTerms" not in src:
        return None
    langs = [str(l.get("Code") or l.get("Name") or "").lower() for l in src.get("mLanguages", [])]
    names = LANG_HEADERS.get(lang, set())
    idx = next((i for i, c in enumerate(langs) if c in names or c.split("-")[0] in names), 0)
    out = []
    for t in src.get("mTerms", []):
        vals = t.get("Languages") or []
        if idx < len(vals) and looks_like_text(vals[idx], lang):
            out.append(vals[idx].strip())
    return out


def _asset_files(data_dir):
    for root, dirs, files in os.walk(data_dir):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
        for f in files:
            fl = f.lower()
            if fl.endswith((".assets", ".bundle", ".unity3d", ".ab")) or re.fullmatch(r"level\d+", fl) or fl in ("data.unity3d", "globalgamemanagers"):
                yield os.path.join(root, f)


def scan_assets(game_dir, data_dir, lang, progress=None):
    try:
        import UnityPy
    except ImportError:
        return None  # ให้แอปติดตั้งก่อน
    gen = None
    try:
        from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator
        gen_ok = True
    except Exception:
        gen_ok = False
    files = list(_asset_files(data_dir))
    text_assets, behaviours = {}, {}
    for n, path in enumerate(files):
        if progress:
            progress(f"กำลังอ่าน {os.path.basename(path)}", n, len(files))
        try:
            env = UnityPy.load(path)
        except Exception:
            continue
        if gen_ok and gen is None:
            try:
                ver = next((o.assets_file.unity_version for o in env.objects), None)
                if ver:
                    gen = TypeTreeGenerator(ver)
                    gen.load_local_game(game_dir)
            except Exception:
                gen, gen_ok = None, False
        if gen is not None:
            env.typetree_generator = gen
        for obj in env.objects:
            tname = obj.type.name
            if tname == "TextAsset":
                try:
                    d = obj.read()
                    name = d.m_Name or "TextAsset"
                    script = d.m_Script
                    if isinstance(script, (bytes, bytearray)):
                        script = _decode(bytes(script))
                    else:
                        script = script.encode("utf-8", "surrogateescape").decode("utf-8", "ignore")
                    found = parse_text_blob(script, lang, name)
                    if found:
                        text_assets.setdefault(name, []).extend(found)
                except Exception:
                    continue
            elif tname == "MonoBehaviour":
                found, label = None, None
                try:
                    tree = obj.read_typetree()
                    label = _script_name(obj, tree) or "MonoBehaviour"
                    found = _i2_terms(tree, lang)
                    if found is not None:
                        label = "I2 Localization"
                    else:
                        found = []
                        _walk_tree(tree, lang, found)
                except Exception:
                    try:
                        label = "MonoBehaviour (อ่านแบบดิบ)"
                        found = _raw_strings(obj.get_raw_data(), lang)
                    except Exception:
                        found = None
                if found:
                    behaviours.setdefault(label, []).extend(found)
    sources = []
    for name, texts in sorted(text_assets.items()):
        sources.append({"id": "textasset:" + name, "label": "TextAsset · " + name, "kind": "asset", "texts": texts})
    for label, texts in sorted(behaviours.items(), key=lambda kv: -len(kv[1])):
        sources.append({"id": "mono:" + label, "label": "MonoBehaviour · " + label, "kind": "asset", "texts": texts})
    return sources


def _script_name(obj, tree):
    """ชื่อคลาสของสคริปต์ MonoBehaviour (เช่น LanguageSourceAsset) ถ้าหาได้"""
    try:
        ptr = tree.get("m_Script") if isinstance(tree, dict) else None
        if ptr and ptr.get("m_FileID", 0) == 0 and ptr.get("m_PathID"):
            script = obj.assets_file.objects.get(ptr["m_PathID"])
            if script is not None:
                return script.read().m_ClassName
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- strings in code
def dotnet_user_strings(raw):
    """อ่าน #US heap ของไฟล์ .NET (ข้อความที่เขียนไว้ในโค้ด C#)"""
    if raw[:2] != b"MZ":
        return []
    pe = struct.unpack_from("<I", raw, 0x3C)[0]
    if raw[pe:pe + 4] != b"PE\0\0":
        return []
    nsec = struct.unpack_from("<H", raw, pe + 6)[0]
    opt_size = struct.unpack_from("<H", raw, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", raw, opt)[0]
    dd = opt + (96 if magic == 0x10B else 112)
    cli_rva = struct.unpack_from("<I", raw, dd + 14 * 8)[0]
    secs = []
    sec = opt + opt_size
    for i in range(nsec):
        vsize, va, rsize, rptr = struct.unpack_from("<IIII", raw, sec + i * 40 + 8)
        secs.append((va, max(vsize, rsize), rptr))

    def off(rva):
        for va, size, rptr in secs:
            if va <= rva < va + size:
                return rva - va + rptr
        raise ValueError("bad rva")

    cli = off(cli_rva)
    md = off(struct.unpack_from("<I", raw, cli + 8)[0])
    if struct.unpack_from("<I", raw, md)[0] != 0x424A5342:
        return []
    vlen = struct.unpack_from("<I", raw, md + 12)[0]
    p = md + 16 + vlen + 2
    nstreams = struct.unpack_from("<H", raw, p)[0]
    p += 2
    us = None
    for _ in range(nstreams):
        s_off, s_size = struct.unpack_from("<II", raw, p)
        name_end = raw.index(b"\0", p + 8)
        name = raw[p + 8:name_end].decode("ascii", "ignore")
        p = (name_end + 4) & ~3
        if name == "#US":
            us = (md + s_off, s_size)
    if not us:
        return []
    start, size = us
    out, i = [], 1
    while i < size:
        b0 = raw[start + i]
        if b0 & 0x80 == 0:
            ln, hdr = b0, 1
        elif b0 & 0xC0 == 0x80:
            ln, hdr = ((b0 & 0x3F) << 8) | raw[start + i + 1], 2
        else:
            ln = ((b0 & 0x1F) << 24) | (raw[start + i + 1] << 16) | (raw[start + i + 2] << 8) | raw[start + i + 3]
            hdr = 4
        if ln == 0:
            i += hdr
            continue
        data = raw[start + i + hdr:start + i + hdr + ln - 1]
        try:
            out.append(data.decode("utf-16-le"))
        except UnicodeDecodeError:
            pass
        i += hdr + ln
    return out


def il2cpp_string_literals(raw):
    """อ่าน string literal จาก global-metadata.dat (IL2CPP)"""
    if len(raw) < 32 or struct.unpack_from("<I", raw, 0)[0] != 0xFAB11BAF:
        return []
    lit_off, lit_size, data_off, data_size = struct.unpack_from("<iiii", raw, 8)
    if not (0 < lit_off < len(raw) and 0 < data_off < len(raw) and lit_size % 8 == 0):
        return []
    out, bad = [], 0
    for k in range(lit_size // 8):
        ln, idx = struct.unpack_from("<Ii", raw, lit_off + k * 8)
        if idx < 0 or idx + ln > data_size:
            bad += 1
            continue
        try:
            out.append(raw[data_off + idx:data_off + idx + ln].decode("utf-8"))
        except UnicodeDecodeError:
            bad += 1
    if bad > max(10, (lit_size // 8) // 10):
        return []  # รูปแบบไม่ตรง (เวอร์ชันใหม่ หรือไฟล์ถูกเข้ารหัส)
    return out


def scan_code(data_dir, lang):
    sources = []
    managed = os.path.join(data_dir, "Managed")
    for dll in ("Assembly-CSharp.dll", "Assembly-CSharp-firstpass.dll"):
        p = os.path.join(managed, dll)
        if os.path.isfile(p):
            try:
                with open(p, "rb") as f:
                    found = [s.strip() for s in dotnet_user_strings(f.read()) if looks_like_text(s, lang)]
            except Exception:
                found = []
            if found:
                sources.append({"id": "code:" + dll, "label": "ข้อความในโค้ด · " + dll, "kind": "code", "texts": found})
    meta = os.path.join(data_dir, "il2cpp_data", "Metadata", "global-metadata.dat")
    if os.path.isfile(meta):
        with open(meta, "rb") as f:
            found = [s.strip() for s in il2cpp_string_literals(f.read()) if looks_like_text(s, lang)]
        if found:
            sources.append({"id": "code:global-metadata", "label": "ข้อความในโค้ด · global-metadata.dat", "kind": "code", "texts": found})
    return sources


# ---------------------------------------------------------------- main
def scan(game_dir, data_dir, lang="en", progress=None):
    """คืนค่า (sources, assets_ok) โดย sources = [{id,label,kind,count,samples,texts,default}]"""
    if progress:
        progress("กำลังสแกนไฟล์ภาษา", 0, 1)
    sources = scan_loose_files(game_dir, lang, progress)
    assets = scan_assets(game_dir, data_dir, lang, progress)
    assets_ok = assets is not None
    sources += assets or []
    if progress:
        progress("กำลังสแกนข้อความในโค้ด", 1, 1)
    sources += scan_code(data_dir, lang)
    seen, final = set(), []
    for s in sources:
        uniq = []
        for t in s["texts"]:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        if uniq:
            final.append({"id": s["id"], "label": s["label"], "kind": s["kind"], "count": len(uniq),
                          "samples": uniq[:4], "texts": uniq, "default": s["kind"] != "code"})
    return final, assets_ok
