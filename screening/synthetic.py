"""
Synthetic identity-document generator + controlled tampering operations.

Produces realistic-looking demo documents whose MRZ lines carry valid ICAO
checksums, modelled on the standard Indian layouts:

  * Passport          - Type/Country/Passport-No header, photo, two field
                        columns (incl. place of birth / place & date of
                        issue) and a TD3 MRZ (2 x 44)
  * Visa              - MRV layout with photo, visa fields and an
                        MRV-B MRZ (2 x 36)
  * National ID       - Aadhaar-style card (Government of India, photo,
                        name/DOB/gender, 12-digit number)
  * Driving licence   - Union of India card with category badges (AN)/(NT),
                        smart chip, father's name, blood group, validity

All imagery is AI/computer generated - no real person's document is used.
"""
from __future__ import annotations

import io
import math
import os
import random
from datetime import date

from PIL import Image, ImageDraw, ImageFont

from .mrz import build_mrv_b, build_td3

_TTF = "/usr/share/fonts/truetype/dejavu/"
MONO = _TTF + "DejaVuSansMono.ttf"
SANS = _TTF + "DejaVuSans.ttf"
SANS_B = _TTF + "DejaVuSans-Bold.ttf"
# Devanagari-capable font so labels can be bilingual like real Indian
# documents; machines without it fall back to English-only labels
DEV = os.path.join(os.path.dirname(__file__), "fonts",
                   "NotoSansDevanagari-Regular.ttf")
if not os.path.exists(DEV):
    DEV = None

DEFAULT_FACES = {
    "A": os.path.join(os.path.dirname(__file__), "..", "..",
                      "demo_assets", "subject_a_passport_photo.jpg"),
    "B": os.path.join(os.path.dirname(__file__), "..", "..",
                      "demo_assets", "subject_b_passport_photo.jpg"),
}

IDENTITY_A = dict(surname="SHARMA", given_names="PRIYA", doc_number="Z1234567",
                  nationality="IND", dob=date(1995, 3, 12), expiry=date(2031, 11, 20),
                  sex="F", place_of_birth="DELHI, DELHI", place_of_issue="DELHI",
                  date_of_issue=date(2021, 11, 21), aadhaar="8234 5671 9012")
IDENTITY_B = dict(surname="KUMAR", given_names="RAJESH", doc_number="K7654321",
                  nationality="IND", dob=date(1978, 7, 1), expiry=date(2029, 5, 30),
                  sex="M", place_of_birth="MUMBAI, MAHARASHTRA",
                  place_of_issue="MUMBAI", date_of_issue=date(2019, 5, 31),
                  aadhaar="9345 6782 1234")
IDENTITY_WATCH = dict(surname="SINGH", given_names="VIKRAM", doc_number="S7777777",
                      nationality="IND", dob=date(1985, 1, 25), expiry=date(2030, 2, 14),
                      sex="M", place_of_birth="AMRITSAR, PUNJAB",
                      place_of_issue="AMRITSAR", date_of_issue=date(2020, 2, 15),
                      aadhaar="7456 1238 9023")
IDENTITY_BLACKLISTED = dict(surname="MEHTA", given_names="ANIL", doc_number="B4444444",
                            nationality="IND", dob=date(1990, 9, 9),
                            expiry=date(2028, 12, 1), sex="M",
                            place_of_birth="SURAT, GUJARAT", place_of_issue="SURAT",
                            date_of_issue=date(2018, 12, 2), aadhaar="6123 7894 5601")
IDENTITY_DL = dict(surname="ALI", given_names="ASHRAF", doc_number="AN01 20130003278",
                   nationality="IND", dob=date(1987, 12, 20), expiry=date(2033, 9, 22),
                   sex="M", father_name="MOHAMMED ALI", blood_group="A+",
                   date_of_issue=date(2013, 9, 23), categories="AN NT")


def _font(path, size):
    return ImageFont.truetype(path, size)


def _bi(hindi, english):
    """Bilingual label text, like on real Indian documents."""
    return f"{hindi} /{english}" if DEV else english


def _lfont(size):
    """Label font: Devanagari-capable when available (it also covers Latin)."""
    return _font(DEV, size) if DEV else _font(SANS, size)


def _paste_ghost(img, face_path, box, alpha=0.28):
    """Translucent second portrait, like the ghost photo on real pages."""
    x, y, w, h = box
    face = Image.open(face_path).convert("RGB").resize((w, h))
    region = img.crop((x, y, x + w, y + h))
    img.paste(Image.blend(region, face, alpha), (x, y))


def _header(d, x, y, hindi, english, size, fill):
    """Bilingual heading; each script drawn with a font that covers it."""
    if DEV:
        d.text((x, y), hindi, font=_font(DEV, size), fill=fill)
        w = _font(DEV, size).getlength(hindi)
        d.text((x + w + 14, y), english, font=_font(SANS_B, size), fill=fill)
    else:
        d.text((x, y), english, font=_font(SANS_B, size), fill=fill)


def _signature(d, x, y, w=180, h=36, seed=5):
    rnd = random.Random(seed)
    pts, px = [], x
    while px < x + w:
        pts.append((px, y + rnd.uniform(0, h)))
        px += rnd.uniform(8, 18)
    d.line(pts, fill=(30, 30, 90), width=2)


def _bg(width, height, tone=(232, 227, 213), seed=7):
    img = Image.new("RGB", (width, height), tone)
    d = ImageDraw.Draw(img)
    rnd = random.Random(seed)
    colors = [(180, 200, 220), (190, 215, 195), (220, 200, 180)]
    for i in range(26):
        col = colors[i % 3]
        amp = rnd.uniform(6, 22)
        period = rnd.uniform(180, 420)
        y0 = rnd.uniform(0, height)
        pts = [(x, y0 + amp * math.sin(x / period * 2 * math.pi + i))
               for x in range(0, width, 8)]
        d.line(pts, fill=col, width=1)
    return img, d


def _paste_face(img, face_path, box):
    x, y, w, h = box
    face = Image.open(face_path).convert("RGB")
    fw, fh = face.size
    target_ratio = w / h
    cur_ratio = fw / fh
    if cur_ratio > target_ratio:
        new_w = int(fh * target_ratio)
        left = (fw - new_w) // 2
        face = face.crop((left, 0, left + new_w, fh))
    else:
        new_h = int(fw / target_ratio)
        top = max(0, int(fh * 0.08))
        face = face.crop((0, top, fw, min(fh, top + new_h)))
    face = face.resize((w, h))
    img.paste(face, (x, y))
    d = ImageDraw.Draw(img)
    d.rectangle([x - 3, y - 3, x + w + 3, y + h + 3], outline=(60, 60, 60), width=3)
    return d


def _field(d, x, y, label, value, label_size=19, value_size=29):
    # bilingual labels: Hindi on its own line above the English one so an
    # eng-only Tesseract still sees clean ASCII label lines
    hindi, _, english = label.partition(" /")
    if not english:
        english = label
    if DEV and hindi != label:
        # kept well above the English line so OCR segments them apart
        d.text((x, y), hindi, font=_font(DEV, 15), fill=(150, 150, 155))
    d.text((x, y + 24), english, font=_font(SANS, label_size), fill=(90, 90, 95))
    d.text((x, y + 50), value, font=_font(SANS_B, value_size), fill=(20, 20, 25))
    return y + 82


def _fmt(dt, sep="-"):
    return dt.strftime(f"%d{sep}%m{sep}%Y")


def make_passport(identity, face_path, out_path, quality=92):
    W, H = 1250, 880
    img, d = _bg(W, H)
    _header(d, W // 2 - 260, 38, "भारत गणराज्य", "REPUBLIC OF INDIA", 40,
            (120, 90, 30))
    _paste_face(img, face_path, (70, 160, 300, 380))
    _paste_ghost(img, face_path, (950, 170, 220, 280))
    d = ImageDraw.Draw(img)

    for hx, lab, val in ((420, _bi("प्रकार", "Type"), "P"),
                         (560, _bi("देश कोड", "Code"), identity["nationality"]),
                         (800, _bi("पासपोर्ट संख्या", "Passport No."),
                          identity["doc_number"])):
        hindi, _, english = lab.partition(" /")
        if DEV:
            d.text((hx, 150), hindi, font=_font(DEV, 15), fill=(120, 120, 125))
        d.text((hx, 170), english, font=_font(SANS, 19), fill=(90, 90, 95))
        d.text((hx, 194), val, font=_font(SANS_B, 29), fill=(20, 20, 25))

    _field(d, 420, 250, _bi("उपनाम", "Surname"), identity["surname"])
    _field(d, 420, 332, _bi("दिए गए नाम", "Given Names"), identity["given_names"])
    _field(d, 420, 414, _bi("राष्ट्रीयता", "Nationality"), identity["nationality"])
    _field(d, 420, 496, _bi("जन्म स्थान", "Place of Birth"),
           identity.get("place_of_birth", "DELHI, DELHI"))
    _field(d, 800, 250, _bi("जन्म तिथि", "Date of Birth"), _fmt(identity["dob"]))
    if DEV:
        d.text((1080, 250), "लिंग", font=_font(DEV, 15), fill=(150, 150, 155))
    d.text((1080, 274), "Sex", font=_font(SANS, 19), fill=(90, 90, 95))
    d.text((1080, 300), identity["sex"], font=_font(SANS_B, 29), fill=(20, 20, 25))
    _field(d, 800, 332, _bi("जारी करने का स्थान", "Place of Issue"),
           identity.get("place_of_issue", "DELHI"))
    _field(d, 800, 414, _bi("जारी करने की तिथि", "Date of Issue"),
           _fmt(identity.get("date_of_issue", date(2021, 11, 21))))
    _field(d, 800, 496, _bi("समाप्ति की तिथि", "Date of Expiry"),
           _fmt(identity["expiry"]))
    _signature(d, 420, 600)

    d.rectangle([40, 650, W - 40, H - 20], fill=(250, 250, 248))
    d.text((60, 655), "Machine Readable Zone - TD3", font=_font(SANS, 14),
           fill=(140, 140, 140))
    l1, l2 = build_td3("P", identity["nationality"], identity["surname"],
                       identity["given_names"], identity["doc_number"],
                       identity["nationality"], identity["dob"], identity["expiry"],
                       identity["sex"])
    d.text((60, 680), l1, font=_font(MONO, 34), fill=(10, 10, 10))
    d.text((60, 750), l2, font=_font(MONO, 34), fill=(10, 10, 10))

    img.save(out_path, "JPEG", quality=quality)
    return out_path


def make_visa(identity, face_path, out_path, visa_no="V88012345",
              visa_type="BUSINESS", entries="MULTIPLE", stay="90 DAYS",
              valid_until=None, quality=92):
    # landscape sticker like the real Indian visa: header band, photo left,
    # ghost portrait right, field rows in two columns, MRV-B MRZ at the bottom
    W, H = 1150, 800
    img, d = _bg(W, H, tone=(225, 232, 225), seed=11)
    if DEV:
        d.text((60, 20), "वीज़ा", font=_font(DEV, 30), fill=(30, 50, 90))
    d.text((60, 56), "VISA", font=_font(SANS_B, 30), fill=(30, 50, 90))
    _header(d, W // 2 - 200, 14, "भारत गणराज्य", "REPUBLIC OF INDIA", 28,
            (30, 60, 30))
    d.text((W // 2 - 60, 96), "VISA", font=_font(SANS_B, 40),
           fill=(70, 130, 200))
    if DEV:
        d.text((W - 260, 76), "वीज़ा संख्या", font=_font(DEV, 14),
               fill=(150, 150, 155))
    d.text((W - 260, 100), "Visa Number", font=_font(SANS, 16), fill=(90, 90, 95))
    d.text((W - 260, 128), visa_no, font=_font(SANS_B, 26), fill=(20, 20, 25))
    _paste_face(img, face_path, (60, 120, 200, 250))
    _paste_ghost(img, face_path, (890, 130, 200, 240))
    d = ImageDraw.Draw(img)
    # faint ashoka-chakra emblem between the columns, pink motifs right
    cx, cy, r = 575, 330, 80
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(170, 185, 215), width=2)
    for k in range(24):
        a = k * math.pi / 12
        d.line([cx, cy, cx + r * math.cos(a), cy + r * math.sin(a)],
               fill=(185, 198, 225), width=1)
    for fx, fy, fr in ((930, 470, 46), (1040, 545, 38), (860, 565, 30)):
        d.regular_polygon((fx, fy, fr), 4, rotation=20, fill=(238, 178, 205))
        d.regular_polygon((fx, fy, fr), 4, rotation=65, fill=(240, 190, 213))
    _field(d, 320, 120, _bi("उपनाम और नाम", "Surname and Given Name"),
           f"{identity['surname']} {identity['given_names']}")
    _field(d, 320, 210, _bi("पासपोर्ट संख्या", "Passport No"),
           identity["doc_number"])
    _field(d, 640, 210, _bi("वीज़ा टाईप", "Visa Type"), visa_type)
    _field(d, 320, 292, _bi("प्रवेशों की संख्या", "No Of Entries"), entries)
    _field(d, 640, 292, _bi("ठहरने की अवधि", "Duration of Stay"), stay)
    _field(d, 320, 374, _bi("जारी करने की तिथि", "Date of Issue"),
           _fmt(identity.get("date_of_issue", date(2024, 1, 15))))
    _field(d, 640, 374, _bi("समाप्ति की तिथि", "Date of Expiry(DD/MM/YYYY)"),
           _fmt(valid_until or identity["expiry"], "/"))
    if DEV:
        d.text((320, 462), "विशेष पृष्ठांकन", font=_font(DEV, 15),
               fill=(150, 150, 155))
    d.text((320, 486), "Special Endorsement", font=_font(SANS, 17),
           fill=(90, 90, 95))
    d.text((320, 510), f"NON-EXTENDABLE {visa_type} VISA",
           font=_font(SANS, 17), fill=(40, 40, 45))
    d.text((60, 552), "NOT VALID FOR PROHIBITED, RESTRICTED AND "
                      "CANTONMENT AREAS", font=_font(SANS, 17), fill=(40, 40, 45))
    if DEV:
        d.text((60, 578), "प्रयोजन बदलने की अनुमति नहीं है",
               font=_font(DEV, 15), fill=(40, 40, 45))
    d.text((60, 600), "Change of Purpose Not Allowed.",
           font=_font(SANS, 16), fill=(40, 40, 45))

    d.rectangle([40, 660, W - 40, H - 20], fill=(250, 250, 248))
    d.text((60, 664), "Machine Readable Zone - MRV-B", font=_font(SANS, 14),
           fill=(140, 140, 140))
    l1, l2 = build_mrv_b(visa_no, "IND", identity["surname"], identity["given_names"],
                         identity["nationality"], identity["dob"],
                         valid_until or identity["expiry"], identity["sex"])
    d.text((60, 690), l1, font=_font(MONO, 30), fill=(10, 10, 10))
    d.text((60, 745), l2, font=_font(MONO, 30), fill=(10, 10, 10))
    img.save(out_path, "JPEG", quality=quality)
    return out_path


def make_id_card(identity, face_path, out_path, quality=92):
    """Aadhaar-style national identity card."""
    W, H = 1000, 630
    img, d = _bg(W, H, tone=(240, 236, 222), seed=21)
    d.ellipse([W // 2 - 26, 18, W // 2 + 26, 70], outline=(170, 130, 40), width=3)
    d.text((W // 2 - 140, 78), "Government of India", font=_font(SANS_B, 32),
           fill=(120, 80, 20))
    _paste_face(img, face_path, (60, 130, 210, 260))
    d = ImageDraw.Draw(img)
    y = _field(d, 320, 140, "Name", f"{identity['surname']} {identity['given_names']}")
    y = _field(d, 320, y, "Date of Birth", _fmt(identity["dob"]))
    y = _field(d, 320, y, "Gender", "Male" if identity["sex"] == "M" else "Female")
    d.text((320, 470), "Aadhaar Number", font=_font(SANS, 19), fill=(90, 90, 95))
    d.text((320, 496), identity.get("aadhaar", "8234 5671 9012"),
           font=_font(MONO, 40), fill=(20, 20, 25))
    img.save(out_path, "JPEG", quality=quality)
    return out_path


def make_driving_license(identity, face_path, out_path, quality=92):
    """Indian driving licence card: categories, smart chip, blood group."""
    W, H = 1000, 680
    img, d = _bg(W, H, tone=(238, 230, 220), seed=31)
    d.text((40, 24), "UNION OF INDIA", font=_font(SANS_B, 24), fill=(90, 40, 20))
    d.text((250, 18), "Driving Licence", font=_font(SANS_B, 34), fill=(60, 60, 60))
    cats = identity.get("categories", "AN NT")
    d.text((W - 220, 26), " ".join(f"({c})" for c in cats.split()),
           font=_font(SANS_B, 30), fill=(140, 30, 30))
    d.text((40, 88), "Licence Number", font=_font(SANS, 18), fill=(90, 90, 95))
    d.text((40, 116), identity["doc_number"], font=_font(SANS_B, 30),
           fill=(20, 20, 25))
    _paste_face(img, face_path, (800, 110, 160, 220))
    # smart chip
    d.rounded_rectangle([60, 200, 150, 270], radius=10, fill=(212, 175, 55),
                        outline=(150, 120, 30), width=2)
    for i in (1, 2):
        d.line([60, 200 + i * 23, 150, 200 + i * 23], fill=(150, 120, 30), width=2)
        d.line([60 + i * 30, 200, 60 + i * 30, 270], fill=(150, 120, 30), width=2)
    d = ImageDraw.Draw(img)
    _field(d, 300, 150, _bi("जारी करने की तिथि", "Date of Issue"),
           _fmt(identity.get("date_of_issue", date(2013, 9, 23)), "/"))
    _field(d, 600, 150, _bi("वैधता", "Validity"), _fmt(identity["expiry"], "/"))
    _field(d, 300, 250, _bi("जन्म तिथि", "Date of Birth"), _fmt(identity["dob"], "/"))
    _field(d, 600, 250, "Blood Group", identity.get("blood_group", "A+"),
           value_size=34)
    _field(d, 60, 350, _bi("नाम", "Name"),
           f"{identity['given_names']} {identity['surname']}")
    _field(d, 60, 445, _bi("पुत्र/पुत्री/पत्नी का नाम", "Son/Daughter/Wife of"),
           identity.get("father_name", "MOHAMMED ALI"))
    img.save(out_path, "JPEG", quality=quality)
    return out_path


# --------------------------------------------------------------------------
# Tampering operations
# --------------------------------------------------------------------------
def resave_region(pil_img, box, quality=70):
    """box = (x, y, w, h). Locally re-compresses the region at a different
    JPEG quality, creating the compression discontinuity real forgeries show."""
    x, y, w, h = box
    region = pil_img.crop((x, y, x + w, y + h))
    buf = io.BytesIO()
    region.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    recompressed = Image.open(buf).convert("RGB")
    pil_img.paste(recompressed, (x, y))
    return pil_img


def alter_value(pil_img, box, new_text, value_size=29, quality=70):
    x, y, w, h = box
    sample = pil_img.crop((max(0, x - 12), y, max(1, x - 4), y + h)).resize((1, 1))
    bg = sample.getpixel((0, 0))
    d = ImageDraw.Draw(pil_img)
    d.rectangle([x, y, x + w, y + h], fill=bg)
    d.text((x, y + 2), new_text, font=_font(SANS_B, value_size), fill=(20, 20, 25))
    return resave_region(pil_img, (x, y, w, h), quality)


def swap_photo(pil_img, other_face_path, photo_box, quality=60):
    """Simulates a crude photo substitution: the replacement portrait comes
    from a separately JPEG-compressed source at a different quality."""
    _paste_face(pil_img, other_face_path, photo_box)
    return resave_region(pil_img, photo_box, quality)


def generate_demo_docs(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    fa, fb = DEFAULT_FACES["A"], DEFAULT_FACES["B"]
    paths = {}

    paths["clean_passport"] = make_passport(IDENTITY_A, fa,
                                            os.path.join(out_dir, "passport_clean.jpg"))
    # 1) DOB text alteration (also breaks visual-vs-MRZ consistency)
    #    DOB value sits in the right column: label y=250, value y=300.
    img = Image.open(paths["clean_passport"])
    img = alter_value(img, (798, 298, 250, 40), "01-01-1990")
    paths["tampered_dob"] = os.path.join(out_dir, "passport_tampered_dob.jpg")
    img.save(paths["tampered_dob"], "JPEG", quality=92)
    # 2) photo substitution
    img = Image.open(paths["clean_passport"])
    img = swap_photo(img, fb, (70, 160, 300, 380))
    paths["tampered_photo"] = os.path.join(out_dir, "passport_swapped_photo.jpg")
    img.save(paths["tampered_photo"], "JPEG", quality=92)
    # 3) watchlisted traveller
    paths["watchlist_passport"] = make_passport(
        IDENTITY_WATCH, fb, os.path.join(out_dir, "passport_watchlist.jpg"))
    # 4) blacklisted document number
    paths["blacklisted_passport"] = make_passport(
        IDENTITY_BLACKLISTED, fb, os.path.join(out_dir, "passport_blacklisted.jpg"))
    # 5) metadata forgery: file carries an editing-software fingerprint
    meta = os.path.join(out_dir, "passport_edited_metadata.jpg")
    with open(paths["clean_passport"], "rb") as fh:
        blob = fh.read()
    with open(meta, "wb") as fh:
        fh.write(blob + b"\x00Edited with Adobe Photoshop 25.1\x00")
    paths["metadata_forgery"] = meta
    # other document types
    paths["visa"] = make_visa(IDENTITY_A, fa, os.path.join(out_dir, "visa_clean.jpg"))
    paths["id_card"] = make_id_card(IDENTITY_A, fa, os.path.join(out_dir, "id_clean.jpg"))
    paths["license"] = make_driving_license(IDENTITY_DL, fb,
                                            os.path.join(out_dir, "license_clean.jpg"))
    return paths
