"""
Database identity verification module.

Connects to the existing MySQL `identity_screening` database (READ-ONLY)
to verify that a screened identity exists and to retrieve the stored
photograph for biometric cross-check.

All queries use parameterized statements.  No DDL, INSERT, UPDATE or
DELETE is ever issued.

Column names are auto-discovered via DESCRIBE so the module adapts to
whatever schema is present.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

import cv2
import numpy as np
from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _get_connection():
    import pymysql
    cfg = settings.IDENTITY_DB
    return pymysql.connect(
        host=cfg["host"],
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        port=cfg["port"],
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
        read_timeout=10,
    )


@contextmanager
def _cursor():
    conn = _get_connection()
    try:
        cur = conn.cursor()
        yield cur
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Schema discovery cache
# ---------------------------------------------------------------------------
_schema_cache: dict[str, list[str]] = {}


def _get_columns(cur, table: str) -> list[str]:
    """Return column names for a table, cached after first call."""
    if table not in _schema_cache:
        cur.execute("DESCRIBE `%s`" % table)
        _schema_cache[table] = [r["Field"] for r in cur.fetchall()]
    return _schema_cache[table]


def _find_col(columns: list[str], *candidates: str) -> str | None:
    """Return the first candidate that exists in columns (case-insensitive)."""
    col_lower = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in col_lower:
            return col_lower[cand.lower()]
    return None


# ---------------------------------------------------------------------------
# Table → doc_type mapping
# ---------------------------------------------------------------------------

_TABLE_MAP = {
    "passport":        "passport",
    "driving_license": "driving_license",
    "visa":            "visa",
    "id_card":         "aadhaar",
    "aadhaar":         "aadhaar",
}

# Candidate column names for each logical field — tried in order
_LOOKUP_CANDIDATES = {
    "passport":        ["passport_number", "passport_no", "doc_number", "number"],
    "driving_license": ["license_number", "licence_number", "dl_number",
                        "doc_number", "number"],
    "visa":            ["visa_number", "visa_no", "doc_number", "number"],
    "aadhaar":         ["aadhaar_number", "aadhaar_no", "uid", "number"],
}

_NAME_CANDIDATES = [
    "name", "full_name", "holder_name",
    "first_name", "fname", "given_name",
]
_LAST_NAME_CANDIDATES = ["last_name", "lname", "surname", "family_name"]
_PHOTO_CANDIDATES = ["photo", "photograph", "photo_path", "image", "face_photo"]
_EMAIL_CANDIDATES = ["gmail_id", "email", "email_id", "gmail", "mail"]
_PHONE_CANDIDATES = ["phone_number", "phone", "mobile", "contact", "mobile_number"]


def _normalise_doc_number(raw: str) -> str:
    return raw.replace(" ", "").replace("-", "").upper()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup_identity(doc_type: str, doc_number: str,
                    holder_name: str = "") -> dict:
    from .utils import jaro_winkler

    table = _TABLE_MAP.get(doc_type)
    if table is None:
        return {
            "found": False, "table": None, "record": None,
            "db_photo_path": None, "gmail_id": None, "phone_number": None,
            "name_match": None,
            "detail": f"No DB table mapped for doc_type={doc_type}",
            "checks": [],
        }

    clean_num = _normalise_doc_number(doc_number)
    if not clean_num:
        return {
            "found": False, "table": table, "record": None,
            "db_photo_path": None, "gmail_id": None, "phone_number": None,
            "name_match": None,
            "detail": "Empty document number - cannot query DB",
            "checks": [],
        }

    checks = []
    try:
        with _cursor() as cur:
            columns = _get_columns(cur, table)
            logger.info("Table `%s` columns: %s", table, columns)

            # Resolve actual column names
            lookup_col = _find_col(columns,
                                   *_LOOKUP_CANDIDATES.get(doc_type,
                                       _LOOKUP_CANDIDATES.get(table, ["number"])))
            if not lookup_col:
                return {
                    "found": False, "table": table, "record": None,
                    "db_photo_path": None, "gmail_id": None,
                    "phone_number": None, "name_match": None,
                    "detail": f"Cannot find lookup column in `{table}` "
                              f"(columns: {columns})",
                    "checks": [],
                }

            # Build SELECT with all available columns
            cols_sql = ", ".join(f"`{c}`" for c in columns)
            query = f"SELECT {cols_sql} FROM `{table}` WHERE `{lookup_col}` = %s LIMIT 1"

            cur.execute(query, (clean_num,))
            row = cur.fetchone()

    except Exception as exc:
        logger.exception("DB lookup failed for %s/%s", table, clean_num)
        return {
            "found": False, "table": table, "record": None,
            "db_photo_path": None, "gmail_id": None, "phone_number": None,
            "name_match": None,
            "detail": f"Database error: {exc}",
            "checks": [{
                "id": "db_connection", "label": "Database connectivity",
                "passed": False, "severity": "warning",
                "detail": str(exc),
            }],
        }

    if row is None:
        checks.append({
            "id": "db_identity_exists", "label": "Identity exists in DB",
            "passed": False, "severity": "critical",
            "detail": f"No record found in `{table}` for "
                      f"{lookup_col}={clean_num}",
        })
        return {
            "found": False, "table": table, "record": None,
            "db_photo_path": None, "gmail_id": None, "phone_number": None,
            "name_match": None,
            "detail": f"Identity NOT found in `{table}`",
            "checks": checks,
        }

    # Identity exists
    checks.append({
        "id": "db_identity_exists", "label": "Identity exists in DB",
        "passed": True, "severity": "critical",
        "detail": f"Record found in `{table}` for {lookup_col}={clean_num}",
    })

    # --- Resolve name columns ---
    name_col = _find_col(columns, *_NAME_CANDIDATES)
    last_col = _find_col(columns, *_LAST_NAME_CANDIDATES)

    if name_col and last_col:
        db_full = f"{row.get(name_col, '')} {row.get(last_col, '')}".strip()
    elif name_col:
        db_full = str(row.get(name_col, "")).strip()
    elif last_col:
        db_full = str(row.get(last_col, "")).strip()
    else:
        db_full = ""

    name_sim = None
    if holder_name and db_full:
        name_sim = round(jaro_winkler(holder_name.upper(), db_full.upper()), 3)
        passed = name_sim >= 0.80
        checks.append({
            "id": "db_name_match", "label": "Name matches DB record",
            "passed": passed, "severity": "warning",
            "detail": f"OCR name='{holder_name}' vs DB='{db_full}' "
                      f"(similarity={name_sim})",
        })

    # --- Resolve photo / email / phone ---
    photo_col = _find_col(columns, *_PHOTO_CANDIDATES)
    email_col = _find_col(columns, *_EMAIL_CANDIDATES)
    phone_col = _find_col(columns, *_PHONE_CANDIDATES)

    photo_path = str(row.get(photo_col, "")) if photo_col else None
    gmail_id = str(row.get(email_col, "")) if email_col else None
    phone_number = str(row.get(phone_col, "")) if phone_col else None

    # Clean empty strings to None
    if not photo_path:
        photo_path = None
    if not gmail_id:
        gmail_id = None
    if not phone_number:
        phone_number = None

    # Build serialisable record (skip photo blob)
    record_clean = {}
    for k, v in row.items():
        if k == photo_col:
            continue
        if hasattr(v, "isoformat"):
            record_clean[k] = v.isoformat()
        elif isinstance(v, (bytes, bytearray)):
            record_clean[k] = f"<binary {len(v)} bytes>"
        else:
            record_clean[k] = v

    return {
        "found": True,
        "table": table,
        "record": record_clean,
        "db_photo_path": photo_path,
        "gmail_id": gmail_id,
        "phone_number": phone_number,
        "name_match": name_sim,
        "detail": f"Identity verified in `{table}`",
        "checks": checks,
    }


def load_db_photo(photo_path: str) -> np.ndarray | None:
    """Load the photograph referenced by the DB photo column."""
    if not photo_path:
        return None

    # Try absolute first
    p = Path(photo_path)
    if p.is_file():
        img = cv2.imread(str(p))
        if img is not None:
            return img

    # Try relative to MEDIA_ROOT
    p = Path(settings.MEDIA_ROOT) / photo_path
    if p.is_file():
        img = cv2.imread(str(p))
        if img is not None:
            return img

    # Try relative to BASE_DIR
    p = Path(settings.BASE_DIR) / photo_path
    if p.is_file():
        img = cv2.imread(str(p))
        if img is not None:
            return img

    logger.warning("DB photo not found at any known path: %s", photo_path)
    return None


def verify_photo_against_db(document_img, db_photo_img, threshold=None):
    """Compare the face on the scanned document with the DB photograph."""
    from . import faces
    if threshold is None:
        threshold = settings.SFACE_MATCH_THRESHOLD
    if db_photo_img is None:
        return {
            "matched": False, "similarity": None,
            "detail": "DB photo not available",
            "backend": faces.backend_name(),
        }
    return faces.verify(document_img, db_photo_img, threshold)


def verify_live_against_db(live_img, db_photo_img, threshold=None):
    """Compare the live capture face with the DB photograph."""
    from . import faces
    if threshold is None:
        threshold = settings.SFACE_MATCH_THRESHOLD
    if db_photo_img is None:
        return {
            "matched": False, "similarity": None,
            "detail": "DB photo not available",
            "backend": faces.backend_name(),
        }
    if live_img is None:
        return {
            "matched": False, "similarity": None,
            "detail": "No live photo provided",
            "backend": faces.backend_name(),
        }
    return faces.verify(live_img, db_photo_img, threshold)
