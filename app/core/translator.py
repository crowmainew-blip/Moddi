"""ตัวแปล: ออฟไลน์ (Ollama), API แบบ OpenAI-compatible (OpenAI / OpenRouter / Typhoon ฯลฯ) และตัวทดสอบ

- ป้องกันโค้ดพิเศษในเกม เช่น \\V[1] \\C[2] %1 ไม่ให้ AI แปลทับ
- แปลทีละชุด (batch) เพื่อความเร็ว ถ้าชุดไหนพัง ค่อยแปลทีละบรรทัด
- จำคำแปลไว้ (translation memory) บรรทัดที่เคยแปลแล้วไม่ต้องแปลซ้ำ
- อภิธานศัพท์ (glossary) บังคับชื่อตัวละคร/สกิลให้แปลเหมือนกันทั้งเกม
"""
import json
import re
import urllib.request

CODE_RE = re.compile(
    r"\\[A-Za-z]+\[[^\]]*\]"      # \V[1] \C[2] \FS[24]
    r"|\\[A-Za-z]+<[^>]*>"         # \n<ชื่อ> ของปลั๊กอินบางตัว
    r"|\\[A-Za-z]+"                # \G
    r"|\\[{}\\$.|!><^]"            # \{ \. \| \! ...
    r"|%\d"                        # %1 %2 ในข้อความระบบ
    r"|\{\d+\}"                     # {0} {1} ของเกม Unity
    r"|</?[A-Za-z][^<>\n]{0,40}>"     # <color=#fff> </b> <br> และแท็กปลั๊กอิน
)

SYSTEM_PROMPT = (
    "คุณคือนักแปลเกมมืออาชีพ แปลข้อความในเกมเป็นภาษาไทยที่เป็นธรรมชาติ อ่านลื่น เหมาะกับเกม\n"
    "กฎ:\n"
    "1. รักษาสัญลักษณ์ ⟦0⟧ ⟦1⟧ ... ไว้ครบและไม่แก้ไข (เป็นโค้ดของเกม)\n"
    "2. ข้อความที่มีหลายบรรทัด (คั่นด้วย \\n) ให้คงจำนวนบรรทัดเท่าเดิม\n"
    "3. ชื่อเฉพาะให้ใช้ตามอภิธานศัพท์ถ้ามี ถ้าไม่มีให้ทับศัพท์\n"
    "   ชื่อแบรนด์ แพลตฟอร์ม และบริษัท (เช่น Steam, Xbox, PlayStation, Windows, Nintendo, Discord) ห้ามแปล ให้คงภาษาอังกฤษไว้\n"
    "4. ตอบกลับเป็น JSON เท่านั้น รูปแบบ {\"t\": [\"คำแปล1\", \"คำแปล2\", ...]} "
    "จำนวนและลำดับต้องตรงกับที่ส่งไป"
)


def protect(text):
    codes = []

    def sub(m):
        codes.append(m.group(0))
        return "⟦%d⟧" % (len(codes) - 1)

    return CODE_RE.sub(sub, text), codes


def restore(text, codes):
    for i, c in enumerate(codes):
        text = text.replace("⟦%d⟧" % i, c)
    return text


def valid(protected_src, out, codes):
    if not isinstance(out, str) or not out.strip():
        return False
    for i in range(len(codes)):
        if out.count("⟦%d⟧" % i) != protected_src.count("⟦%d⟧" % i):
            return False
    if any(int(n) >= len(codes) for n in re.findall(r"⟦(\d+)⟧", out)):
        return False
    return True


def fix_lines(src, out):
    """บังคับจำนวนบรรทัดให้เท่าต้นฉบับ (กล่องข้อความเกมมีที่จำกัด)"""
    n = src.count("\n") + 1
    lines = [l for l in out.split("\n")]
    if len(lines) == n:
        return out
    if len(lines) > n:  # รวมบรรทัดเกินเข้าบรรทัดสุดท้าย
        return "\n".join(lines[: n - 1] + [" ".join(lines[n - 1:])])
    return "\n".join(lines + [""] * (n - len(lines)))


# ---------------------------------------------------------------- backends
def _post(url, payload, headers, timeout=300):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class MockBackend:
    """ไว้ทดสอบ ไม่ได้แปลจริง"""
    name = "mock"

    def chat(self, system, user):
        items = json.loads(user.split("แปลรายการนี้:\n", 1)[1])
        return json.dumps({"t": ["[ไทย] " + s.replace("\n", "\n[ไทย] ") for s in items]}, ensure_ascii=False)


class OllamaBackend:
    """แปลออฟไลน์ในเครื่อง ผ่านโปรแกรม Ollama (ollama.com)"""
    name = "ollama"

    def __init__(self, model="gemma3:4b", url="http://127.0.0.1:11434"):
        self.model, self.url = model, url.rstrip("/")

    def chat(self, system, user):
        r = _post(self.url + "/api/chat", {
            "model": self.model, "stream": False, "format": "json",
            "options": {"temperature": 0.2},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }, {})
        return r["message"]["content"]


class OpenAICompatBackend:
    """API แบบ OpenAI-compatible: OpenAI, OpenRouter (เลือกได้หลายร้อยโมเดล), Typhoon ฯลฯ"""
    name = "api"

    def __init__(self, base_url, api_key, model):
        self.base, self.key, self.model = base_url.rstrip("/"), api_key, model

    def chat(self, system, user):
        r = _post(self.base + "/chat/completions", {
            "model": self.model, "temperature": 0.2,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }, {"Authorization": "Bearer " + self.key})
        return r["choices"][0]["message"]["content"]


def make_backend(cfg):
    kind = cfg.get("backend", "ollama")
    if kind == "mock":
        return MockBackend()
    if kind == "api":
        return OpenAICompatBackend(cfg["base_url"], cfg.get("api_key", ""), cfg["model"])
    return OllamaBackend(cfg.get("model") or "gemma3:4b", cfg.get("ollama_url") or "http://127.0.0.1:11434")


# ---------------------------------------------------------------- แปล
def _parse(raw, n):
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("AI ไม่ตอบเป็น JSON")
    data = json.loads(m.group(0))
    t = data.get("t") or data.get("translations")
    if not isinstance(t, list) or len(t) != n:
        raise ValueError("จำนวนคำแปลไม่ตรง")
    return t


def _glossary_note(glossary, texts):
    hits = {k: v for k, v in glossary.items() if any(k in s for s in texts)}
    if not hits:
        return ""
    return "อภิธานศัพท์ (ต้องใช้ตามนี้): " + json.dumps(hits, ensure_ascii=False) + "\n"


def translate_all(units, backend, memory, glossary=None, batch=20, progress=None, stop=None):
    """แปลทุกหน่วยที่ยังไม่มีใน memory; memory ถูกอัปเดตในที่ คืนค่า (แปลใหม่, ล้มเหลว)"""
    glossary = glossary or {}
    todo = [u["src"] for u in units if u["src"] not in memory]
    done, failed = 0, []
    total = len(todo)
    dead_batches, last_err = 0, None
    for start in range(0, total, batch):
        if stop and stop():
            break
        chunk = todo[start:start + batch]
        prot = [protect(s) for s in chunk]
        texts = [p[0] for p in prot]
        results = [None] * len(chunk)
        batch_err = None
        try:
            out = _parse(backend.chat(SYSTEM_PROMPT, _glossary_note(glossary, chunk) + "แปลรายการนี้:\n"
                                      + json.dumps(texts, ensure_ascii=False)), len(chunk))
            for i, o in enumerate(out):
                if valid(texts[i], o, prot[i][1]):
                    results[i] = o
        except (OSError, KeyError) as e:   # ต่อไม่ติด / โมเดลไม่มี / API ตอบผิดรูปแบบ
            batch_err = e
        except Exception:
            pass
        if batch_err is not None:
            dead_batches += 1
            last_err = batch_err
            if dead_batches >= 3 and done == 0:
                raise RuntimeError(f"ตัวแปลใช้งานไม่ได้: {last_err}")
            if dead_batches >= 3:
                raise RuntimeError(f"ตัวแปลหยุดตอบ: {last_err} (บรรทัดที่แปลแล้วถูกบันทึกไว้ กดแปลต่อได้)")
            failed.extend(chunk)
            if progress:
                progress(min(start + batch, total), total)
            continue
        dead_batches = 0
        for i, src in enumerate(chunk):  # แปลทีละบรรทัดสำหรับตัวที่พัง
            if results[i] is None:
                try:
                    o = _parse(backend.chat(SYSTEM_PROMPT, _glossary_note(glossary, [src]) + "แปลรายการนี้:\n"
                                            + json.dumps([texts[i]], ensure_ascii=False)), 1)[0]
                    if valid(texts[i], o, prot[i][1]):
                        results[i] = o
                except Exception:
                    pass
            if results[i] is None:
                failed.append(src)
            else:
                memory[src] = fix_lines(src, restore(results[i], prot[i][1]))
                done += 1
        if progress:
            progress(min(start + batch, total), total)
    return done, failed
