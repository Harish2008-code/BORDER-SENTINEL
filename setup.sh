#!/usr/bin/env bash
# One-shot environment bootstrap for BORDER SENTINEL (demo mode).
#
# Handles PEP 668 "externally-managed-environment" (Kali/Debian/Ubuntu):
# dependencies are installed into a project virtualenv (.venv); only if a
# venv truly cannot be created does it fall back to a user-level install
# with --break-system-packages.
set -e
cd "$(dirname "$0")"

PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || { echo "ERROR: python3 not found on PATH"; exit 1; }

VENV=".venv"
PIP=""
PYBIN="$PY"

echo "[1/5] Python dependencies"
if [ -x "$VENV/bin/pip" ]; then
  PIP="$VENV/bin/pip";  PYBIN="$VENV/bin/python"
elif [ -x "$VENV/Scripts/pip.exe" ]; then
  PIP="$VENV/Scripts/pip.exe"; PYBIN="$VENV/Scripts/python.exe"
else
  echo "  creating virtualenv at $VENV"
  "$PY" -m venv "$VENV" || {
    echo "  venv creation failed - installing python3-venv via apt"
    (sudo -n apt-get update -qq && \
     sudo -n apt-get install -y --no-install-recommends python3-venv python3-full) || true
    "$PY" -m venv "$VENV" || true
  }
  if [ -x "$VENV/bin/pip" ]; then
    PIP="$VENV/bin/pip"; PYBIN="$VENV/bin/python"
  elif [ -x "$VENV/Scripts/pip.exe" ]; then
    PIP="$VENV/Scripts/pip.exe"; PYBIN="$VENV/Scripts/python.exe"
  fi
fi

if [ -n "$PIP" ]; then
  "$PIP" install -q --upgrade pip
  "$PIP" install -q -r requirements.txt
else
  echo "  WARNING: venv unavailable - user-level install with PEP 668 override"
  "$PY" -m pip install -q --user --break-system-packages --upgrade pip || true
  "$PY" -m pip install -q --user --break-system-packages -r requirements.txt
fi

echo "[2/5] Tesseract OCR (system package)"
if ! command -v tesseract >/dev/null; then
  sudo -n apt-get update -qq || true
  sudo -n apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng || true
fi
tesseract --version 2>/dev/null | head -1 || \
  echo "WARNING: tesseract missing - OCR module degraded"

echo "[3/5] Face models (OpenCV zoo ONNX)"
mkdir -p screening/models
[ -f screening/models/face_detection_yunet_2023mar.onnx ] || \
  curl -sL -o screening/models/face_detection_yunet_2023mar.onnx \
    https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
[ -f screening/models/face_recognition_sface_2021dec.onnx ] || \
  curl -sL -o screening/models/face_recognition_sface_2021dec.onnx \
    https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx

echo "[4/5] Migrations"
"$PYBIN" manage.py migrate --no-input

echo "[5/5] Demo seed (watchlist, blacklist, synthetic documents)"
"$PYBIN" manage.py seed_demo

echo
echo "Done. Start the server with:"
if [ "$PYBIN" != "$PY" ]; then
  echo "  $PYBIN manage.py runserver 0.0.0.0:8000"
  echo "  (or activate first: source $VENV/bin/activate && python manage.py runserver 0.0.0.0:8000)"
else
  echo "  $PY manage.py runserver 0.0.0.0:8000"
fi
