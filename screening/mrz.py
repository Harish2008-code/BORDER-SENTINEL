"""
ICAO 9303 Machine Readable Zone (MRZ) parsing.

Supports TD3 (passports, 2x44), TD2 (2x36) and TD1 (ID cards, 3x30).
Includes OCR post-correction: when a checksum fails, confusable character
substitutions (O/0, I/1, S/5 ...) are attempted so a misread glyph can be
repaired *and flagged*, which is exactly what a real checkpoint engine does.
"""
from __future__ import annotations

import re
from datetime import date

WEIGHTS = (7, 3, 1)

# Characters that OCR engines routinely confuse, grouped into substitution sets.
CONFUSABLE_GROUPS = [
    "0OQ", "1I", "2Z", "5S", "6G", "8B", "7T", "4A", "9g",
]
_CONFUSABLE = {}
for _g in CONFUSABLE_GROUPS:
    _g = _g.upper()
    for _c in _g:
        _CONFUSABLE[_c] = _g


def char_value(ch: str) -> int:
    if "0" <= ch <= "9":
        return ord(ch) - 48
    if "A" <= ch <= "Z":
        return ord(ch) - 55
    return 0  # filler '<'


def compute_checksum(text: str) -> int:
    total = 0
    for i, ch in enumerate(text):
        total += char_value(ch) * WEIGHTS[i % 3]
    return total % 10


def _try_correct(data: str, check: str):
    """Return (corrected_data, corrected_check, fixes) making the checksum pass."""
    if compute_checksum(data) == char_value(check):
        return data, check, []
    fixes = []
    # 1) wrong check char only (O/0, I/1 ...)
    if check in _CONFUSABLE:
        for cand in _CONFUSABLE[check]:
            if compute_checksum(data) == char_value(cand):
                return data, cand, [(len(data), check, cand)]
    # 2) single misread inside the data
    for i, ch in enumerate(data):
        if ch not in _CONFUSABLE:
            continue
        for cand in _CONFUSABLE[ch]:
            if cand == ch:
                continue
            alt = data[:i] + cand + data[i + 1:]
            if compute_checksum(alt) == char_value(check):
                fixes.append((i, ch, cand))
                return alt, check, fixes
    return data, check, []


def resolve_yymmdd(yymmdd: str, kind: str) -> dict:
    """YYMMDD -> calendar date using ICAO sliding-window century rules."""
    out = {"raw": yymmdd, "date": None, "valid": False}
    if len(yymmdd) != 6 or not yymmdd.isdigit():
        return out
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    now_yy = date.today().year % 100
    if kind == "dob":
        year = 2000 + yy if yy <= now_yy + 1 else 1900 + yy
    else:  # expiry must be today or later when the document was issued valid
        year = 2000 + yy if yy >= now_yy - 10 else 2100 + yy
    try:
        out["date"] = date(year, mm, dd)
        out["valid"] = True
    except ValueError:
        pass
    return out


def _pad(line: str, width: int) -> str:
    line = line.upper().replace(" ", "<")
    line = "".join(c if c.isalnum() or c == "<" else "<" for c in line)
    return (line + "<" * width)[:width]


def extract_mrz_lines(text: str, min_width: int = 26):
    """Pick MRZ-looking lines out of raw OCR text."""
    lines = []
    for raw in text.splitlines():
        cleaned = raw.strip().upper().replace(" ", "<")
        cleaned = "".join(c for c in cleaned if c.isalnum() or c == "<")
        # genuine MRZ lines always contain a filler run of '<<<' (name
        # padding / trailing fillers); spaced label text that OCR mangles
        # into angle brackets only ever shows isolated '<' or single '<<'
        if len(cleaned) >= min_width and re.search(r"<{3,}", cleaned):
            alpha = sum(c.isalnum() for c in cleaned)
            if alpha / max(1, len(cleaned)) > 0.35:
                lines.append(cleaned)
    return lines


def parse_td3(l1: str, l2: str) -> dict:
    l1, l2 = _pad(l1, 44), _pad(l2, 44)
    fixes = []

    doc_no, doc_check = l2[0:9], l2[9]
    doc_no, doc_check, f = _try_correct(doc_no.rstrip("<"), doc_check)
    fixes += [("doc_number", *x) for x in f]

    dob, dob_check = l2[13:19], l2[19]
    dob, dob_check, f = _try_correct(dob, dob_check)
    fixes += [("dob", *x) for x in f]

    expiry, expiry_check = l2[21:27], l2[27]
    expiry, expiry_check, f = _try_correct(expiry, expiry_check)
    fixes += [("expiry", *x) for x in f]

    personal = l2[28:42]
    personal_check = l2[42]
    composite_src = l2[0:10] + l2[13:20] + l2[21:43]
    composite_ok = compute_checksum(composite_src) == char_value(l2[43])
    if not composite_ok and l2[43] in _CONFUSABLE:
        # the composite check glyph itself may be an OCR misread (O/0, Q/0 ...)
        for cand in _CONFUSABLE[l2[43]]:
            if compute_checksum(composite_src) == char_value(cand):
                composite_ok = True
                fixes.append(("composite", 43, l2[43], cand))
                break

    return {
        "format": "TD3",
        "lines": [l1, l2],
        "doc_type": l1[0:2].rstrip("<"),
        "issuing_state": l1[2:5].rstrip("<"),
        "surname": l1[5:44].split("<<")[0].replace("<", " ").strip(),
        "given_names": "<<".join(l1[5:44].split("<<")[1:])[0:38].replace("<", " ").strip(),
        "doc_number": doc_no.rstrip("<"),
        "nationality": l2[10:13].rstrip("<"),
        "dob": resolve_yymmdd(dob, "dob"),
        "expiry": resolve_yymmdd(expiry, "expiry"),
        "sex": l2[20] if l2[20] in "MFX<" else "",
        "personal_number": personal.rstrip("<"),
        "checks": {
            "doc_number": compute_checksum(doc_no) == char_value(doc_check),
            "dob": compute_checksum(dob) == char_value(dob_check),
            "expiry": compute_checksum(expiry) == char_value(expiry_check),
            "composite": composite_ok,
        },
        "ocr_fixes": fixes,
    }


def parse_td1(l1: str, l2: str, l3: str) -> dict:
    l1, l2, l3 = _pad(l1, 30), _pad(l2, 30), _pad(l3, 30)
    doc_no_raw, doc_check = l1[5:14], l1[14]
    doc_no, doc_check, fixes = _try_correct(doc_no_raw.rstrip("<"), doc_check)
    dob, dob_check = l2[0:6], l2[6]
    dob, dob_check, f2 = _try_correct(dob, dob_check)
    expiry, expiry_check = l2[8:14], l2[14]
    expiry, expiry_check, f3 = _try_correct(expiry, expiry_check)
    return {
        "format": "TD1",
        "lines": [l1, l2, l3],
        "doc_type": l1[0:2].rstrip("<"),
        "issuing_state": l1[2:5].rstrip("<"),
        "doc_number": doc_no.rstrip("<"),
        "nationality": l2[15:18].rstrip("<"),
        "dob": resolve_yymmdd(dob, "dob"),
        "expiry": resolve_yymmdd(expiry, "expiry"),
        "sex": l2[7] if l2[7] in "MFX<" else "",
        "surname": l3[0:30].split("<<")[0].replace("<", " ").strip(),
        "given_names": "<<".join(l3[0:30].split("<<")[1:]).replace("<", " ").strip(),
        "checks": {
            "doc_number": compute_checksum(doc_no) == char_value(doc_check),
            "dob": compute_checksum(dob) == char_value(dob_check),
            "expiry": compute_checksum(expiry) == char_value(expiry_check),
            "composite": True,
        },
        "ocr_fixes": fixes + f2 + f3,
    }


def parse_mrz(lines):
    """Auto-detect format and parse. Returns dict or None."""
    if len(lines) >= 3 and max(len(l) for l in lines[:3]) <= 38:
        return parse_td1(*lines[:3])
    if len(lines) >= 2:
        if lines[0].startswith("V"):
            return parse_mrv_b(lines[0], lines[1])
        # OCR drops trailing fillers; pad to TD3 width before slicing
        return parse_td3(lines[0], lines[1])
    return None


# ---------------------------------------------------------------------------
# MRV (Machine Readable Visa) - ICAO 9303 Part 7, Type B: 2 x 36
# ---------------------------------------------------------------------------
def build_mrv_b(visa_number, issuing_state, surname, given_names, nationality,
                dob: date, expiry: date, sex, subtype="B"):
    vn = (visa_number + "<" * 9)[:9]
    line1 = f"V{subtype}{issuing_state:<<3}{surname.replace(' ', '<')}<<{given_names.replace(' ', '<')}"
    line1 = (line1 + "<" * 36)[:36]
    line2 = (
        vn + str(compute_checksum(vn))
        + f"{nationality:<<3}"
        + dob.strftime("%y%m%d") + str(compute_checksum(dob.strftime("%y%m%d")))
        + sex
        + expiry.strftime("%y%m%d") + str(compute_checksum(expiry.strftime("%y%m%d")))
        + "<<<"
    )
    line2 = (line2 + "<" * 36)[:36]
    return line1, line2


def _realign(l2: str, width: int, slices) -> str:
    """Undo a single-character OCR insertion in a fixed-width data line.

    Tesseract occasionally duplicates/inserts a digit (e.g. '452' -> '4521'),
    which shifts every fixed-position field after it.  Try deleting one
    character at each position and keep the best candidate:

    1. candidates that leave the leading visa-number + check char untouched
       (positions 0..9) are preferred -- the leading run is the most
       reliably recognised part of the line;
    2. among those, rank by checksums satisfied, then by structural
       plausibility (letters where letters belong, digits where digits
       belong, valid sex character).
    """
    if len(l2) <= width:
        return _pad(l2, width)

    def _structural(c: str) -> int:
        return (c[10:13].isalpha() + c[13:19].isdigit()
                + c[21:27].isdigit() + (c[20] in "MFX<"))

    candidates = []
    for i in range(len(l2)):
        cand = _pad((l2[:i] + l2[i + 1:])[:width], width)
        checks = sum(1 for (a, b, c) in slices
                     if compute_checksum(cand[a:b]) == char_value(cand[c]))
        candidates.append((cand, checks, _structural(cand)))
    anchored = [c for c in candidates if c[0][:10] == l2[:10]]
    pool = anchored or candidates
    pool.sort(key=lambda c: (c[1], c[2]))
    return pool[-1][0]


def parse_mrv_b(l1: str, l2: str) -> dict:
    l1 = _pad(l1, 36)
    l2 = _realign(l2, 36, [(0, 9, 9), (13, 19, 19), (21, 27, 27)])
    fixes = []
    vn, vn_check = l2[0:9], l2[9]
    vn, vn_check, f = _try_correct(vn.rstrip("<"), vn_check)
    fixes += [("visa_number", *x) for x in f]
    dob, dob_check = l2[13:19], l2[19]
    dob, dob_check, f = _try_correct(dob, dob_check)
    fixes += [("dob", *x) for x in f]
    expiry, expiry_check = l2[21:27], l2[27]
    expiry, expiry_check, f = _try_correct(expiry, expiry_check)
    fixes += [("expiry", *x) for x in f]
    return {
        "format": "MRV-B",
        "lines": [l1, l2],
        "doc_type": "V",
        "visa_subtype": l1[1],
        "issuing_state": l1[2:5].rstrip("<"),
        "surname": l1[5:36].split("<<")[0].replace("<", " ").strip(),
        "given_names": "<<".join(l1[5:36].split("<<")[1:]).replace("<", " ").strip(),
        "doc_number": vn.rstrip("<"),          # visa number
        "nationality": l2[10:13].rstrip("<"),
        "dob": resolve_yymmdd(dob, "dob"),
        "expiry": resolve_yymmdd(expiry, "expiry"),
        "sex": l2[20] if l2[20] in "MFX<" else "",
        "checks": {
            "visa_number": compute_checksum(vn) == char_value(vn_check),
            "dob": compute_checksum(dob) == char_value(dob_check),
            "expiry": compute_checksum(expiry) == char_value(expiry_check),
            "composite": True,
        },
        "ocr_fixes": fixes,
    }


def build_td3(doc_type, issuing_state, surname, given_names, doc_number,
              nationality, dob: date, expiry: date, sex, personal=""):
    """Construct two valid 44-char TD3 lines (used by the demo generator)."""
    dn = (doc_number + "<" * 9)[:9]
    line1 = f"{doc_type:<<2}{issuing_state:<<3}{surname.replace(' ', '<')}<<{given_names.replace(' ', '<')}"
    line1 = (line1 + "<" * 44)[:44]
    # composite check covers positions 1-10, 14-20 and 22-43 of line 2
    personal_field = (personal + "<" * 14)[:14]
    pcheck = str(compute_checksum(personal_field)) if personal_field.strip("<") else "<"
    line2 = (
        dn + str(compute_checksum(dn))
        + f"{nationality:<3}"
        + dob.strftime("%y%m%d") + str(compute_checksum(dob.strftime("%y%m%d")))
        + sex
        + expiry.strftime("%y%m%d") + str(compute_checksum(expiry.strftime("%y%m%d")))
        + personal_field + pcheck
    )
    composite_src = line2[0:10] + line2[13:20] + line2[21:43]
    line2 += str(compute_checksum(composite_src))
    return line1, line2
