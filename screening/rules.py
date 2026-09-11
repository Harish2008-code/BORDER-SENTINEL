"""
Module 2 - Document Validation.

Rule engine that verifies extracted information against official document
standards: MRZ checksums, date logic, format rules, cross-field consistency,
watchlist / blacklist lookups and duplicate-identity detection.
"""
from __future__ import annotations

from datetime import date

from .utils import jaro_winkler, parse_date

ISO3 = (
    "AFG ALA ALB DZA ASM AND AGO AIA ATA ATG ARG ARM ABW AUS AUT AZE BHS BHR BGD "
    "BRB BLR BEL BLZ BEN BMU BTN BOL BES BIH BWA BVT BRA IOT BRN BGR BFA BDI CPV "
    "KHM CMR CAN CYM CAF TCD CHL CHN CXR CCK COL COM COG COD COK CRI CIV HRV CUB "
    "CUW CYP CZE DNK DJI DMA DOM ECU EGY SLV GNQ ERI EST SWZ ETH FLK FRO FJI FIN "
    "FRA GUF PYF ATF GAB GMB GEO DEU GHA GIB GRC GRL GRD GLP GUM GTM GGY GIN GNB "
    "GUY HTI HMD VAT HND HKG HUN ISL IND IDN IRN IRQ IRL IMN ISR ITA JAM JPN JEY "
    "JOR KAZ KEN KIR PRK KOR KWT KGZ LAO LVA LBN LSO LBR LBY LIE LTU LUX MAC MDG "
    "MWI MYS MDV MLI MLT MHL MTQ MRT MUS MYT MEX FSM MDA MCO MNG MNE MSR MAR MOZ "
    "MMR NAM NRU NPL NLD NCL NZL NIC NER NGA NIU NFK MKD MNP NOR OMN PAK PLW PSE "
    "PAN PNG PRY PER PHL PCN POL PRT PRI QAT ROU RUS RWA REU BLM SHN KNA LCA MAF "
    "SPM VCT WSM SMR STP SAU SEN SRB SYC SLE SGP SXM SVK SVN SLB SOM ZAF SGS SSD "
    "ESP LKA SDN SUR SJM SWE CHE SYR TWN TJK THA TLS TGO TKL TON TTO TUN TUR TKM "
    "TCA TUV UGA UKR ARE GBR USA UMI URY UZB VUT VEN VNM VGB VIR WLF ESH YEM ZMB "
    "ZWE"
).split()

DOC_NUMBER_PATTERNS = {
    "IND": r"^[A-Z][0-9]{7}$",
    "USA": r"^[0-9]{9}$",
    "GBR": r"^[0-9]{9}$",
    "DEFAULT": r"^[A-Z0-9]{6,9}$",
}

WATCHLIST_NAME_THRESHOLD = 0.90


def _check(cid, name, passed, severity, detail):
    return {"id": cid, "name": name, "passed": bool(passed),
            "severity": severity, "detail": detail}


def run_validation(values: dict, mrz: dict | None, doc_type: str,
                   watchlist=(), blacklist=(), known_doc_numbers=()):
    """
    values: dict from ocr_engine.extract_fields()['values']
    mrz: parsed MRZ dict or None
    watchlist: iterable of dicts {'full_name','doc_number','reason'}
    blacklist: iterable of doc numbers reported lost/expired
    known_doc_numbers: iterable of (doc_number, holder) from past records
    """
    checks = []
    today = date.today()

    # --- presence ---------------------------------------------------------
    has_mrz = mrz is not None
    checks.append(_check(
        "mrz_present", "Machine readable zone detected",
        has_mrz or doc_type != "passport",
        "critical" if doc_type == "passport" else "info",
        "MRZ parsed" if has_mrz else "No MRZ found on document"))

    if has_mrz:
        ok = all(mrz["checks"].values())
        bad = [k for k, v in mrz["checks"].items() if not v]
        checks.append(_check(
            "mrz_checksums", "ICAO 9303 checksums (doc no / DOB / expiry / composite)",
            ok, "critical",
            "All checksums valid" if ok else f"Failed: {', '.join(bad)}"))
        if mrz.get("ocr_fixes"):
            checks.append(_check(
                "mrz_ocr_fixes", "OCR misreads repaired via checksum logic",
                True, "warning",
                f"{len(mrz['ocr_fixes'])} glyph correction(s) applied: "
                + "; ".join(f"{f[0]}[{f[1]}:{f[2]}->{f[3]}]" for f in mrz["ocr_fixes"])))

    # --- format rules ------------------------------------------------------
    doc_no = (mrz or {}).get("doc_number") or values.get("doc_number", "")
    nationality = (mrz or {}).get("nationality") or values.get("nationality", "")
    import re
    if doc_no and doc_type == "visa":
        # an MRV-B MRZ carries the visa number; passport-number rules do
        # not apply (the sticker's "Passport No" field is checked via
        # docno_consistency against the holder's passport instead)
        pat = r"^[A-Z0-9]{6,12}$"
        checks.append(_check(
            "doc_number_format", "Visa number format",
            bool(re.match(pat, doc_no)), "critical",
            f"{doc_no} matches {pat}" if re.match(pat, doc_no)
            else f"{doc_no} does not match {pat}"))
    elif doc_no and doc_type != "driving_license":
        # driving licences are covered by the dedicated dl_format check below
        pat = DOC_NUMBER_PATTERNS.get(nationality, DOC_NUMBER_PATTERNS["DEFAULT"])
        checks.append(_check(
            "doc_number_format", f"Document number format ({nationality or 'generic'})",
            bool(re.match(pat, doc_no)), "critical",
            f"{doc_no} matches {pat}" if re.match(pat, doc_no)
            else f"{doc_no} does not match {pat}"))
    if nationality:
        checks.append(_check(
            "nationality_code", "Nationality is a valid ISO-3166 alpha-3 code",
            nationality in ISO3, "warning",
            nationality if nationality in ISO3 else f"Unknown code {nationality}"))

    # --- dates --------------------------------------------------------------
    dob = (mrz or {}).get("dob", {}).get("date") or parse_date(values.get("dob"))
    expiry = (mrz or {}).get("expiry", {}).get("date") or parse_date(values.get("expiry"))
    dob_sev = "critical" if doc_type == "passport" else "warning"
    if dob:
        age = (today - dob).days / 365.25
        checks.append(_check(
            "dob_logic", "Date of birth is in the past and age plausible",
            dob < today and 0 <= age <= 105, "critical",
            f"DOB {dob.isoformat()} (age {age:.0f})" if dob < today
            else f"DOB {dob.isoformat()} is in the future"))
    else:
        checks.append(_check("dob_logic", "Date of birth present and parseable",
                             False, dob_sev, "DOB missing/unreadable"))
    if expiry:
        checks.append(_check(
            "expiry_logic", "Document not expired",
            expiry >= today, "critical",
            f"Expires {expiry.isoformat()}" if expiry >= today
            else f"EXPIRED on {expiry.isoformat()}"))
    else:
        # Aadhaar cards carry no expiry (lifetime validity); visas/permits
        # take their validity from the MRZ or the stamp, so a missing
        # visual expiry is only a warning for those document types
        expiry_sev = ("warning" if doc_type in ("visa", "permit", "id_card")
                      else "critical")
        checks.append(_check("expiry_logic", "Expiry date present and parseable",
                             False, expiry_sev, "Expiry missing/unreadable"))
    if dob and expiry:
        checks.append(_check(
            "date_order", "DOB precedes expiry date", dob < expiry, "critical",
            "Consistent" if dob < expiry else "DOB after expiry!"))

    # --- sex -----------------------------------------------------------------
    sex = (mrz or {}).get("sex") or values.get("sex", "")
    if doc_type in ("passport", "id_card"):
        checks.append(_check("sex_field", "Sex field valid (M/F/X)",
                             sex in ("M", "F", "X"), "warning",
                             sex or "missing"))

    # --- cross consistency visual zone vs MRZ -------------------------------
    if has_mrz:
        vis_name = (values.get("surname", "") + " " + values.get("given_names", "")).strip()
        mrz_name = (mrz["surname"] + " " + mrz["given_names"]).strip()
        if vis_name and mrz_name:
            sim = jaro_winkler(vis_name, mrz_name)
            checks.append(_check(
                "name_consistency", "Visual zone name matches MRZ name",
                sim >= 0.85, "critical",
                f"similarity {sim:.2f} ('{vis_name}' vs '{mrz_name}')"))
        # on a visa sticker the MRZ holds the visa number, so consistency
        # must be checked against the "Visa Number" field, not "Passport No"
        vis_dn = (values.get("visa_number") if doc_type == "visa"
                  else values.get("doc_number")) or ""
        if vis_dn:
            checks.append(_check(
                "docno_consistency", "Visual zone doc number matches MRZ",
                vis_dn.replace(" ", "") == doc_no, "critical",
                f"'{vis_dn}' vs MRZ '{doc_no}'"))
        vis_dob = parse_date(values.get("dob"))
        if vis_dob and dob:
            checks.append(_check(
                "dob_consistency", "Visual zone DOB matches MRZ DOB",
                vis_dob == dob, "critical",
                f"visual {vis_dob.isoformat()} vs MRZ {dob.isoformat()}"))

    # --- visa specific --------------------------------------------------------
    if doc_type == "visa":
        stay = values.get("stay_duration", "")
        import re as _re
        m = _re.search(r"(\d{1,3})", stay)
        days = int(m.group(1)) if m else None
        checks.append(_check(
            "visa_stay", "Stay duration within 1..1800 days",
            days is not None and 1 <= days <= 1800, "critical",
            stay or "missing"))
        entries = values.get("entries", "")
        checks.append(_check(
            "visa_entries", "Entry validation value recognised (M/S/1/2)",
            any(tok in entries.upper() for tok in ("M", "S", "1", "2")) if entries else False,
            "warning", entries or "missing"))

    # --- Aadhaar / driving licence specifics ----------------------------------
    if doc_type == "id_card":
        aad = values.get("aadhaar_number", "")
        if aad:
            import re as _re
            ok = bool(_re.match(r"^[2-9]\d{3}\s\d{4}\s\d{4}$", aad))
            checks.append(_check(
                "aadhaar_format", "Aadhaar number format (12 digits, no 0/1 lead)",
                ok, "critical", aad if ok else f"malformed: {aad}"))
    if doc_type == "driving_license":
        import re as _re
        # OCR reads 0 as O in the numeric part - normalise before validating
        norm = (doc_no or "")[:2] + (doc_no or "")[2:].upper().replace("O", "0")
        ok = bool(_re.match(r"^[A-Z]{2}\d{2}\s?\d{11}$", norm))
        checks.append(_check(
            "dl_format", "Indian DL number format (SS-RR YYYYYYYYYYY)",
            ok, "critical", doc_no if ok else f"malformed: {doc_no}"))
        bg = values.get("blood_group", "")
        if bg:
            checks.append(_check(
                "blood_group", "Blood group value recognised",
                bg in ("A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"),
                "warning", bg))

    # --- watchlist / blacklist -------------------------------------------------
    name = values.get("full_name") or ""
    if not name and mrz:
        name = (mrz["surname"] + " " + mrz["given_names"]).strip()
    hit = None
    best = 0.0
    norm = lambda s: " ".join(sorted((s or "").upper().split()))
    for w in watchlist:
        sim = max(jaro_winkler(name or "", w.get("full_name", "")),
                  jaro_winkler(norm(name), norm(w.get("full_name", ""))))
        best = max(best, sim)
        if sim >= WATCHLIST_NAME_THRESHOLD or (doc_no and w.get("doc_number") == doc_no):
            hit = w
            break
    checks.append(_check(
        "watchlist", "Name / document checked against security watchlist",
        hit is None, "critical",
        f"MATCH: {hit['full_name']} - {hit.get('reason', '')}" if hit
        else f"No hit (best name similarity {best:.2f})"))

    bl = doc_no in set(blacklist)
    checks.append(_check(
        "blacklist", "Document checked against lost/stolen/expired database",
        not bl, "critical",
        f"DOCUMENT {doc_no} IS BLACKLISTED" if bl else "Not listed"))

    # --- duplicate identities ---------------------------------------------------
    if doc_no and known_doc_numbers:
        others = [holder for dn, holder in known_doc_numbers
                  if dn and dn != doc_no and holder and name and
                  jaro_winkler(holder, name) >= 0.9]
        checks.append(_check(
            "duplicate_identity", "Same holder seen under other document numbers",
            not others, "warning",
            f"Also holds: {', '.join(others)}" if others else "No duplicates"))

    return checks


def summarize(checks):
    failed = [c for c in checks if not c["passed"]]
    critical = [c for c in failed if c["severity"] == "critical"]
    warnings = [c for c in failed if c["severity"] == "warning"]
    return {"failed": len(failed), "critical": len(critical),
            "warnings": len(warnings), "total": len(checks)}
