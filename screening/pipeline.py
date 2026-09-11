"""
End-to-end screening pipeline wiring all modules together:

  Module 1  ocr_engine / mrz        -> extraction
  Module 2  rules                   -> validation
  Module 3  tamper                  -> forgery forensics
  Module 4  faces                   -> biometric verification
  Module 5  db_verify               -> MySQL identity verification
  Module 6  email_verify            -> passport email verification

plus composite risk scoring, persistence and the hash-chained audit trail.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
from django.conf import settings
from django.core.files.storage import default_storage

from . import db_verify, faces, ocr_engine, rules, scoring, tamper
from .annotate import render_annotated
from .models import ExpiredDocument, ScreeningRecord, WatchlistEntry
from .mrz import parse_mrz

logger = logging.getLogger(__name__)


def store_upload(uploaded_file, subdir):
    """Persist an uploaded file under MEDIA_ROOT/<subdir>/, returns rel path."""
    import uuid
    name = f"{subdir}/{uuid.uuid4().hex[:10]}_{uploaded_file.name}"
    return default_storage.save(name, uploaded_file)


def run_screening(doc_rel, live_rel=None, doc_type_hint=None, save=True,
                  base_url=""):
    """doc_rel / live_rel are paths relative to MEDIA_ROOT."""
    t0 = time.time()
    doc_path = Path(settings.MEDIA_ROOT) / doc_rel
    live_path = (Path(settings.MEDIA_ROOT) / live_rel) if live_rel else None
    img = cv2.imread(str(doc_path))
    if img is None:
        raise ValueError(f"Unreadable image: {doc_path}")

    # ============== Module 1: extraction ==================================
    extraction = ocr_engine.extract_fields(img)
    doc_type = doc_type_hint or ocr_engine.classify_document(img,
                                                             extraction["raw_text"])
    mrz_lines, mrz_conf = ([], 0.0)
    if doc_type in ("passport", "visa", "id_card"):
        mrz_lines, mrz_conf = ocr_engine.read_mrz(img)
    mrz = parse_mrz(mrz_lines) if mrz_lines else None

    # cross-channel fusion
    if mrz:
        from .utils import jaro_winkler
        confs = extraction["confidences"]
        vals = extraction["values"]
        for field, mrz_val in (("surname", mrz["surname"]),
                               ("given_names", mrz["given_names"]),
                               ("doc_number", mrz["doc_number"])):
            vis = vals.get(field, "")
            if not vis or confs.get(field, 0) < 0.6 or \
                    jaro_winkler(vis, mrz_val) >= 0.8:
                vals[field] = mrz_val
        if vals.get("surname") and vals.get("given_names"):
            vals["full_name"] = f"{vals['surname']} {vals['given_names']}"

    ocr_conf = extraction["ocr_confidence"]
    if mrz_lines:
        ocr_conf = round((ocr_conf + mrz_conf) / 2, 3)

    # portrait location
    face_boxes = faces.detect_faces(img)
    portrait = face_boxes[0] if face_boxes else None

    # ============== Module 3: tampering ===================================
    tamper_res = tamper.run_tamper_suite(
        img, str(doc_path), face_bbox=portrait,
        text_regions=list(extraction["regions"].values()))

    # ============== Module 4: biometrics (doc vs live) =====================
    face_res = None
    live_img = None
    if live_path:
        live_img = cv2.imread(str(live_path))
        if live_img is not None:
            face_res = faces.verify(img, live_img,
                                    settings.SFACE_MATCH_THRESHOLD)

    # ============== Module 2: validation ==================================
    watch_rows = WatchlistEntry.objects.values("full_name", "doc_number", "reason")
    blacklist = set(ExpiredDocument.objects.values_list("doc_number", flat=True))
    doc_no = (mrz or {}).get("doc_number") or \
             extraction["values"].get("doc_number", "")
    if doc_type == "visa" and extraction["values"].get("doc_number"):
        doc_no = extraction["values"]["doc_number"]
    known = [(r.doc_number, r.holder_name) for r in
             ScreeningRecord.objects.exclude(doc_number="")
             .exclude(doc_number=doc_no)[:200]]
    checks = rules.run_validation(extraction["values"], mrz, doc_type,
                                  watchlist=list(watch_rows), blacklist=blacklist,
                                  known_doc_numbers=known)

    watch_failed = any(c["id"] in ("watchlist", "blacklist") and not c["passed"]
                       for c in checks)
    blacklist_failed = any(c["id"] == "blacklist" and not c["passed"]
                           for c in checks)
    face_mismatched = bool(face_res and face_res.get("similarity") is not None
                           and not face_res.get("matched"))

    holder = extraction["values"].get("full_name", "")
    if not holder and mrz:
        holder = f"{mrz['surname']} {mrz['given_names']}".strip()

    # ============== Module 5: DB identity verification ====================
    db_result = None
    doc_vs_db_face = None
    live_vs_db_face = None
    db_photo_img = None

    print(f'[DBG] Module 5: doc_type={doc_type}, doc_no={doc_no!r}, holder={holder!r}')
    if doc_no:
        try:
            db_result = db_verify.lookup_identity(doc_type, doc_no,
                                                  holder_name=holder)
            print(f'[DBG] DB result: found={db_result.get("found")}, '
                  f'gmail={db_result.get("gmail_id")}, '
                  f'photo={db_result.get("db_photo_path")}, '
                  f'detail={db_result.get("detail")}')
            # Merge DB checks into the main checks list
            if db_result.get("checks"):
                checks.extend(db_result["checks"])

            # Load DB photo for biometric cross-checks
            if db_result.get("found") and db_result.get("db_photo_path"):
                db_photo_img = db_verify.load_db_photo(
                    db_result["db_photo_path"])

                if db_photo_img is not None:
                    # Compare document photo with DB photo
                    doc_vs_db_face = db_verify.verify_photo_against_db(
                        img, db_photo_img)
                    doc_vs_db_face["comparison"] = "document_vs_db"

                    # Compare live photo with DB photo
                    if live_img is not None:
                        live_vs_db_face = db_verify.verify_live_against_db(
                            live_img, db_photo_img)
                        live_vs_db_face["comparison"] = "live_vs_db"

        except Exception as exc:
            logger.exception("DB verification failed: %s", exc)
            db_result = {
                "found": False, "table": None, "record": None,
                "db_photo_path": None, "gmail_id": None,
                "phone_number": None, "name_match": None,
                "detail": f"DB verification error: {exc}",
                "checks": [{
                    "id": "db_connection", "label": "Database connectivity",
                    "passed": False, "severity": "warning",
                    "detail": str(exc),
                }],
            }
            checks.extend(db_result["checks"])

    # ============== Composite risk ========================================
    risk = scoring.compute_risk(
        ocr_conf, checks, tamper_res["score"],
        watch_failed, face_res,
        thresholds=(settings.RISK_LOW_MAX, settings.RISK_MEDIUM_MAX),
        blacklist_failed=blacklist_failed,
        face_mismatched=face_mismatched,
        db_result=db_result,
        email_status=None,  # set after persistence for passport
        doc_vs_db_face=doc_vs_db_face,
        live_vs_db_face=live_vs_db_face,
    )

    result = {
        "doc_type": doc_type,
        "extraction": extraction,
        "mrz": mrz,
        "checks": checks,
        "validation_summary": rules.summarize(checks),
        "tamper": tamper_res,
        "face": face_res,
        "db_verification": db_result,
        "doc_vs_db_face": doc_vs_db_face,
        "live_vs_db_face": live_vs_db_face,
        "email_verification": None,
        "risk": risk,
        "holder_name": holder,
        "doc_number": doc_no,
        "processing_ms": int((time.time() - t0) * 1000),
        "face_boxes": face_boxes,
    }

    if not save:
        return result

    # ============== Persistence + audit trail =============================
    record = ScreeningRecord.objects.create(
        doc_type=doc_type,
        original=doc_rel,
        live_photo=live_rel or None,
        holder_name=holder,
        doc_number=doc_no,
        risk_score=risk["score"],
        risk_level=risk["level"],
        recommendation=risk["recommendation"],
        ocr_confidence=ocr_conf,
        processing_ms=result["processing_ms"],
        fields_json={
            "values": extraction["values"],
            "confidences": extraction["confidences"],
            "mrz": _jsonable(mrz),
            "contact": {
                "gmail_id": (db_result or {}).get("gmail_id"),
                "phone_number": (db_result or {}).get("phone_number"),
                "source_table": (db_result or {}).get("table"),
                "verified": bool(db_result and db_result.get("found")),
            },
        },
        checks_json=checks,
        tamper_json={
            "score": tamper_res["score"],
            "detectors": tamper_res["detectors"],
        },
        face_json=_build_face_json(face_res, doc_vs_db_face, live_vs_db_face),
        scoring_json=risk,
    )

    # Annotated image
    annotated_out = Path(settings.MEDIA_ROOT) / "annotated" / f"rec_{record.pk}.png"
    annotated_out.parent.mkdir(parents=True, exist_ok=True)
    render_annotated(img, annotated_out,
                     suspect_regions=tamper_res["regions"],
                     portrait=portrait,
                     value_regions=list(extraction["regions"].values()),
                     face_boxes=face_boxes)
    record.annotated = f"annotated/rec_{record.pk}.png"
    record.save(update_fields=["annotated"])

    # Audit events
    record.append_audit("screened", f"risk={risk['score']} ({risk['level']})")
    if watch_failed:
        record.append_audit("watchlist_hit")
    if risk["level"] == "HIGH":
        record.append_audit("escalated", risk["recommendation"])

    # DB verification audit
    if db_result:
        if db_result.get("found"):
            record.append_audit("db_identity_verified",
                                f"Found in {db_result['table']}")
            if doc_vs_db_face and doc_vs_db_face.get("matched"):
                record.append_audit("doc_photo_db_match",
                                    f"sim={doc_vs_db_face.get('similarity')}")
            elif doc_vs_db_face and doc_vs_db_face.get("similarity") is not None:
                record.append_audit("doc_photo_db_mismatch",
                                    f"sim={doc_vs_db_face.get('similarity')}")
            if live_vs_db_face and live_vs_db_face.get("matched"):
                record.append_audit("live_photo_db_match",
                                    f"sim={live_vs_db_face.get('similarity')}")
            elif live_vs_db_face and live_vs_db_face.get("similarity") is not None:
                record.append_audit("live_photo_db_mismatch",
                                    f"sim={live_vs_db_face.get('similarity')}")
        else:
            record.append_audit("db_identity_not_found", db_result.get("detail", ""))

    # ============== Contact details + informational email =================
    if db_result and db_result.get("found") and \
            (db_result.get("gmail_id") or db_result.get("phone_number")):
        record.append_audit(
            "contact_retrieved",
            f"email={db_result.get('gmail_id')} phone={db_result.get('phone_number')}")

        # Send a general information email to the holder (informational only)
        if db_result.get("gmail_id"):
            from . import email_verify
            try:
                sent = email_verify.send_info_email(
                    db_result["gmail_id"],
                    holder_name=holder,
                    doc_number=doc_no,
                    doc_type=doc_type,
                    risk_level=risk["level"],
                    record=record)
                if sent:
                    record.append_audit("info_email_sent",
                                        f"Sent to {db_result['gmail_id']}")
                else:
                    record.append_audit("info_email_failed",
                                        f"Could not send to {db_result['gmail_id']}")
            except Exception as exc:
                logger.exception("Info email failed: %s", exc)

    result["record_id"] = record.pk
    return result


def _build_face_json(face_res, doc_vs_db, live_vs_db):
    """Combine all face verification results into one JSON blob."""
    data = {}
    if face_res:
        data["doc_vs_live"] = face_res
    if doc_vs_db:
        data["doc_vs_db"] = doc_vs_db
    if live_vs_db:
        data["live_vs_db"] = live_vs_db
    # Backward compat: if only doc_vs_live, flatten
    if face_res and not doc_vs_db and not live_vs_db:
        return face_res
    return data if data else {}


def _jsonable(mrz):
    if not mrz:
        return None
    out = dict(mrz)
    for k in ("dob", "expiry"):
        if out.get(k) and out[k].get("date"):
            out[k] = dict(out[k], date=out[k]["date"].isoformat())
    return out
