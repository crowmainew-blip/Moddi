"""จัดตำแหน่งสระและวรรณยุกต์ไทยสำหรับเกมที่ไม่รองรับการจัดตัวอักษรไทย (เช่น Unity)

ใช้ตัวอักษรรูปแบบพิเศษในช่วง U+F700–U+F71A (Private Use Area) ที่ฟอนต์ไทยของ Windows
อย่าง Tahoma มีไว้สำหรับวางสระ/วรรณยุกต์ในตำแหน่งที่ถูกต้องอยู่แล้ว
ต้องใช้คู่กับฟอนต์ที่มีตัวอักษรชุดนี้ (moddi ตั้ง Tahoma ให้)
"""

ASCENDER = set("ปฝฟฬ")          # พยัญชนะหางยาวขึ้นบน
DESC_REMOVABLE = {"ญ": "", "ฐ": ""}   # หางล่างที่ต้องตัดออกเมื่อมีสระล่าง
DESC_KEEP = set("ฎฏ")             # หางล่างที่ต้องดันสระล่างลง

UPPER_VOWELS = set("ัิีึื็ํ")   # ั ิ ี ึ ื ็ ํ
TONES = set("่้๊๋์")                       # ่ ้ ๊ ๋ ์
LOWER_VOWELS = set("ฺุู")                            # ุ ู ฺ
SARA_AM = "ำ"

UPPER_LEFT = {"ิ": "", "ี": "", "ึ": "", "ื": "",
              "ั": "", "ํ": "", "็": ""}
TONE_LOW_LEFT = {"่": "", "้": "", "๊": "", "๋": "", "์": ""}
TONE_LOW = {"่": "", "้": "", "๊": "", "๋": "", "์": ""}
TONE_LEFT = {"่": "", "้": "", "๊": "", "๋": "", "์": ""}
LOWER_LOW = {"ุ": "", "ู": "", "ฺ": ""}

_REVERSE = {}
for _m in (UPPER_LEFT, TONE_LOW_LEFT, TONE_LOW, TONE_LEFT, LOWER_LOW):
    for _k, _v in _m.items():
        _REVERSE[_v] = _k
for _k, _v in DESC_REMOVABLE.items():
    _REVERSE[_v] = _k


def _is_base(c):
    return "ก" <= c <= "ฮ"  # ก-ฮ


def shape(text):
    """แปลงข้อความไทยให้สระ/วรรณยุกต์อยู่ถูกตำแหน่งในเกมที่ไม่จัดตัวอักษรเอง"""
    if not text or not any("฀" <= c <= "๿" for c in text):
        return text
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if not _is_base(c):
            out.append(c)
            i += 1
            continue
        # รวบตัวกำกับที่ตามหลังพยัญชนะตัวนี้
        j = i + 1
        while j < n and (text[j] in UPPER_VOWELS or text[j] in TONES or text[j] in LOWER_VOWELS):
            j += 1
        marks = text[i + 1:j]
        has_am = j < n and text[j] == SARA_AM
        has_upper = any(m in UPPER_VOWELS for m in marks)
        has_lower = any(m in LOWER_VOWELS for m in marks)
        base = c
        if has_lower and c in DESC_REMOVABLE:
            base = DESC_REMOVABLE[c]
        seg = [base]
        if c in ASCENDER:
            if has_am:
                seg.append(UPPER_LEFT["ํ"])  # ำ แยกเป็น ํ (ชิดซ้าย) + า
            for m in marks:
                if m in UPPER_VOWELS:
                    seg.append(UPPER_LEFT[m])
                elif m in TONES:
                    seg.append(TONE_LEFT[m] if (has_upper or has_am) else TONE_LOW_LEFT[m])
                else:
                    seg.append(m)
            if has_am:
                seg.append("า")
                j += 1
        else:
            for m in marks:
                if m in TONES and not has_upper and not has_am:
                    seg.append(TONE_LOW[m])
                elif m in LOWER_VOWELS and c in DESC_KEEP:
                    seg.append(LOWER_LOW[m])
                else:
                    seg.append(m)
        out.extend(seg)
        i = j
    return "".join(out)


def unshape(text):
    """แปลงกลับเป็นข้อความไทยปกติ (ใช้ตอนอ่านคำแปลที่เคยแปลงไว้)"""
    if not text or not any("" <= c <= "" for c in text):
        return text
    s = "".join(_REVERSE.get(c, c) for c in text)
    # ประกอบ ํ + า ที่แยกไว้ กลับเป็น ำ (วรรณยุกต์อยู่ก่อน ำ ตามลำดับการพิมพ์ไทย)
    out, i = [], 0
    while i < len(s):
        if s[i] == "ํ":
            k = i + 1
            tones = ""
            while k < len(s) and s[k] in TONES:
                tones += s[k]
                k += 1
            if k < len(s) and s[k] == "า":
                out.append(tones + SARA_AM)
                i = k + 1
                continue
        out.append(s[i])
        i += 1
    return "".join(out)
