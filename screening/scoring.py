"""Composite risk scoring across all modules including DB verification."""
from __future__ import annotations

from .utils import clamp

WEIGHTS = {
    "ocr": 8.0,
    "validation": 15.0,
    "tamper": 25.0,
    "watchlist": 12.0,
    "face": 15.0,
    "db_verification": 15.0,
    "email_verification": 10.0,
}

RECOMMENDATIONS = {
    "LOW": "Standard clearance - proceed",
    "MEDIUM": "Refer to secondary inspection",
    "HIGH": "Hold traveller - refer to document forgery unit",
}


def compute_risk(ocr_confidence, checks, tamper_score, watchlist_failed,
                 face_result=None, thresholds=(30, 60),
                 blacklist_failed=False, face_mismatched=False,
                 db_result=None, email_status=None,
                 doc_vs_db_face=None, live_vs_db_face=None):
    breakdown = []

    # --- OCR confidence ---
    conf = ocr_confidence if ocr_confidence is not None else 0.7
    ocr_c = (1.0 - clamp(conf, 0, 1)) * WEIGHTS["ocr"]
    breakdown.append({"component": "ocr_confidence", "weight": WEIGHTS["ocr"],
                      "value": round(conf, 3), "contribution": round(ocr_c, 1)})

    # --- Validation checks ---
    critical = sum(1 for c in checks if not c["passed"] and c["severity"] == "critical")
    warnings = sum(1 for c in checks if not c["passed"] and c["severity"] == "warning")
    val_c = min(WEIGHTS["validation"], critical * 8.0 + warnings * 3.0)
    breakdown.append({"component": "validation", "weight": WEIGHTS["validation"],
                      "value": f"{critical} critical / {warnings} warning",
                      "contribution": round(val_c, 1)})

    # --- Tampering ---
    tamper_c = clamp(tamper_score, 0, 100) / 100.0 * WEIGHTS["tamper"]
    breakdown.append({"component": "tampering", "weight": WEIGHTS["tamper"],
                      "value": round(tamper_score, 1), "contribution": round(tamper_c, 1)})

    # --- Watchlist ---
    watch_c = WEIGHTS["watchlist"] if watchlist_failed else 0.0
    breakdown.append({"component": "watchlist", "weight": WEIGHTS["watchlist"],
                      "value": "hit" if watchlist_failed else "clear",
                      "contribution": round(watch_c, 1)})

    # --- Face (doc vs live) ---
    if face_result is None:
        face_c = 0.4 * WEIGHTS["face"]
        face_val = "not presented"
    elif face_result.get("similarity") is None:
        face_c = 0.8 * WEIGHTS["face"]
        face_val = face_result.get("detail", "no face")
    else:
        sim = face_result["similarity"]
        confidence = clamp((sim - 0.1) / 0.7, 0, 1)
        if face_result.get("matched"):
            confidence = max(confidence, 0.9)
        face_c = (1.0 - confidence) * WEIGHTS["face"]
        face_val = round(sim, 3)
    breakdown.append({"component": "face_verification", "weight": WEIGHTS["face"],
                      "value": face_val, "contribution": round(face_c, 1)})

    # --- DB verification ---
    db_c = 0.0
    if db_result is None:
        db_c = 0.3 * WEIGHTS["db_verification"]
        db_val = "not checked"
    elif not db_result.get("found"):
        db_c = WEIGHTS["db_verification"]
        db_val = "identity NOT found"
    else:
        # Identity found — check sub-components
        db_val = "identity found"
        name_match = db_result.get("name_match")
        if name_match is not None and name_match < 0.80:
            db_c += 0.4 * WEIGHTS["db_verification"]
            db_val += f" (name mismatch: {name_match})"

        # Doc photo vs DB photo comparison
        if doc_vs_db_face is not None:
            if doc_vs_db_face.get("similarity") is not None:
                if not doc_vs_db_face.get("matched"):
                    db_c += 0.4 * WEIGHTS["db_verification"]
                    db_val += " (doc-photo mismatch)"
            elif doc_vs_db_face.get("detail", "").startswith("DB photo"):
                pass  # no DB photo available — don't penalise

        # Live photo vs DB photo comparison
        if live_vs_db_face is not None:
            if live_vs_db_face.get("similarity") is not None:
                if not live_vs_db_face.get("matched"):
                    db_c += 0.2 * WEIGHTS["db_verification"]
                    db_val += " (live-DB mismatch)"

    db_c = min(db_c, WEIGHTS["db_verification"])
    breakdown.append({"component": "db_verification", "weight": WEIGHTS["db_verification"],
                      "value": db_val, "contribution": round(db_c, 1)})

    # --- Email verification (passport only) ---
    email_c = 0.0
    if email_status is None or email_status.get("status") == "NOT_REQUIRED":
        email_c = 0.0
        email_val = "not required"
    elif email_status["status"] == "APPROVED":
        email_c = 0.0
        email_val = "approved"
    elif email_status["status"] == "PENDING":
        email_c = 0.5 * WEIGHTS["email_verification"]
        email_val = "pending"
    elif email_status["status"] == "REJECTED":
        email_c = WEIGHTS["email_verification"]
        email_val = "rejected"
    elif email_status["status"] == "EXPIRED":
        email_c = 0.7 * WEIGHTS["email_verification"]
        email_val = "expired"
    else:
        email_c = 0.3 * WEIGHTS["email_verification"]
        email_val = email_status.get("status", "unknown")
    breakdown.append({"component": "email_verification",
                      "weight": WEIGHTS["email_verification"],
                      "value": email_val, "contribution": round(email_c, 1)})

    # --- Composite score ---
    score = int(round(clamp(sum(b["contribution"] for b in breakdown), 0, 100)))

    # Policy gates
    if critical >= 2:
        score = max(score, 60)
    elif critical >= 1:
        score = max(score, 45)
    if blacklist_failed:
        score = max(score, 75)
    elif face_mismatched:
        score = max(score, 70)
    elif watchlist_failed:
        score = max(score, 60)

    # DB-specific gates
    if db_result is not None and not db_result.get("found"):
        score = max(score, 65)  # unverified identity
    if doc_vs_db_face and doc_vs_db_face.get("similarity") is not None \
            and not doc_vs_db_face.get("matched"):
        score = max(score, 70)  # document photo doesn't match DB
    if email_status and email_status.get("status") == "REJECTED":
        score = max(score, 75)  # explicitly rejected

    lo, med = thresholds
    level = "LOW" if score < lo else ("MEDIUM" if score < med else "HIGH")
    return {
        "score": score,
        "level": level,
        "recommendation": RECOMMENDATIONS[level],
        "breakdown": breakdown,
    }
