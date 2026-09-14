# BORDER SENTINEL

**AI-based fake identity & document screening system for border checkpoints.**

Border Sentinel takes a photograph or scan of a travel document — optionally
alongside a live capture of the person presenting it — and returns a composite
risk score with a full, auditable explanation of how that score was reached.
It combines OCR/MRZ extraction, an ICAO-9303 rule engine, image-forensics
tamper detectors, face biometrics, a read-only identity database lookup and an
email confirmation loop, then persists every decision behind a hash-chained
audit trail.

Built with Django 5 + Django REST Framework, OpenCV and Tesseract. SQLite
backs the application itself; an external MySQL database provides the
identity-of-record lookup.

---

## Screening pipeline

Every upload runs through `screening/pipeline.py:run_screening()`, which wires
six modules together:

| # | Module | File | What it does |
|---|--------|------|--------------|
| 1 | Extraction | `ocr_engine.py`, `mrz.py` | Tesseract reads the visual zone (label/value pairs) and the machine-readable zone. `mrz.py` parses TD1/TD2/TD3, validates the ICAO 9303 check digits and repairs confusable OCR glyphs (`O/0`, `I/1`, `S/5`…) — flagging every repair it makes. Visual and MRZ channels are then fused with Jaro-Winkler agreement. |
| 2 | Validation | `rules.py` | Checks MRZ presence and checksums, ISO-3166 nationality codes, per-country document-number formats, date logic (DOB / expiry / issue ordering), cross-field consistency, watchlist and blacklist hits, and duplicate-identity collisions against past records. Each check reports `info` / `warning` / `critical`. |
| 3 | Tamper forensics | `tamper.py` | Six detectors: Error Level Analysis (double-JPEG recompression), noise-residual inconsistency, copy-move duplication, EXIF editing-software fingerprints, portrait splice-seam analysis, and text-region statistics. Statistics are computed on *flat* blocks only, because forgery traces live in the smooth areas between the printing. |
| 4 | Biometrics | `faces.py` | OpenCV YuNet detection + SFace 128-d embeddings (ONNX, cosine threshold `0.363`). Falls back to Haar cascades with a classical histogram descriptor when the ONNX weights are absent, so the pipeline degrades rather than breaks. |
| 5 | Identity DB | `db_verify.py` | Read-only, parameterised lookups against a MySQL `identity_screening` database (`passport`, `visa`, `driving_license`, `aadhaar` tables). Columns are auto-discovered via `DESCRIBE`, so the module adapts to whatever schema it finds. Retrieves the on-file photograph for document-vs-DB and live-vs-DB biometric cross-checks, plus contact details. |
| 6 | Email verification | `email_verify.py` | Sends the document holder a tokenised approve/reject link (10-minute default expiry) and folds their response back into the risk score. |

Results are then combined by `scoring.py`, persisted as a `ScreeningRecord`,
and rendered as an analyst overlay image (`annotate.py`) marking the portrait,
extracted value regions and suspect areas.

### Risk scoring

`scoring.py` produces a 0–100 score from weighted components — OCR confidence
(8), validation failures (15), tampering (25), watchlist (12), face match (15),
DB verification (15) and email verification (10) — then applies hard policy
gates that raise the floor regardless of the weighted total:

| Condition | Minimum score |
|-----------|---------------|
| Blacklisted document | 75 |
| Email verification explicitly rejected | 75 |
| Document photo ≠ database photo | 70 |
| Live photo ≠ document photo | 70 |
| Identity not found in the DB | 65 |
| Watchlist hit | 60 |
| ≥ 2 critical validation failures | 60 |
| 1 critical validation failure | 45 |

Bands: **LOW** < 30 ≤ **MEDIUM** < 60 ≤ **HIGH**, mapping to
*standard clearance*, *refer to secondary inspection* and
*hold traveller — refer to document forgery unit*.

### Audit trail

Every record carries a SHA-256 hash-chained `AuditEvent` log
(`ScreeningRecord.append_audit`). Each event hashes its own payload together
with the previous event's digest, so `verify_audit_chain()` detects any
retroactive edit or deletion. The chain status is shown on the record detail
page and returned by the API.

---

## Setup

### Requirements

- Python 3.10+
- Tesseract OCR on `PATH` (or set `TESSERACT_CMD`; the standard Windows
  installer locations under `C:\Program Files\Tesseract-OCR` are probed
  automatically)
- MySQL with an `identity_screening` database — optional; without it Module 5
  records a connectivity warning and contributes its full weight to the risk
  score
- `pymysql`, if you use the identity database (not listed in
  `requirements.txt`)

### Linux / macOS

`setup.sh` bootstraps everything — virtualenv, dependencies, Tesseract, the
ONNX face models, migrations and the demo seed:

```bash
./setup.sh
.venv/bin/python manage.py runserver 0.0.0.0:8000
```

### Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install pymysql            # only if using the identity database
python manage.py migrate
python manage.py seed_demo     # optional: watchlist, blacklist, synthetic docs
python manage.py runserver
```

The face models (`face_detection_yunet_2023mar.onnx`,
`face_recognition_sface_2021dec.onnx`) ship in `screening/models/`; `setup.sh`
re-downloads them from the OpenCV zoo if they are missing.

### Configuration

The identity database and SMTP settings are read from the environment
(`config/settings.py`):

| Variable | Default |
|----------|---------|
| `IDENTITY_DB_HOST` / `_PORT` / `_NAME` | `localhost` / `3306` / `identity_screening` |
| `IDENTITY_DB_USER` / `IDENTITY_DB_PASSWORD` | `root` / — |
| `EMAIL_HOST` / `EMAIL_PORT` | `smtp.gmail.com` / `587` |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | — |
| `DEFAULT_FROM_EMAIL` | — |
| `EMAIL_VERIFICATION_EXPIRY` | `600` (seconds) |

> **Demo configuration.** `config/settings.py` ships with `DEBUG = True`,
> `ALLOWED_HOSTS = ["*"]`, a hardcoded `SECRET_KEY` and hardcoded fallback
> credentials. Set the environment variables above and replace the secret key
> before running this anywhere but a local demo.

---

## Usage

### Web interface

| Route | Purpose |
|-------|---------|
| `/` | Dashboard — volumes, risk-level and document-type breakdowns, average processing time |
| `/screen/` | Upload a document (plus an optional live photo or webcam capture) |
| `/records/` | Searchable record list, filterable by risk level and document type |
| `/record/<pk>/` | Full report: extracted fields, every validation check, tamper detector scores, face comparisons, annotated overlay, audit chain, and analyst status / notes |
| `/watchlist/` | Manage watchlist and blacklisted-document entries |
| `/admin/` | Django admin |

Live traveller photos can be captured server-side through OpenCV via the
`/camera/stream/`, `/camera/snapshot/` and `/camera/capture/` endpoints.

### JSON API

```
GET  /api/health/           backend status, face backend in use, record count
POST /api/screen/           multipart: document (required), live_photo, doc_type
GET  /api/records/          latest 100 records; ?level=LOW|MEDIUM|HIGH
GET  /api/records/<pk>/     full record + audit trail + chain validity
GET  /api/watchlist/        watchlist and blacklist contents
POST /api/watchlist/        add a watchlist entry
```

```bash
curl -F document=@passport.jpg -F live_photo=@selfie.jpg \
     http://localhost:8000/api/screen/
```

The response carries the risk score and band, the recommendation, the failed
checks, the tamper score and a `modules` block with per-module detail.

---

## Synthetic demo corpus

`screening/synthetic.py` generates bilingual (Hindi / English) passports, visas,
Aadhaar-style ID cards and driving licences from scratch with PIL — including
deliberately forged variants: swapped portraits, altered dates of birth,
locally recompressed regions and edited metadata. `manage.py seed_demo` writes
the corpus and seeds a watchlisted identity plus a blacklisted document number,
giving a repeatable end-to-end demo with no real personal data.

## Tests

```bash
python manage.py test screening
```

39 tests across nine modules cover MRZ parsing and checksum repair, the rule
engine, each tamper detector, face verification, OCR extraction, document
layouts, the full pipeline and the web views.

## Layout

```
config/              Django project (settings, URLs, WSGI/ASGI)
screening/
  ocr_engine.py      Module 1 — Tesseract visual-zone extraction
  mrz.py             Module 1 — ICAO 9303 TD1/TD2/TD3 parsing
  rules.py           Module 2 — validation rule engine
  tamper.py          Module 3 — forensic tamper detectors
  faces.py           Module 4 — YuNet / SFace biometrics
  db_verify.py       Module 5 — read-only MySQL identity lookup
  email_verify.py    Module 6 — tokenised holder confirmation
  scoring.py         Composite risk scoring and policy gates
  pipeline.py        End-to-end orchestration
  annotate.py        Analyst overlay rendering
  camera.py          Server-side OpenCV capture endpoints
  synthetic.py       Synthetic document generator
  models.py          Records, watchlists, hash-chained audit events
  views.py, api.py   Web UI and REST API
  templates/ static/ models/ fonts/ tests/
media/               Uploaded documents, live photos, annotated overlays
setup.sh             One-shot environment bootstrap
```


