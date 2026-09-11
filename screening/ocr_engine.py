"""
Module 1 - OCR Extraction.

Tesseract-backed extraction of the visual zone (labels + values) and the
machine readable zone of passports, visas, ID cards, driving licences and
permit documents.  Best-effort on arbitrary layouts; tuned for the synthetic
demo corpus shipped with the project.
"""
from __future__ import annotations

import os
import re
import shutil
import sys

import cv2
import numpy as np

try:
    import pytesseract
    HAS_TESSERACT = True
except Exception:  # pragma: no cover
    pytesseract = None
    HAS_TESSERACT = False


def _configure_tesseract():
    """Point pytesseract at a Tesseract binary even when it is not on PATH.

    The Windows installer (C:\\Program Files\\Tesseract-OCR) does not modify
    PATH by default; honour TESSERACT_CMD first, then probe the standard
    install locations.  Returns the path chosen, or None."""
    if pytesseract is None:
        return None
    if shutil.which("tesseract"):
        return None
    candidates = [os.environ.get("TESSERACT_CMD", "")]
    if sys.platform.startswith("win"):
        candidates += [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
    for cand in candidates:
        if cand and os.path.exists(cand):
            pytesseract.pytesseract.tesseract_cmd = cand
            return cand
    return None


TESSERACT_PATH = _configure_tesseract()

MRZ_WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"

LABELS = {
    "surname": [r"SUR?NAME", r"LAST\s*NAME", r"NOM"],
    "given_names": [r"GIVEN\s*NAMES?", r"FIRST\s*NAME", r"PRENOM"],
    "full_name": [r"NAME\s*OF\s*HOLDER", r"^NAME\b", r"\bNAME\b$"],
    "doc_number": [r"PASSPORT\s*NO", r"DOCUMENT\s*NO", r"ID\s*NO", r"LICEN[SC]E\s*N", r"DL\s*NO", r"NUMBER"],
    "nationality": [r"NATIONALITY", r"CITIZENSHIP"],
    "dob": [r"DATE\s*OF\s*BIRTH", r"BIRTH\s*DATE", r"DOB"],
    "expiry": [r"DATE\s*OF\s*EXPIRY", r"EXPIRY\s*DATE", r"VALIDITY\s*DATE", r"\bVALIDITY\b", r"VALID\s*UNTIL", r"DATE\s*OF\s*EXP"],
    "sex": [r"\bSEX\b", r"\bGENDER\b"],
    "place_of_birth": [r"PLACE\s*OF\s*BIRTH"],
    "place_of_issue": [r"PLACE\s*OF\s*ISSUE"],
    "date_of_issue": [r"DATE\s*OF\s*ISSUE"],
    "aadhaar_number": [r"AADHAAR\s*(?:NO|NUMBER)", r"AADHAR\s*(?:NO|NUMBER)"],
    "father_name": [r"FATHER", r"RELATIVE", r"SON\s*/\s*DAUGHTER"],
    "blood_group": [r"BLOOD\s*GROUP"],
    "visa_number": [r"VISA[\s-]*NO", r"VISA[\s-]*NUM"],
    "visa_type": [r"VISA\s*TYPE", r"CATEGORY"],
    "entries": [r"NO\s*OF\s*ENTRIES", r"ENTRY\s*VALIDATION", r"ENTRIES"],
    "stay_duration": [r"STAY\s*DURATION", r"DURATION\s*OF\s*STAY", r"STAY"],
}


def _upscale(img, min_width=1000):
    h, w = img.shape[:2]
    if w < min_width:
        factor = min_width / w
        img = cv2.resize(img, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    return img


def _boxes_from_data(data):
    out = []
    n = len(data["text"])
    for i in range(n):
        txt = (data["text"][i] or "").strip()
        conf = float(data["conf"][i])
        if not txt or conf < 0:
            continue
        out.append({
            "text": txt, "conf": conf,
            "x": int(data["left"][i]), "y": int(data["top"][i]),
            "w": int(data["width"][i]), "h": int(data["height"][i]),
        })
    return out


def _looks_like_label(text):
    """True when the captured 'value' is actually another field's label."""
    up = text.upper().strip()
    if len(up) > 30:
        return False
    for pats in LABELS.values():
        for pat in pats:
            if re.search(pat, up):
                return True
    return False


def _group_lines(boxes):
    boxes = sorted(boxes, key=lambda b: (b["y"], b["x"]))
    lines = []
    for b in boxes:
        placed = False
        for line in lines:
            if abs(line["y"] - b["y"]) <= max(8, b["h"] * 0.5):
                line["words"].append(b)
                placed = True
                break
        if not placed:
            lines.append({"y": b["y"], "words": [b]})
    for line in lines:
        line["words"].sort(key=lambda w: w["x"])
        line["text"] = " ".join(w["text"] for w in line["words"])
    lines.sort(key=lambda l: l["y"])
    return lines


def read_text(img, psm=6, whitelist=None):
    """Raw OCR over a BGR image; returns (text, boxes, mean_conf)."""
    img = _upscale(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    config = f"--psm {psm}"
    if whitelist:
        config += f" -c tessedit_char_whitelist={whitelist}"
    data = pytesseract.image_to_data(gray, config=config,
                                    output_type=pytesseract.Output.DICT)
    boxes = _boxes_from_data(data)
    text = pytesseract.image_to_string(gray, config=config)
    confs = [b["conf"] for b in boxes]
    return text, boxes, (sum(confs) / len(confs) / 100.0 if confs else 0.0)


def read_mrz(img):
    """OCR of the MRZ strip (bottom of the document).

    Runs two Tesseract page-segmentation modes and keeps the candidate whose
    ICAO parse yields the most valid checksums."""
    from .mrz import extract_mrz_lines, parse_mrz
    h, w = img.shape[:2]
    strip = img[int(h * 0.72):, :]
    strip = cv2.resize(strip, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    best_lines, best_score = [], -1
    for psm in (6, 4):
        config = f"--psm {psm} -c tessedit_char_whitelist={MRZ_WHITELIST}"
        text = pytesseract.image_to_string(th, config=config)
        lines = extract_mrz_lines(text)
        if len(lines) < 2:
            continue
        parsed = parse_mrz(lines)
        score = sum(parsed["checks"].values()) if parsed else 0
        if score > best_score:
            best_score, best_lines = score, lines
    conf = 0.9 if best_score >= 3 else (0.6 if best_lines else 0.0)
    return best_lines, conf


_VALUE_CLEAN = {
    "dob": re.compile(r"(\d{1,2}[ ./\-]\d{1,2}[ ./\-]\d{2,4})"),
    "expiry": re.compile(r"(\d{1,2}[ ./\-]\d{1,2}[ ./\-]\d{2,4})"),
}


def extract_fields(img, doc_type="passport"):
    """Visual-zone extraction. Returns dict(values, confidences, regions, raw)."""
    text, boxes, mean_conf = read_text(img)
    lines = _group_lines(boxes)
    values, confidences, regions = {}, {}, {}

    for field, patterns in LABELS.items():
        for li, line in enumerate(lines):
            if field == "doc_number" and "VISA" in line["text"].upper() \
                    and "PASSPORT" not in line["text"].upper():
                continue  # never steal the visa number as the document number
            if field == "doc_number" and "AADHA" in line["text"].upper():
                continue  # aadhaar number belongs to its own field
            if field == "surname" and "GIVEN" in line["text"].upper():
                continue  # combined "Surname and Given Name" label -> full_name
            if field == "given_names" and "SURNAME" in line["text"].upper():
                continue
            m = None
            for pat in patterns:
                m = re.search(pat, line["text"], re.I)
                if m:
                    break
            if not m:
                continue
            # pixel-correct: value words sit to the right of the label's box
            pos, label_end_x, label_x = 0, 0, None
            for w in line["words"]:
                ws, we = pos, pos + len(w["text"])
                if ws < m.end() and we > m.start():
                    label_end_x = max(label_end_x, w["x"] + w["w"])
                    if label_x is None:
                        label_x = w["x"]
                pos = we + 1
            # low-confidence scraps and far-right noise (photo edges) are
            # not values: keep words inside the label's own column
            words_after = [w for w in line["words"]
                           if label_end_x <= w["x"] <= label_x + 260
                           and w["conf"] >= 50]
            rest = " ".join(w["text"] for w in words_after).strip(" :.-")
            needs_next = not rest or field in ("father_name",)
            if rest and _looks_like_label(rest):
                needs_next = True   # e.g. header row: "Nationality ... Passport No."
            if field in ("dob", "expiry") and rest and not _VALUE_CLEAN[field].search(rest):
                needs_next = True
            if field == "doc_number" and rest:
                up = rest.upper()
                up = up[:2] + up[2:].replace("O", "0")   # 0/O OCR confusion
                nm = re.search(r"\b([A-Z]{2}\d{2}\s?\d{11})\b", up) or \
                    re.search(r"\b([A-Z]{0,2}[0-9][A-Z0-9]{5,9})\b", up)
                if nm:
                    rest = nm.group(1)
                elif not re.search(r"\d", rest):
                    needs_next = True
            backup = None
            if needs_next:
                for nxt in lines[li + 1:li + 4]:
                    if not (0 < nxt["y"] - line["y"] <= 70):
                        continue
                    col = []
                    if label_x is not None:
                        first = next((w for w in nxt["words"]
                                      if label_x - 40 <= w["x"] <= label_x + 140), None)
                        if first:
                            col = [first]
                            prev_end = first["x"] + first["w"]
                            for w in nxt["words"]:
                                if w["x"] > prev_end and w["x"] - prev_end < 100:
                                    col.append(w)
                                    prev_end = w["x"] + w["w"]
                    if col:
                        rest = " ".join(w["text"] for w in col).strip(" :.-")
                        words_after = col
                    else:
                        rest, words_after = nxt["text"], nxt["words"]
                    avg_conf = (sum(w["conf"] for w in words_after) /
                                max(1, len(words_after)))
                    if rest and not _looks_like_label(rest):
                        if avg_conf >= 70:
                            break
                        # keep an OCR-mangled date as last resort
                        if backup is None and len(re.findall(r"\d", rest)) >= 6:
                            backup = (rest, words_after)
            if backup is not None and len(re.findall(r"\d", rest)) < 4:
                rest, words_after = backup
            if not rest:
                continue
            if field == "doc_number":
                up = rest.upper()
                up = up[:2] + up[2:].replace("O", "0")
                nm = re.search(r"\b([A-Z]{2}\d{2}\s?\d{11})\b", up) or \
                    re.search(r"\b([A-Z]{0,2}[0-9][A-Z0-9]{5,9})\b", up)
                if nm:
                    rest = nm.group(1)
            if field in _VALUE_CLEAN:
                dm = _VALUE_CLEAN[field].search(rest)
                if dm:
                    rest = dm.group(1)
            if field == "sex":
                sm = re.search(r"\b(MALE|FEMALE|F|M|X)\b", rest.upper())
                if not sm:
                    continue
                rest = {"MALE": "M", "FEMALE": "F"}.get(sm.group(1), sm.group(1))
            values[field] = re.sub(r"\s+", " ", rest).strip()
            confidences[field] = round(
                sum(w["conf"] for w in words_after) / max(1, len(words_after)) / 100.0, 3)
            if words_after:
                x0 = min(w["x"] for w in words_after)
                y0 = min(w["y"] for w in words_after)
                x1 = max(w["x"] + w["w"] for w in words_after)
                y1 = max(w["y"] + w["h"] for w in words_after)
                regions[field] = [x0, y0, x1 - x0, y1 - y0]
            break

    if "surname" in values and "given_names" in values:
        values["full_name"] = f"{values['surname']} {values['given_names']}"

    return {
        "values": values,
        "confidences": confidences,
        "regions": regions,
        "raw_text": text,
        "ocr_confidence": round(mean_conf, 3),
    }


def classify_document(img, raw_text=""):
    """Heuristic document-type classifier."""
    from .mrz import extract_mrz_lines
    if not raw_text:
        raw_text, _, _ = read_text(img)
    t = raw_text.upper()
    mrz_lines = extract_mrz_lines(raw_text)
    if mrz_lines:
        return "visa" if mrz_lines[0].startswith("V") else "passport"
    if "VISA" in t and ("ENTRY" in t or "STAY" in t or "DURATION" in t):
        return "visa"
    if "UNION OF INDIA" in t or "DRIVING" in t or "LICEN" in t:
        return "driving_license"
    if "AADHAAR" in t or "AADHAR" in t or "UIDAI" in t or "IDENTITY" in t \
            or "GOVERNMENT OF INDIA" in t or "BHARAT" in t:
        return "id_card"
    if "PERMIT" in t:
        return "permit"
    if "PASSPORT" in t or "REPUBLIC" in t:
        return "passport"
    # No MRZ and no strong keyword: a genuine passport ALWAYS carries an MRZ,
    # so a document without one is far more likely an ID card than a passport.
    # Defaulting to id_card avoids falsely applying passport MRZ rules (which
    # would flag every non-passport as HIGH risk for a "missing" MRZ).
    return "id_card"
